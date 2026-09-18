"""FastAPI 진입점 — POST /query (+ HITL 재개용 POST /query/approve).

실제 요청 처리 로직(가드레일 -> 그래프 실행 -> 구조화 -> 마스킹)은 pipeline.py에
있다. evaluation/run_eval.py가 서버를 띄우지 않고도 같은 경로를 재사용하기
위해서다. 이 파일은 FastAPI 라우팅과 그래프/체크포인터/체인 수명주기만 다룬다.

load_dotenv()를 여기서 호출하는 이유: .env에 AWS 자격 증명뿐 아니라 LangSmith
트레이싱 변수(LANGCHAIN_TRACING_V2 등, 패턴 11)도 들어가는데, 프로세스 시작 시
한 번 로드해 두지 않으면 os.environ에 반영되지 않아 어느 쪽도 동작하지 않는다.

API 스펙(개발방향성 §2-2)은 {question} -> {answer, contexts, trace} 단일 요청/응답을
가정하지만, 실행 도구(stop_resource 등)는 사람 승인(HITL)이 끼어들 수 있다. 그래서
이 프로젝트는 스펙을 다음과 같이 확장했다 (구현 전 의사결정 C):
  - 승인이 필요 없으면: 기존 스펙 그대로 {answer, contexts, trace}(+structured) 반환
  - 승인이 필요하면: {status: "pending_approval", thread_id, request: {tool, args, reason}}
    를 반환하고, 사용자가 POST /query/approve {thread_id, approved} 로 재개한다.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel

load_dotenv()

# Dockerfile/run.sh/README는 전부 `uvicorn src.app:app`으로 이 파일을 src.app
# 서브모듈로 임포트한다. 그 방식은 저장소 루트만 sys.path에 넣고 src/ 자체는
# 안 넣어서, 바로 아래의 평범한(상대경로 없는) 형제 모듈 import(guardrails 등)가
# ModuleNotFoundError로 죽는다. mcp_servers/cost_server.py와 evaluation/run_eval.py는
# 이미 이 문제를 sys.path.insert로 피해가고 있었는데 여기만 빠뜨렸다.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import batch  # noqa: E402
import guardrails  # noqa: E402
import mcp_client  # noqa: E402
import pipeline  # noqa: E402
import qa_history  # noqa: E402
from agent import build_supervisor  # noqa: E402
from answer_chain import build_answer_chain  # noqa: E402

CHECKPOINT_DB = str(Path(__file__).resolve().parent.parent / "data" / "checkpoints.db")

logger = logging.getLogger(__name__)

_graph = None  # 첫 요청에서 지연 생성 — 임베딩·LLM·MCP 서버 기동(AWS 호출 포함)을 임포트 시점에 하지 않기 위함
_answer_chain = None
_checkpointer = None
_checkpointer_cm = None  # AsyncSqliteSaver의 async context manager 자체 — lifespan 동안 열어둬야 한다
_mcp_stack = None  # MCP 세션 3개를 담은 AsyncExitStack — 그래프와 함께 지연 생성, lifespan 동안 열어둬야 한다
_init_lock = asyncio.Lock()
# 안전장치 2 — MCP 자식 프로세스가 죽는 등 그래프 내부에서 예외가 새어나오면
# True로 표시해, 다음 요청에서 세션·그래프를 통째로 다시 만든다(SAFEGUARDS.md
# 참고). 지금 구조는 그래프 노드들이 특정 도구 함수 참조를 클로저로 들고 있어서
# 죽은 프로바이더 하나만 골라 재연결할 수는 없다 — 대신 다음 요청이 전체를
# 새로 만드는 "거칠지만 확실한" 복구를 한다.
_graph_broken = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버가 떠 있는 동안 SqliteSaver 연결을 하나 열어둔다.

    이전엔 MemorySaver()를 썼는데, 그건 프로세스 메모리에만 있어서 서버가
    재시작되면 진행 중이던 HITL 승인 대기(interrupt 상태)가 전부 사라졌다 —
    /query에서 pending_approval을 받은 사용자가 재시작 후 /query/approve를
    보내면 "그런 thread_id 없음"이 된다. AsyncSqliteSaver로 바꾸면 같은 상태가
    data/checkpoints.db에 남아 재시작 후에도 승인을 이어갈 수 있다.
    """
    global _checkpointer, _checkpointer_cm
    _checkpointer_cm = AsyncSqliteSaver.from_conn_string(CHECKPOINT_DB)
    _checkpointer = await _checkpointer_cm.__aenter__()
    batch_task = asyncio.create_task(batch.scheduler_loop())
    try:
        yield
    finally:
        batch_task.cancel()
        try:
            await batch_task
        except asyncio.CancelledError:
            pass
        # _mcp_stack은 첫 /query 전까지 None일 수 있다(그래프 지연 생성) — 그때는 닫을
        # 세션이 아예 없으므로 건너뛴다.
        if _mcp_stack is not None:
            await _mcp_stack.aclose()
        await _checkpointer_cm.__aexit__(None, None, None)


