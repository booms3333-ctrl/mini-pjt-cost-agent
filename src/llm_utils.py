"""LangChain 메시지에서 텍스트만 뽑아내는 공통 유틸.

ChatBedrockConverse 응답이나 MCP 도구 결과의 content가 문자열이 아니라
[{"type": "text", "text": "..."}] 같은 블록 리스트로 올 때가 있다. 이 변환
로직이 agent.py/retriever.py/evaluation/run_eval.py 세 곳에 거의 똑같이
따로 있었다 — 코드 리뷰에서 지적받아 하나로 합쳤다.
"""

from __future__ import annotations

import time
from typing import Any

from langchain_core.runnables import RunnableLambda

# 페일오버 우선순위 — MODEL_FAILOVER.md가 이 목록의 원본 문서다. 순위를 바꾸거나
# 모델을 추가/제거하면 그 문서도 같이 갱신한다. 1순위가 재시도(with_bedrock_retry,
# 3회)까지 다 실패해야 2순위로 넘어간다 — 평소(1순위 정상)엔 추가 호출이 없다.
#
# 속도 우선으로 재배치했다(2026-09-18) — 처음엔 "가장 강력한 모델부터" 순서로
# Claude Sonnet 4.5를 1순위로 뒀는데, round1 평가로 실제로 돌려보니 문항당
# 5~15초(Nova 2 Lite 단독 시절)에서 70~200초 이상으로 튀었다. 이 프로젝트는 질문
# 하나에 순차 LLM 호출이 3~6번 걸려서, 무거운 모델을 1순위에 두면 그 지연이 그대로
# 곱해진다 — "가장 좋은 모델"과 "1순위(=거의 항상 실제로 쓰이는 모델)"는 다른
# 기준이어야 한다는 뜻. 그래서 이 프로젝트에서 이미 속도·프롬프트 호환성 둘 다
# 검증된 Nova 2 Lite를 1순위로 올리고, Claude 계열은 "Nova가 전부 막혔을 때만
# 쓰는" 뒷순위 페일오버로 내렸다.
MODEL_PRIORITY: list[str] = [
    "global.amazon.nova-2-lite-v1:0",
    "us.amazon.nova-2-lite-v1:0",
    "us.amazon.nova-lite-v1:0",
    "us.amazon.nova-pro-v1:0",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    "us.anthropic.claude-sonnet-4-6",
    "global.anthropic.claude-sonnet-4-6",
    "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
]


def extract_active_model(response: Any) -> str | None:
    """LLM 응답의 response_metadata에서 실제로 응답한 모델 ID를 뽑는다.

    ChatBedrockConverse가 채워주는 response_metadata["model_name"]은 그 응답을
    만든 인스턴스에 설정된 모델 ID 그대로다(직접 호출해 실측 확인) — 별도 계측 없이
    "이번엔 어느 모델이 답했는지"를 정확히 알 수 있다.

    처음엔 이 값을 contextvar(authz.py의 requester_team과 같은 패턴)에 기록해서
    agent.py 노드 안에서 "설정"하고 pipeline.finalize()에서 "조회"하는 식으로
    만들었다가, 실제로 돌려보니 항상 비어 있었다 — LangGraph가 노드를 asyncio
    태스크로 실행해서, 그 안에서 contextvar.set()해도 호출부(부모 컨텍스트)에는
    안 보였다(직접 겪음). 그래서 이 함수는 부수효과 없이 값만 뽑아 돌려주고,
    호출부(agent.py)가 그 값을 그래프 상태(SupervisorState.active_model)에 담아
    LangGraph의 정식 상태 병합 경로로 들고 나온다 — trace를 들고 나오는 것과 같은
    방식이다.
    """
    metadata = getattr(response, "response_metadata", None)
    if isinstance(metadata, dict):
        return metadata.get("model_name")
    return None


# ══════════════════════════════════════════════════════════════════
# 서킷 브레이커 — 방금 실패한 모델을 잠깐 쉬게 한다 (부수효과는 이것 하나뿐)
# ══════════════════════════════════════════════════════════════════
#
# .with_fallbacks()만 쓰던 처음 버전은 "기억이 없다" — 1순위가 지금 계속
# 스로틀링에 걸리는 중이어도 호출마다 매번 1순위부터 재시도하고 나서야 다음
# 순위로 넘어갔다. 1순위를 계속 두드리는 것 자체가 스로틀링을 더 악화시키는
# 악순환이라, 실측(Sonnet을 1순위로 뒀을 때 문항당 지연이 70→143→163→215초로
# 계속 나빠짐)으로 확인됐다. 그래서 "방금 실패한 모델은 일정 시간 동안 아예
# 건드리지 않고 건너뛴다"는 최소한의 상태를 둔다 — 이 모듈 전체에서 딱 하나
# 있는 진짜 부수효과(mutable global)이고, 나머지 함수는 전부 순수 함수다.
_CIRCUIT_COOLDOWN_SECONDS = 30.0
_circuit_trip_until: dict[str, float] = {}


