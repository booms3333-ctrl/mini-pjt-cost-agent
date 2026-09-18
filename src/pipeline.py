"""질의 처리 파이프라인 — app.py와 evaluation/run_eval.py가 함께 쓴다.

미들웨어 순서(guardrails.MIDDLEWARE_ORDER)를 여기서 적용한다:
InputGuard(차단) -> 그래프 실행(OutputCheck은 agent.py의 judge_output에서 서브
에이전트 단위로 이미 적용됨) -> 구조화(answer_chain, 패턴 1) -> Masking.
로직을 app.py에서 분리한 이유는 evaluation/run_eval.py가 HTTP 서버를 띄우지
않고도 같은 경로로 에이전트를 호출해야 하기 때문이다 (20문항 평가를 매번 서버
기동 없이 돌리려는 목적).

트레이스(패턴 11)는 observability.start_collector()로 요청마다 새로 시작해서
data/traces/<thread_id>.jsonl 로 덤프한다 — agent.py의 각 노드가 같은 콜렉터를
observability.get_collector()로 찾아 llm_start/llm_end/tool_* 이벤트를 쌓는다.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage
from langgraph.types import Command

import authz
import guardrails
import observability
import qa_history
from llm_utils import get_text

_SOURCE_SUFFIX = re.compile(r"\n\(출처: (.*?)\)$")

# 안전장치 1 — 그래프 실행 전체에 상한을 둔다 (SAFEGUARDS.md 참고). Bedrock/MCP
# 어딘가가 에러 없이 그냥 멈춰버리면(서킷 브레이커는 "빠르게 반복 실패하는 것"만
# 잡고 이런 행-hang은 못 잡는다) 이 상한이 없으면 요청이 영원히 붙잡힌다. UI
# 클라이언트 타임아웃(120초)보다 짧게 잡아서, 서버가 먼저 명확한 에러로 끝낸다.
REQUEST_TIMEOUT_SECONDS = 90

# 안전장치 3 — 승인 대기(pending_approval) 상태가 이만큼(초) 지나면 재개를 거절한다
# (SAFEGUARDS.md 참고). 오래 방치된 승인은 그 사이 상황이 바뀌었을 수 있어(리소스
# 상태·비용 데이터 등) 안전을 위해 그냥 밀어붙이지 않는다.
APPROVAL_TTL_SECONDS = 3600


def _messages_since_last_human(messages: list) -> list:
    """체크포인터가 스레드 전체 메시지를 계속 이어 붙이므로, 이번 턴에 새로 생긴
    메시지만 골라내려면 가장 최근 HumanMessage 이후를 잘라내야 한다. 이걸 안 하면
    두 번째 턴부터 finalize()가 이전 턴 답변까지 전부 다시 이어붙여 응답에 담아
    버린다 (같은 thread_id로 여러 턴을 주고받는 실사용 시나리오에서 직접 재현해
    발견 — agent.py의 routed_human_count 버그와 짝을 이루는 문제였다).
    """
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            return messages[i + 1 :]
    return messages

# HistorySummaryMiddleware (패턴 8, guardrails.MIDDLEWARE_ORDER 참고). AsyncSqliteSaver가
# 같은 thread_id의 messages를 매 질의마다 계속 이어 붙이므로(add_messages 리듀서),
# 대화가 길어지면 체크포인트에 쌓이는 메시지 수가 무한정 늘어난다. 지금 이 프로젝트의
# 서브 에이전트는 매번 "가장 최근 질문"만 다시 프롬프트에 넣으므로(agent.py의
# _last_human_text) 턴마다 LLM 토큰 비용이 늘어나는 문제는 없지만, (1) 체크포인트
# 저장 공간은 계속 늘어나고 (2) 향후 서브 에이전트가 과거 맥락을 참고하도록 확장할
# 때를 대비해 미리 요약을 준비해 둔다.
HISTORY_SUMMARY_THRESHOLD = 20  # 이 개수를 넘으면 오래된 메시지를 요약으로 교체한다
HISTORY_KEEP_RECENT = 6  # 최근 이만큼은 원문 그대로 남긴다


async def _maybe_summarize_history(graph, config: dict) -> None:
    """대화가 길어지면 오래된 메시지를 요약 하나로 교체한다.

    체크포인터가 없거나(runtime에서 그래프를 checkpointer 없이 조립한 경우) 상태
    조회/갱신이 실패해도 요약은 보강 기능이지 필수 경로가 아니므로 조용히 넘어간다
    (answer_chain 실패 시 원시 답변으로 폴백하는 것과 같은 원칙).
    """
    try:
        state = await graph.aget_state(config)
    except Exception:  # noqa: BLE001
        return
    messages = list(state.values.get("messages", [])) if state.values else []
    if len(messages) <= HISTORY_SUMMARY_THRESHOLD:
        return

    to_summarize = messages[:-HISTORY_KEEP_RECENT]
    if not to_summarize:
        return

    transcript = "\n".join(
        f"{'사용자' if isinstance(m, HumanMessage) else '에이전트'}: {get_text(m)}"
        for m in to_summarize
        if isinstance(m, (HumanMessage, AIMessage)) and get_text(m)
    )
    if not transcript.strip():
        return

    try:
        from llm_utils import build_llm_with_failover

        llm = build_llm_with_failover()
        prompt = (
            "다음은 사용자와 클라우드 비용 에이전트의 이전 대화다. 이후 대화에서 참고할 "
            "수 있도록 핵심 사실(조회한 리소스 ID, 언급된 수치, 실행/승인 여부 등)만 "
            "5문장 이내로 요약하라.\n\n" + transcript
        )
        summary_response = await llm.ainvoke([HumanMessage(content=prompt)])
        summary_text = get_text(summary_response)

        removals = [RemoveMessage(id=m.id) for m in to_summarize if getattr(m, "id", None)]
        replacement = SystemMessage(content=f"[이전 대화 요약] {summary_text}")
        await graph.aupdate_state(config, {"messages": [*removals, replacement]})
    except Exception:  # noqa: BLE001
        return


async def finalize(result: dict[str, Any], question: str, answer_chain=None) -> dict[str, Any]:
    """그래프 실행 결과를 {answer, contexts, trace} 또는 pending_approval로 조립한다.

    answer_chain이 주어지면(패턴 1: LCEL + Pydantic 구조화 출력) 서브 에이전트가
    만든 원시 텍스트를 한 번 더 거쳐 {summary, key_numbers, confidence,
    needs_followup} 로 정규화하고, 그 결과 전체를 "structured" 키에 담는다.
    answer_chain 호출이 실패해도(예: LLM 오류) 원시 답변으로 폴백한다 — 구조화는
    보강이지 필수 경로가 아니다.
    """
    interrupts = result.get("__interrupt__")
    if interrupts:
        # request.args는 LLM이 그대로 채운 도구 인자(예: send_cost_alert의 message,
        # resize_resource의 target_type)라 PII/자격증명이 섞여 나올 수 있다 — 이
        # 경로가 mask_pii()를 아예 안 거치고 있던 걸 코드 리뷰에서 발견해 고쳤다.
        return {"status": "pending_approval", "request": guardrails.mask_pii_deep(interrupts[0].value)}

    ai_messages = [m for m in _messages_since_last_human(result.get("messages", [])) if isinstance(m, AIMessage)]
    raw_answer = "\n\n".join(m.content for m in ai_messages) or "답변을 생성하지 못했습니다."

    answer_text = raw_answer
    structured: dict[str, Any] = {}
    if answer_chain is not None:
        try:
            with observability.Timer("llm", "answer_chain"):
                structured = await answer_chain.ainvoke({"question": question, "raw_answer": raw_answer})
            answer_text = structured.get("summary") or raw_answer
        except Exception:  # noqa: BLE001 — 구조화 실패는 원시 답변으로 폴백
            structured = {}

    answer_text = guardrails.mask_pii(answer_text)

    # trace는 operator.add로 스레드 전체 동안 계속 쌓이기만 하므로(턴 경계가 따로
    # 없음), agent.py가 매 턴 시작 시 기록해 두는 trace_baseline 이후만 이번 턴
    # 것으로 본다 — 안 그러면 두 번째 턴부터 이전 턴들의 trace/contexts까지 매번
    # 다시 응답에 실리게 된다 (위 messages와 같은 종류의 문제).
    turn_trace = result.get("trace", [])[result.get("trace_baseline", 0) :]

    # contexts/trace는 도구 원본 출력을 그대로 담는데, sanitize_tool_output()은
    # 인젝션 마커만 지우지 PII는 안 지운다 — answer만 마스킹되고 같은 응답의
    # contexts/trace엔 자격증명이 그대로 남을 수 있던 문제라 여기도 mask_pii를 거친다.
    contexts = []
    for rec in turn_trace:
        if rec.get("tool") != "retrieve_docs":
            continue
        output = str(rec.get("output", ""))
        match = _SOURCE_SUFFIX.search(output)
        sources = match.group(1).split(", ") if match else ["알 수 없음"]
        text = guardrails.mask_pii(_SOURCE_SUFFIX.sub("", output))
        for source in sources:
            contexts.append({"doc_id": source, "text": text})

    trace = [
        {
            "step": rec.get("tool") or rec.get("step"),
            "input": question,
            "output": guardrails.mask_pii(str(rec.get("output") or "")),
        }
        for rec in turn_trace
    ]

    response = {"answer": answer_text, "contexts": contexts, "trace": trace}
    if structured:
        response["structured"] = structured
    # 이번 턴에 실제로 응답받은 모델 — MODEL_FAILOVER.md 참고. agent.py가
    # SupervisorState.active_model에 담아 그래프 상태로 들고 나온 값이다(라우팅된
    # 서브 에이전트가 없었던 질문 등에서는 값이 없을 수 있다).
    active_model = result.get("active_model")
    if active_model:
        response["active_model"] = active_model
    return response


def _thread_id_of(config: dict) -> str:
    return config.get("configurable", {}).get("thread_id", "unknown")


def _record_history(thread_id: str, question: str, response: dict, requester_team: str | None) -> None:
    """response 모양에 따라 상태를 나눠 data/history.db에 남긴다."""
    if response.get("status") == "pending_approval":
        qa_history.record(
            thread_id, question, f"[승인 대기] {response['request']}", requester_team, status="pending_approval"
        )
    else:
        qa_history.record(thread_id, question, response.get("answer", ""), requester_team, status="answered")


async def ask(graph, question: str, config: dict, answer_chain=None, requester_team: str | None = None) -> dict[str, Any]:
    """가드레일 차단 -> 그래프 실행 -> 구조화 -> 마스킹까지 한 번에 처리한다.

    HITL이 필요하면 그래프가 interrupt()로 멈추고, finalize가 이를
    {"status": "pending_approval", "request": {...}}로 표면화한다.

    requester_team을 넘기면(SERVICE.md 가드레일 규칙 5) tools.py의 조회·실행
    함수가 그 팀 데이터로만 결과를 좁힌다 — authz.set_requester_team()이
    contextvars에 심어두고, 같은 이벤트 루프 태스크 안에서 실행되는 도구
    함수들이 그 값을 읽는다. None이면 제한 없음(플랫폼팀 등 전체 조회 권한).
    """
    thread_id = _thread_id_of(config)

    blocked, reason = guardrails.input_guard(question)
    if blocked:
        response = {"answer": f"요청을 처리할 수 없습니다: {reason}", "contexts": [], "trace": []}
        qa_history.record(thread_id, question, response["answer"], requester_team, status="blocked")
        return response

    authz.set_requester_team(requester_team)
    observability.start_collector()
    try:
        result = await asyncio.wait_for(
            graph.ainvoke({"messages": [HumanMessage(content=question)]}, config),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        # 안전장치 1 — SAFEGUARDS.md 참고. 그래프 상태가 어중간하게 남을 수 있으니
        # 이 스레드에 대한 이후 요청은 새 대화로 시작하길 권한다(여기서 강제로
        # 정리하진 않는다 — interrupt() 재개 로직과 꼬일 위험이 더 크다).
        response = {
            "answer": (
                f"요청 처리 시간이 {REQUEST_TIMEOUT_SECONDS}초를 넘어 응답을 완성하지 못했습니다. "
                "질문을 더 구체적으로 나눠서 다시 시도해 주세요."
            ),
            "contexts": [],
            "trace": [],
        }
        observability.dump_current(thread_id)
        qa_history.record(thread_id, question, response["answer"], requester_team, status="error")
        return response
    response = await finalize(result, question, answer_chain)
    # finalize()가 answer_chain(LLM 호출)을 여기서 돌리므로, 그 이벤트까지 담으려면
    # dump는 finalize 이후에 해야 한다 (먼저 dump하면 answer_chain 타이밍이 빠진다).
    observability.dump_current(thread_id)
    _record_history(thread_id, question, response, requester_team)
    if response.get("status") != "pending_approval":
        # interrupt()로 멈춘 상태 도중에 state를 건드리면 재개 로직과 꼬일 수 있어
        # 승인 대기 중에는 건드리지 않는다.
        await _maybe_summarize_history(graph, config)
    return response


async def resume(
    graph, approved: bool, config: dict, answer_chain=None, requester_team: str | None = None
) -> dict[str, Any]:
    """interrupt()로 멈춘 실행을 사용자 승인 여부로 재개한다.

    requester_team은 승인 재개 시에도 다시 넘겨야 한다 — HITL 승인 중 실제로
    실행되는 stop_resource/resize_resource도 팀 소유권 검사를 받는데, 이
    contextvar는 프로세스 전역이 아니라 요청(태스크)마다 새로 설정해야 하는
    값이라 /query 때 넘긴 값이 /query/approve 호출까지 자동으로 이어지지 않는다.
    """
    thread_id = _thread_id_of(config)

    # 안전장치 3 — 이 스레드의 마지막 기록이 승인 대기였고, 그로부터 APPROVAL_TTL_SECONDS를
    # 넘겼으면 재개 자체를 거절한다(SAFEGUARDS.md 참고). 그래프 상태는 건드리지
    # 않는다 — interrupt()가 걸린 채로 그냥 둔다(강제로 정리하면 재개 로직과 꼬일
    # 위험이 더 크다). 기록이 없거나 이미 답변된 스레드면(예: 승인 없이 온 요청)
    # 이 검사를 건너뛰고 아래에서 정상적으로 처리하다가 "재개할 게 없음"으로 끝난다.
    recent = qa_history.list_history(thread_id=thread_id, limit=1)
    if recent and recent[0]["status"] == "pending_approval":
        created_at = datetime.fromisoformat(recent[0]["created_at"])
        age_seconds = (datetime.now(timezone.utc) - created_at).total_seconds()
        if age_seconds > APPROVAL_TTL_SECONDS:
            answer = (
                f"이 승인 요청은 {int(age_seconds // 60)}분 전에 만들어져 만료됐습니다 — "
                "그 사이 상황이 바뀌었을 수 있어 안전을 위해 처리하지 않습니다. 새 질문으로 다시 요청해 주세요."
            )
            qa_history.record(thread_id, f"[승인 재개 시도: approved={approved}]", answer, requester_team, status="error")
            return {"answer": answer, "contexts": [], "trace": [], "status": "expired"}

    authz.set_requester_team(requester_team)
    observability.start_collector()
    try:
        result = await asyncio.wait_for(
            graph.ainvoke(Command(resume={"approved": approved}), config),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        response = {
            "answer": (
                f"요청 처리 시간이 {REQUEST_TIMEOUT_SECONDS}초를 넘어 응답을 완성하지 못했습니다. "
                "질문을 더 구체적으로 나눠서 다시 시도해 주세요."
            ),
            "contexts": [],
            "trace": [],
        }
        observability.dump_current(thread_id)
        qa_history.record(thread_id, f"[승인 재개: approved={approved}]", response["answer"], requester_team, status="error")
        return response
    response = await finalize(result, "", answer_chain)
    observability.dump_current(thread_id)
    _record_history(thread_id, f"[승인 재개: approved={approved}]", response, requester_team)
    if response.get("status") != "pending_approval":
        await _maybe_summarize_history(graph, config)
    return response