app = FastAPI(title="멀티클라우드 비용 최적화 & 이상 비용 탐지 에이전트", lifespan=lifespan)


async def _get_graph():
    """그래프와 구조화 체인을 지연 생성한다. mcp_client.open_persistent_mcp_tools()를 직접 await 한다 —

    FastAPI 요청 핸들러는 이미 실행 중인 이벤트 루프 안에 있어서, 내부적으로
    asyncio.run()을 쓰는 mcp_client.load_mcp_tools_sync()를 부르면
    "cannot be called from a running event loop" 로 죽는다.

    open_persistent_mcp_tools()를 쓰는 이유(성능): langchain-mcp-adapters의
    client.get_tools()는 도구 호출마다 새 세션(=새 자식 프로세스, fastmcp
    재import 포함 실측 약 1.5초)을 여는 게 기본 동작이다 — 상시 떠 있는 이
    서버에서는 그래프 생성 시 세션 3개를 한 번만 열어 프로세스 수명 내내
    재사용하는 게 맞다. 반환된 AsyncExitStack(_mcp_stack)을 계속 들고 있어야
    세션이 안 닫히므로, lifespan 종료 시 aclose()해야 한다(위 lifespan 참고).

    _init_lock으로 감싸는 이유: 락 없이 `if _graph is None`만 보면, 콜드 스타트
    직후 동시에 들어온 요청 여러 개가 전부 None을 보고 각자 MCP 서버 3개씩
    따로 기동해버린다 — 락으로 첫 초기화를 한 번만 돌게 막는다.

    안전장치 2(SAFEGUARDS.md) — `_graph_broken`이 True면(mark_graph_broken() 참고)
    기존 그래프가 있어도 무시하고 다시 만든다. MCP 자식 프로세스 하나가 죽으면
    그 프로바이더로 가는 모든 이후 호출이 서버 재시작 전까지 계속 실패하는
    문제를 고치기 위함 — 죽은 세션만 골라 재연결할 방법은 없어서(그래프 노드가
    특정 도구 함수를 클로저로 들고 있음) 세션 3개+그래프를 통째로 다시 만든다.
    """
    global _graph, _answer_chain, _mcp_stack, _graph_broken
    if _graph is not None and not _graph_broken:
        return _graph
    async with _init_lock:
        if _graph is None or _graph_broken:  # 락을 기다리는 동안 다른 요청이 이미 고쳤을 수 있다
            if _mcp_stack is not None:
                try:
                    await _mcp_stack.aclose()
                except Exception:  # noqa: BLE001 — 이미 죽은 세션을 정리하는 중이라 실패해도 무시
                    logger.exception("기존 MCP 세션 정리 중 오류(무시하고 재기동 계속)")
            mcp_tools, _mcp_stack = await mcp_client.open_persistent_mcp_tools()
            _graph = build_supervisor(checkpointer=_checkpointer, mcp_tools=mcp_tools)
            _answer_chain = build_answer_chain()
            _graph_broken = False
    return _graph


def mark_graph_broken() -> None:
    """그래프 실행 중 예외가 새어나왔을 때 호출한다 — 다음 요청이 _get_graph()에서
    세션·그래프를 통째로 다시 만들게 한다(안전장치 2, SAFEGUARDS.md 참고)."""
    global _graph_broken
    _graph_broken = True