def is_circuit_open(model_id: str) -> bool:
    """model_id가 지금 쿨다운 중인지만 조회한다 — 상태를 바꾸지 않는 순수 조회."""
    trip_until = _circuit_trip_until.get(model_id)
    return trip_until is not None and time.monotonic() < trip_until


def trip_circuit(model_id: str, cooldown_seconds: float | None = None) -> None:
    """실패를 기록해 model_id를 cooldown_seconds 동안 후보에서 뺀다.

    기본값을 파이썬 함수 정의 시점에 고정된 파라미터 값(= _CIRCUIT_COOLDOWN_SECONDS)
    으로 두지 않고 None으로 받아 매번 모듈 전역값을 다시 읽는다 — 함수 시그니처의
    기본 인자는 def 실행 시점에 딱 한 번 평가되므로, 상수를 나중에 바꿔도(테스트 등)
    이미 정의된 함수의 기본값에는 반영이 안 되는 파이썬의 흔한 함정이다.
    """
    if cooldown_seconds is None:
        cooldown_seconds = _CIRCUIT_COOLDOWN_SECONDS
    _circuit_trip_until[model_id] = time.monotonic() + cooldown_seconds


def reset_circuit(model_id: str) -> None:
    """성공하면 쿨다운을 즉시 해제한다 — 시간이 다 지나기를 기다리지 않고 바로 복귀."""
    _circuit_trip_until.pop(model_id, None)


def build_fallback_candidates(tool_fns: list | None, model_ids: list[str], region: str = "us-east-1", temperature: float = 0):
    """model_ids 각각에 대해 (model_id, 재시도 1회까지 씌운 runnable) 쌍을 만든다.

    "이미 있는 llm을 1순위로 그대로 쓰고, 나머지 모델만 후보로 달라"는 쪽(agent.py의
    서브 에이전트 ReAct/실행 결정 노드)에서 쓴다 — 테스트가 주입한 FakeLLM을 1순위
    자리에서 안 건드리기 위해, "1순위 + 나머지 후보"를 이 함수와 호출부에서 나눠
    조립한다(MODEL_FAILOVER.md "테스트 격리" 참고). 재시도는 1회로 줄인다 — 이유는
    with_bedrock_retry 문서 참고.
    """
    from langchain_aws import ChatBedrockConverse

    candidates = []
    for model_id in model_ids:
        candidate = ChatBedrockConverse(model=model_id, region_name=region, temperature=temperature)
        if tool_fns is not None:
            candidate = candidate.bind_tools(tool_fns)
        candidates.append((model_id, with_bedrock_retry(candidate, stop_after_attempt=1)))
    return candidates