class QueryRequest(BaseModel):
    question: str
    thread_id: str | None = None
    # SERVICE.md 가드레일 규칙 5(요청자 권한 밖 다른 팀 정보 제공 금지). 비우면
    # 제한 없음(플랫폼팀 등 전체 조회 권한) — 개발팀 리드처럼 자기 팀만 봐야
    # 하는 호출자는 "team-a" 같은 값을 넣어야 한다. 이 필드 자체는 아직
    # 인증되지 않은 자기 신고 값이다: 진짜 신원 검증(로그인 세션 등)은
    # 이 3일짜리 스코프 밖이고, 여기서 강제하는 건 "그렇게 신고된 팀 밖의
    # 데이터는 절대 안 보여준다"는 것뿐이다.
    requester_team: str | None = None


class ApproveRequest(BaseModel):
    thread_id: str
    approved: bool
    requester_team: str | None = None


@app.post("/query")
async def query(request: QueryRequest) -> dict[str, Any]:
    thread_id = request.thread_id or str(uuid.uuid4())

    # 그래프를 만들기 전(=MCP 서버 기동, 임베딩 전) 값싼 차단 검사를 먼저 한다.
    # pipeline.ask()도 같은 검사를 하지만(run_eval.py 등 다른 호출자를 위해),
    # 여기서 먼저 걸러야 차단될 요청 때문에 첫 요청마다 그래프를 새로 만들지 않는다.
    blocked, reason = guardrails.input_guard(request.question)
    if blocked:
        answer = f"요청을 처리할 수 없습니다: {reason}"
        qa_history.record(thread_id, request.question, answer, request.requester_team, status="blocked")
        return {"answer": answer, "contexts": [], "trace": []}

    config = {"configurable": {"thread_id": thread_id}}

    graph = await _get_graph()
    try:
        response = await pipeline.ask(
            graph, request.question, config, answer_chain=_answer_chain, requester_team=request.requester_team
        )
    except Exception:
        # 안전장치 2(SAFEGUARDS.md) — MCP 자식 프로세스가 죽는 등 그래프 내부에서
        # 예외가 새어나온 경우다. 원인을 사용자에게 그대로 노출하지 않는다(스택
        # 정보·내부 경로가 섞여 나올 수 있음, guardrails.mask_pii와 같은 원칙) —
        # 서버 로그에만 전체 예외를 남기고, 다음 요청이 새 그래프로 다시 시작하게
        # 표시해둔다.
        logger.exception("그래프 실행 중 처리되지 않은 예외 — 다음 요청에서 재기동합니다")
        mark_graph_broken()
        answer = "일시적인 오류로 답변을 완성하지 못했습니다. 잠시 후 다시 시도해 주세요."
        qa_history.record(thread_id, request.question, answer, request.requester_team, status="error")
        return {"answer": answer, "contexts": [], "trace": []}

    if response.get("status") == "pending_approval":
        response["thread_id"] = thread_id
    return response


@app.get("/history")
async def history(thread_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    """질문-답변 히스토리를 최신순으로 돌려준다. thread_id를 주면 그 대화만 본다."""
    return {"items": qa_history.list_history(thread_id=thread_id, limit=limit)}


@app.get("/batch-runs")
async def batch_runs(limit: int = 50) -> dict[str, Any]:
    """이상탐지 배치 실행 이력을 최신순으로 돌려준다 (provider별 findings_count·notified 포함)."""
    return {"items": batch.list_batch_runs(limit=limit)}


@app.post("/query/approve")
async def approve(request: ApproveRequest) -> dict[str, Any]:
    config = {"configurable": {"thread_id": request.thread_id}}
    graph = await _get_graph()
    try:
        return await pipeline.resume(
            graph, request.approved, config, answer_chain=_answer_chain, requester_team=request.requester_team
        )
    except Exception:
        # /query와 같은 이유 — 안전장치 2(SAFEGUARDS.md).
        logger.exception("승인 재개 중 처리되지 않은 예외 — 다음 요청에서 재기동합니다")
        mark_graph_broken()
        answer = "일시적인 오류로 승인 처리를 완성하지 못했습니다. 잠시 후 다시 시도해 주세요."
        qa_history.record(
            request.thread_id, f"[승인 재개 시도: approved={request.approved}]", answer, request.requester_team, status="error"
        )
        return {"answer": answer, "contexts": [], "trace": []}