def with_circuit_breaker_failover(candidates: list[tuple[str, Any]]):
    """(model_id, runnable) 순서대로 시도하는 페일오버를 만든다 — 쿨다운 중인
    모델은 시도 자체를 건너뛴다(재시도까지 다 치르고서야 넘어가던 .with_fallbacks()
    보다 빠르다). 성공하면 그 모델의 쿨다운을 즉시 해제하고, 실패하면 트립한다.
    전부 쿨다운 중이면(극단적인 경우) 그래도 순서대로 한 번씩은 시도한다 —
    서킷 브레이커 때문에 완전히 응답 불가능해지는 것보다는 낫다.

    반환값은 LangChain Runnable(RunnableLambda)이라 다른 Runnable과 그대로
    합성(`|`)되고, agent.py처럼 `.ainvoke(messages)`로 직접 부르는 곳에도 그대로
    쓸 수 있다.

    func(동기)와 afunc(비동기)를 둘 다 준다 — RunnableLambda에 afunc만 주면
    동기 `.invoke()`가 "코루틴을 동기로 못 부른다"는 TypeError로 그냥 깨진다.
    실제로 retriever.py의 RAG 체인(`retrieve_docs` 도구, 동기 함수라 LangGraph의
    ToolNode가 스레드 풀에서 동기로 돌린다)이 build_llm_with_failover()의 결과를
    `llm.invoke(messages)`로 동기 호출하다가 이 문제로 깨지는 걸 실제 E2E 테스트로
    발견했다 — 그래서 두 경로를 완전히 대칭으로 유지한다.
    """

    def _try_candidates_sync(input_, config, kwargs):
        all_open = all(is_circuit_open(mid) for mid, _ in candidates)
        last_exc: Exception | None = None
        for model_id, runnable in candidates:
            if not all_open and is_circuit_open(model_id):
                continue
            try:
                result = runnable.invoke(input_, config=config, **kwargs)
            except Exception as exc:  # noqa: BLE001 — 다음 후보로 넘어가기 위한 의도적 포괄 처리
                trip_circuit(model_id)
                last_exc = exc
                continue
            reset_circuit(model_id)
            return result
        assert last_exc is not None  # candidates가 비어있지 않으면 항상 하나는 시도된다
        raise last_exc

    async def _try_candidates_async(input_, config, kwargs):
        all_open = all(is_circuit_open(mid) for mid, _ in candidates)
        last_exc: Exception | None = None
        for model_id, runnable in candidates:
            if not all_open and is_circuit_open(model_id):
                continue
            try:
                result = await runnable.ainvoke(input_, config=config, **kwargs)
            except Exception as exc:  # noqa: BLE001 — 다음 후보로 넘어가기 위한 의도적 포괄 처리
                trip_circuit(model_id)
                last_exc = exc
                continue
            reset_circuit(model_id)
            return result
        assert last_exc is not None  # candidates가 비어있지 않으면 항상 하나는 시도된다
        raise last_exc

    def _invoke(input_, config=None, **kwargs):
        return _try_candidates_sync(input_, config, kwargs)

    async def _ainvoke(input_, config=None, **kwargs):
        return await _try_candidates_async(input_, config, kwargs)

    return RunnableLambda(func=_invoke, afunc=_ainvoke)


def build_llm_with_failover(tool_fns: list | None = None, region: str = "us-east-1", temperature: float = 0):
    """MODEL_PRIORITY 전체로 "1순위부터 시작하는" 완전한 페일오버 체인을 만든다.

    도구 바인딩이 필요 없는 호출(구조화, RAG 리랭킹/쿼리확장, 대화 이력 요약, 평가용
    judge/RAGAS)에 쓴다 — 이런 곳은 테스트가 별도 llm을 주입하지 않으므로 9개
    전체를 그냥 다 후보로 만들어도 된다.
    """
    candidates = build_fallback_candidates(tool_fns, MODEL_PRIORITY, region=region, temperature=temperature)
    return with_circuit_breaker_failover(candidates)


def get_text(message: Any) -> str:
    """메시지 content가 블록 리스트여도(MCP 도구 결과 등) 텍스트만 이어붙여 돌려준다."""
    content = message.content if hasattr(message, "content") else message
    if isinstance(content, list):
        return "".join(block.get("text", "") for block in content if isinstance(block, dict))
    return str(content)


def with_bedrock_retry(llm, stop_after_attempt: int = 3):
    """Bedrock LLM 호출에 재시도(패턴 8 — 미들웨어)를 씌운다.

    AWS Bedrock 계정 일일 토큰 쿼터에 걸리면 ThrottlingException이 나는 걸 이
    프로젝트에서 실제로 겪었다(evaluation/run_eval.py round1 첫 실행, README
    트라이앤에러 회고 참고) — 그땐 쿼터가 회복될 때까지 기다렸다가 사람이 다시
    실행했는데, 매번 사람이 재시도할 게 아니라 코드가 지수 백오프로 몇 번 자동
    재시도하게 만든다. LangChain의 모든 Runnable(ChatBedrockConverse 포함)이
    제공하는 `.with_retry()`를 쓴다 — 기본 `retry_if_exception_type=(Exception,)`이
    이미 ThrottlingException(botocore.exceptions.ClientError로 래핑되어 옴)을
    포함하므로 별도 예외 타입 지정이 필요 없다.

    stop_after_attempt 기본값은 3이지만, 페일오버 체인 안(build_fallback_candidates)
    에서는 1로 줄여서 부른다 — 모델이 8개 더 있는데 같은 모델을 3번씩 두드리며
    시간을 쓰는 대신 한 번만 시도하고 빨리 다음 순위로 넘어가는 쪽이 낫다(실측:
    Sonnet을 1순위로 뒀을 때 문항당 지연이 재시도 누적으로 계속 악화됐다).
    """
    return llm.with_retry(stop_after_attempt=stop_after_attempt, wait_exponential_jitter=True)
