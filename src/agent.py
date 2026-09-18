"""메인 에이전트 그래프 — Multi-Agent Supervisor.

뼈대는 Day 6(day06/practice/starter/submission.py)의 Supervisor 라우팅을 그대로
따른다: route_question은 LLM을 호출하지 않는 결정적 규칙이고, supervisor 노드가
pending 목록을 하나씩 소진하며 서브 에이전트에 위임한다.

다만 Day 6 원본은 서브 에이전트가 도구를 실제로 호출하지 않고 "담당 도구: X"라는
설명만 프롬프트에 넣어 LLM이 텍스트로 답하게 했다. 이 프로젝트는 SQLite 조회·
이상탐지·실행이 실제로 필요하므로, 조회형 서브 에이전트(cost_lookup / anomaly /
optimization)는 Day 3(day03/practice/starter/submission.py)의 ReAct 루프
(bind_tools + ToolNode + 순환)를 각자 도구 범위로 내장한 작은 서브그래프로 만들었다.

execution_agent는 다르다: 쓰기·실행 도구(stop_resource 등)는 실행 전에 반드시
guardrails.needs_approval()로 승인 필요 여부를 확인하고, 필요하면 langgraph
interrupt()로 그래프를 멈춘다 (HITL). 이 승인 게이트가 LLM 호출 없이 재실행 가능한
노드여야 재개(resume) 시 LLM을 중복 호출하지 않으므로, "무엇을 호출할지 결정"
(LLM 호출)과 "승인 확인 후 실행"(LLM 미호출) 두 단계로 나눴다.
"""

from __future__ import annotations

import operator
import re
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

import authz
import guardrails
import observability
import llm_utils
from llm_utils import get_text, with_bedrock_retry
import tools as domain_tools

# MODEL_ID는 이제 llm_utils.MODEL_PRIORITY[0](1순위 모델)의 별칭일 뿐이다 — 실제
# 우선순위·페일오버 목록은 MODEL_FAILOVER.md와 llm_utils.MODEL_PRIORITY가 원본이다.
MODEL_ID = llm_utils.MODEL_PRIORITY[0]
REGION = "us-east-1"

# 서브 에이전트당 도구 호출 예산. Day 3 MAX_TOOL_CALLS(=5)와 같은 근거로,
# 조사 한 바퀴를 마치고도 재확인할 여유를 한 번 남기되 우리 도메인은 서브
# 에이전트당 도구가 1~3개뿐이라 조금 더 낮춰 잡았다.
MAX_TOOL_CALLS_PER_AGENT = 4

# optimization_agent만 예산을 늘린다: "분기 절감 계획 세워줘" 같은 복합 질문은
# 유휴 리소스 조회 -> estimate_savings(후보마다 반복 호출 가능) -> retrieve_docs까지
# 필요해서 기본 예산(4)으로는 계획을 끝까지 못 세우고 중간에 끊기는 경우가 있었다
# (LLM-as-Judge 채점에서 처음 발견 — #8: "20% 절감 계획"에 단계별 계획 대신
# "도구 호출 횟수 소진"이라고만 답함). 다른 에이전트는 도구가 1~2개뿐이라 4회로 충분.
AGENT_MAX_TOOL_CALLS: dict[str, int] = {
    "optimization_agent": 7,
}


def _max_tool_calls_for(name: str) -> int:
    return AGENT_MAX_TOOL_CALLS.get(name, MAX_TOOL_CALLS_PER_AGENT)


def _default_llm():
    """1순위 모델(MODEL_ID) 하나만 돌려주는 "맨 llm" — 페일오버가 없다.

    이 파일 안에서는 .bind_tools() 뒤에 재시도를 씌운다(with_bedrock_retry 사용처
    참고) — RunnableRetry(.with_retry()의 반환 타입)는 .bind_tools()를 못 가진다.
    여기서 미리 감싸버리면 그래프 조립 시 llm.bind_tools(...) 호출이 그대로 깨진다
    (직접 겪었다: AttributeError 대신 그냥 bind_tools 자체가 없어서 조용히 실패).

    build_supervisor(llm=None)이 기본 경로에서 이 함수를 쓰는 이유는 딱 하나 —
    build_supervisor가 이 반환값에 나머지 8개 페일오버 후보를 별도로 붙여준다
    (MODEL_FAILOVER.md 참고). llm이 테스트에서 명시적으로 주입되면(FakeLLM 등) 이
    함수는 아예 호출되지 않는다. 9개 전체 페일오버가 그냥 다 필요하면(도구 바인딩이
    없는 호출) 이 함수 대신 llm_utils.build_llm_with_failover()를 바로 써라.
    """
    from langchain_aws import ChatBedrockConverse

    return ChatBedrockConverse(model=MODEL_ID, region_name=REGION, temperature=0)


# ══════════════════════════════════════════════════════════════════
# 라우팅 — Day 6 route_question과 동일한 규칙 기반 배분
# ══════════════════════════════════════════════════════════════════

AGENT_NAMES: list[str] = [
    "cost_lookup_agent",
    "anomaly_agent",
    "optimization_agent",
    "execution_agent",
]

# 도메인별로 도구를 격리한다. get_cost_by_service만 로컬(멀티클라우드 합산 집계 —
# 어느 한 계정 API도 다른 계정 비용은 모르므로 이 합산은 오케스트레이션 계층의 몫)로
# 두고, 나머지 계정별 조회(aws_get_cost 등)는 mcp_servers/cost_server.py 세 대가
# 노출하는 MCP 도구를 붙인다 (build_supervisor의 mcp_tools 인자로 주입).
# retrieve_docs는 optimization_agent 전용으로 둔다 — 정책 근거가 필요한 질문은
# 대부분 예산·배분·절감 조건 확인이라 이 에이전트 범위와 겹친다. get_budget_status도
# 여기 둔다 — "예산"/"한도"는 _OPTIMIZATION_KEYWORDS에 있어서 실제 예산 사용 현황
# 질문("우리 팀 예산 얼마나 썼어?")도 cost_lookup_agent가 아니라 optimization_agent로
# 라우팅되기 때문이다(cost_lookup_agent에 두면 도구는 있는데 그 질문 자체가
# 그 에이전트한테 배정이 안 되는 사고가 난다).
# aws/gcp/azure_check_incidents는 anomaly_agent 전용 — 이상 급증이 클라우드 자체
# 장애 때문인지 실제 공개 상태 피드로 확인한다(src/incident_feeds.py, 합성
# 데이터가 아니라 실 데이터를 쓰는 유일한 도구).
AGENT_TOOLS: dict[str, list[str]] = {
    "cost_lookup_agent": [
        "get_cost_by_service",
        "aws_get_cost", "gcp_get_cost", "azure_get_cost",
        "aws_get_utilization", "gcp_get_utilization", "azure_get_utilization",
    ],
    "anomaly_agent": [
        "detect_cost_anomaly",
        "aws_check_incidents", "gcp_check_incidents", "azure_check_incidents",
    ],
    "optimization_agent": [
        "estimate_savings", "retrieve_docs", "get_budget_status",
        "aws_list_idle", "gcp_list_idle", "azure_list_idle",
    ],
    "execution_agent": ["stop_resource", "resize_resource", "send_cost_alert"],
}

_COST_KEYWORDS = (
    "비용", "얼마", "총액", "청구", "요금", "cost", "spend", "billing", "사용률", "가동",
    "비싸", "비싼",  # "왜 이렇게 비싸?" 처럼 '비용'이란 단어 없이 묻는 경우도 걸리게
)
_ANOMALY_KEYWORDS = ("이상", "급증", "급등", "튀었", "이상한", "anomaly", "spike")
_OPTIMIZATION_KEYWORDS = (
    "절감", "유휴", "idle", "savings", "reserved", "예약", "다운사이징", "downsizing",
    "최적화", "정책", "한도", "배분", "예산", "조건",
)
_PLAN_KEYWORDS = ("계획", "plan")
# 부분 문자열(in) 매칭 대신 정규식을 쓴다: "정지해"/"변경해"/"축소해" 같은 어간이
# "정지해야 하나요?"(문의) · "변경해도 될까요?"(문의) · "축소해도"(문의)처럼 명령이
# 아닌 문장에도 그냥 부분 문자열로는 걸려서 execution_agent로 잘못 라우팅됐다
# (코드 리뷰에서 발견). "~해/시켜 + 줘/주세요/줄래" 같은 실제 명령형 어미가 뒤에
# 붙을 때만 실행 요청으로 본다. "꺼"도 "꺼림칙한"/"꺼내서"에 걸리지 않도록 뒤에
# 줘/주세요/줄래가 와야만 매칭한다.
_EXECUTION_PATTERNS = (
    re.compile(r"꺼\s*(줘|주세요|줄래)"),
    re.compile(r"(정지|중단|종료|축소|변경)(해|시켜)\s*(줘|주세요|줄래)"),
    re.compile(r"발송해"),
    re.compile(r"보내\s*(줘|주세요|줄래)"),
    re.compile(r"\bstop\b", re.IGNORECASE),
    re.compile(r"\bresize\b", re.IGNORECASE),
    re.compile(r"\balert\b", re.IGNORECASE),
)

_AGENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "cost_lookup_agent": _COST_KEYWORDS,
    "anomaly_agent": _ANOMALY_KEYWORDS,
    "optimization_agent": _OPTIMIZATION_KEYWORDS,
}


def route_question(question: str) -> list[str]:
    """질문을 처리할 서브 에이전트 목록을 반환한다. LLM을 호출하지 않는다.

    규칙:
      - 실행 동사(꺼줘/정지/축소/알림 발송 등) -> execution_agent 단독
        (조회 요청과 섞으면 승인 흐름이 애매해지므로 실행 키워드가 있으면 그것만 본다)
      - "계획"류 복합 질의 -> anomaly_agent + optimization_agent
        (Plan-Execute: 절감 계획은 이상탐지 결과 + 최적화 후보를 함께 봐야 하는
        간단한 2단계 분해로 취급한다)
      - 그 외 -> 비용/이상/최적화 키워드에 매칭되는 에이전트를 모두 반환 (여러 개 가능)
      - 아무 것도 해당하지 않으면 빈 목록 (Supervisor가 직접 안내)
    """
    if not question or not question.strip():
        return []

    lowered = question.lower()

    if any(p.search(lowered) for p in _EXECUTION_PATTERNS):
        return ["execution_agent"]

    if any(kw in lowered for kw in _PLAN_KEYWORDS):
        return ["anomaly_agent", "optimization_agent"]

    return [
        name
        for name in ("cost_lookup_agent", "anomaly_agent", "optimization_agent")
        if any(kw in lowered for kw in _AGENT_KEYWORDS.get(name, ()))
    ]


def _last_human_text(messages: list) -> str:
    for m in reversed(messages):
        if getattr(m, "type", None) == "human":
            return str(m.content)
    return ""


def _history_before_last_human(messages: list) -> list:
    """이번 턴 질문(가장 최근 HumanMessage) 앞까지의 대화를 서브 에이전트 히스토리로 돌려준다.

    지금까지 서브 에이전트는 _last_human_text()로 이번 질문 하나만 프롬프트에 받아서
    "방금 뭐라고 물었어?" 같은 후속 질문에 답할 방법이 없었다(대화 기억 없음) — 체크
    포인터가 이전 턴을 다 들고 있어도 LLM에 실제로 전달되는 적이 없었다. 여기 담기는
    메시지(HumanMessage/AIMessage("[에이전트명] 답변"))는 전부 순수 텍스트라 tool_calls가
    안 달려 있어, 원래 만든 서브 에이전트가 아닌 다른 서브 에이전트에 다시 넣어도
    안전하다(Bedrock의 tool_calls/tool_result 짝 검증에 안 걸림).

    별도 길이 제한을 안 두는 이유: pipeline._maybe_summarize_history가 메시지 20개
    초과 시 오래된 부분을 요약 SystemMessage 하나로 이미 교체해두므로(패턴 8), 여기서
    state["messages"]를 그대로 다 넘겨도 무한정 커지지 않는다.
    """
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            return messages[:i]
    return []


# src/llm_utils.py로 옮겼다 — retriever.py/evaluation/run_eval.py와 로직이
# 완전히 같아서 세 군데 따로 유지하는 대신 하나로 합쳤다(코드 리뷰 지적).
_get_text = get_text


def _system_prompt_for(name: str) -> str:
    tools_desc = ", ".join(AGENT_TOOLS.get(name, [])) or "(없음)"
    prompt = (
        f"당신은 {name}입니다. 오늘은 {domain_tools.today_str()}입니다. "
        f"담당 도구: {tools_desc}. 이 범위 안에서만 답하세요. "
        "도구 호출 결과에 없는 수치나 사실을 지어내지 말고, 근거가 없으면 모른다고 답하세요. "
        "바로 아래에 이 대화의 이전 질문·답변이 있다면 참고하세요 — 사용자가 이전에 "
        "무엇을 물었는지, 어떤 답을 받았는지 다시 물으면 그 내용을 그대로 알려주세요."
    )
    if name == "cost_lookup_agent":
        # #14(LLM-as-Judge로 발견): "GCP랑 AWS 스토리지 비용을 비교해줘"에 S3(오브젝트
        # 스토리지)+EBS(블록 스토리지)를 그냥 합쳐 "AWS 스토리지"로 묶고 GCP Cloud
        # Storage와 배율로 직접 비교했다 — 서비스 성격이 다른 항목을 동일 선상에 놓고
        # 비교하면 왜곡된 결론(forbidden: "비교 불가능한 항목을 동일시")이 된다.
        prompt += (
            " 서로 다른 프로바이더의 서비스를 비교할 때, 서비스 성격이 다르면(예: 블록 "
            "스토리지 vs 오브젝트 스토리지) 합산하거나 배율로 직접 비교하기 전에 그 차이를 "
            "먼저 언급하세요. 성격이 같은 항목끼리만 직접 비교하세요."
        )
    if name == "optimization_agent":
        # "이건 도구 범위 밖입니다"라고 스스로 판단해서 retrieve_docs를 아예 안 부르고
        # 넘어가는 경우가 있었다 (여러 차례 다르게 문구를 바꿔도 재현됨). "범위 밖인지
        # 아닌지 판단하는 것" 자체를 도구 호출 뒤로 미루도록 규칙을 절대적으로 만든다 —
        # "~인 것 같으면" 식의 조건부 지시는 LLM이 스스로 "이건 해당 안 된다"고 예외
        # 처리해버릴 여지가 있어서, 예외 없이 매번 호출하게 못박았다.
        prompt += (
            " 절대 규칙: 답을 하기 전에 retrieve_docs를 반드시 최소 한 번 호출하세요. "
            "질문이 도구 범위 밖처럼 보여도 예외가 아닙니다 — 범위 밖인지 아닌지는 "
            "retrieve_docs 결과를 보고 '문서에 근거가 없다'고 확인한 뒤에만 판단하세요. "
            "호출하지 않은 채로 '범위 밖이다/모른다'라고 답하는 것은 금지됩니다. "
            "질문에 리소스 ID가 이미 특정돼 있으면(다운사이징·RI 전환 등 무엇이든) "
            "다른 조회 없이 곧바로 estimate_savings(resource_id, plan_type)를 그 ID로 "
            "호출하세요 — 이 도구는 resource_id와 plan_type만 받고 크기·유형 등 나머지 "
            "정보는 내부에서 스스로 조회하므로, '리소스 사양 정보가 더 필요하다'는 "
            "이유로 호출을 미루거나 거절하는 것은 금지됩니다. 리소스 ID 없이 일반적인 "
            "절감 계획·절감 방안을 묻는 질문이면 답하기 전에 aws_list_idle/gcp_list_idle/"
            "azure_list_idle 중 최소 하나를 반드시 먼저 호출해 유휴 리소스 현황을 "
            "확인하세요 — 유휴 리소스가 없다는 결과가 나와도 그 자체가 근거이므로 호출 "
            "없이 넘어가면 안 됩니다. 그렇게 찾은 유휴 리소스가 있다면 estimate_savings로 "
            "그 중 하나 이상의 절감액을 실제로 계산해 구체적인 수치를 제시하세요. 도구 "
            "결과 없이 절감률·절감액 수치를 스스로 추정해 지어내지 마세요."
        )
    if name == "anomaly_agent":
        # #8(Plan-Execute 복합 질의): 비용 절감 계획처럼 다른 에이전트와 함께 답하는
        # 질문에서 "이건 내 역할이 아니다"라고 판단해 도구를 아예 안 부르는 경우가
        # 있었다. "관련이 있다면"식 조건부 지시는 LLM이 스스로 "이번엔 관련 없다"고
        # 예외 처리할 여지를 준다 — optimization_agent/execution_agent에서 같은
        # 종류의 조건부 표현을 절대 규칙으로 바꿔서 안정화된 적이 있어(round1/round2
        # 재검증 완료), 여기도 같은 방식으로 바꾼다.
        prompt += (
            " 절대 규칙: 비용 절감 계획처럼 여러 에이전트가 나눠 답하는 복합 질문을 "
            "맡으면, 관련 여부를 스스로 판단해 건너뛰지 말고 예외 없이 매번 "
            "detect_cost_anomaly를 먼저 호출해 확인한 뒤 그 결과를 반영해 답하세요. "
            "'이건 내 역할이 아니다'/'이번엔 관련 없다'고 판단해 호출을 건너뛰는 것은 "
            "금지됩니다 — 관련이 없는지 여부는 호출 결과를 보고 나서만 판단하세요."
        )
        # #13(LLM-as-Judge로 발견): "이번 달이랑 지난달이랑 비교가 안 맞는데 왜 그래?"처럼
        # 질문 자체가 모호해서 특정 원인 하나로 단정할 근거가 없는데도, detect_cost_anomaly
        # 결과를 근거 삼아 "이게 원인입니다"라고 확정적으로 답해버리는 경우가 있었다.
        # SERVICE.md 정책 3번("근거 없으면 추측하지 않는다")과 충돌하는 문제라 명시적으로 막는다.
        prompt += (
            " 질문이 모호해서 detect_cost_anomaly 결과만으로 원인을 하나로 단정할 근거가 "
            "부족하면, 확정적으로 답하지 말고 가능한 원인 후보를 여러 개 제시하거나 어떤 "
            "정보가 더 있으면 판단할 수 있는지 되물으세요."
        )
        # 완성도 점검 중 추가: detect_cost_anomaly가 급증을 찾으면 "공휴일이나 장애가
        # 있었는지 확인해보라"고 추측만 시키지 말고, aws/gcp/azure_check_incidents로
        # 그 클라우드에 실제 공개 장애 이력이 있었는지 직접 검증한 뒤 답하라 — 이 도구는
        # 인증 없이 실제 상태 피드를 조회하므로 추측이 아니라 확인된 사실을 줄 수 있다.
        prompt += (
            " detect_cost_anomaly가 특정 날짜의 급증을 찾으면, 그 리소스의 클라우드 "
            "제공자에 맞는 check_incidents 도구로 그 날짜 근처에 실제 공개 장애 이력이 "
            "있었는지 확인한 뒤 그 결과를 반영해 답하세요(있었는지 없었는지 추측하지 "
            "말고 직접 조회하세요). 단, AWS/Azure의 상태 피드는 현재 진행 중인 이슈만 "
            "제공하므로, 결과가 비어 있으면 '장애가 없었다'가 아니라 '과거 이력은 이 "
            "피드로 확인할 수 없다'고 정확히 표현하세요."
        )
        # #15(LLM-as-Judge로 발견): z_threshold를 낮춰 재조회한 결과를 "기준을 낮춰서
        # 확인해봤다"처럼만 서술하면, 마치 이상탐지 설정 자체가 영구히 바뀐 것처럼 읽힐
        # 위험이 있다. detect_cost_anomaly의 z_threshold는 매 호출마다 넘기는 파라미터일
        # 뿐 저장되는 설정이 아니므로, 그 사실을 답변에서 분명히 해야 한다.
        prompt += (
            " 민감도(z_threshold 등) 조정 요청에 답할 땐, 그 값이 이번 조회에만 적용된 "
            "파라미터이고 시스템 설정이 영구히 바뀐 게 아님을 분명히 밝히고, 임계값을 "
            "낮추면 오탐(false positive)이 늘어날 수 있다는 트레이드오프도 함께 안내하세요."
        )
    if name == "execution_agent":
        # #19 같은 케이스: LLM이 스스로 "승인 필요합니다"라고 말로만 답하고 도구 호출
        # 자체를 안 하면, 시스템의 interrupt() 승인 게이트가 아예 실행되지 않는다.
        # 승인 여부 판단은 LLM이 아니라 시스템(needs_approval)의 역할임을 명시한다.
        prompt += (
            " 절대 규칙: 대상 리소스가 특정된 실행 요청이면 예외 없이 도구를 그대로 "
            "호출하세요. '사용자 확인이 필요합니다', '승인 후 실행하겠습니다' 같은 "
            "문장으로 도구 호출을 대신하는 것은 금지됩니다 — 그런 문장은 승인 게이트를 "
            "흉내낼 뿐 실제로는 작동시키지 못합니다. 승인 게이트는 당신이 도구를 실제로 "
            "호출해야만 시스템이 가로채 작동합니다. 도구를 호출하지 않으면 시스템은 "
            "사용자에게 승인 요청 자체를 보내지 못하고, 그 요청은 그대로 묵살됩니다. "
            "승인이 필요한지·거부할지는 시스템이 자동으로 판단하고 처리하므로 그 판단을 "
            "당신이 텍스트로 대신하지 마세요. 다만 어떤 리소스를 대상으로 할지 특정할 수 "
            "없을 때만 도구를 호출하지 않고 사용자에게 되물으세요."
        )
    return prompt


class SupervisorState(TypedDict):
    messages: Annotated[list, add_messages]
    targets: list[str]
    pending: list[str]
    pending_tool_calls: list[dict]
    # execution_agent가 pending_tool_calls를 하나씩 처리하며 쌓는 결과 문자열.
    # 마지막 호출까지 끝나면 이걸 합쳐 최종 메시지를 만들고 비운다.
    execution_results: list[str]
    # 서브 에이전트가 실제로 호출한 도구 입출력 기록. API 응답의 trace/contexts를
    # 여기서 뽑아 쓴다. 노드마다 리스트를 반환하면 자동으로 이어 붙는다(operator.add).
    trace: Annotated[list[dict], operator.add]
    # 지금까지 실제로 라우팅을 마친 human 메시지 개수 — _supervisor_node가 "같은 턴
    # 안에서 워커가 돌아온 것"과 "체크포인터에 저장된 이전 턴 상태 위에서 새 질문이
    # 들어온 것"을 구분하는 데 쓴다. 자세한 이유는 _supervisor_node 문서 참고.
    routed_human_count: int
    # 이번 턴이 시작되기 *전* trace 리스트 길이. trace는 operator.add로 스레드
    # 전체 동안 계속 이어 붙기만 하고 턴 경계가 따로 없어서, pipeline.finalize()가
    # "이번 턴에 새로 생긴 항목"만 골라내려면 이 기준점이 필요하다
    # (trace[trace_baseline:]). messages는 HumanMessage 경계로 구분 가능하지만
    # trace는 그런 자연스러운 구분자가 없어서 따로 기록해 둔다.
    trace_baseline: int
    # 이번 턴에 실제로 응답한 Bedrock 모델 — MODEL_FAILOVER.md 참고. Annotated 없이
    # 평범한 키로 둬서 "마지막으로 쓴 노드의 값이 남는다"(LangGraph 기본 동작, 즉
    # 트레이스처럼 계속 누적하는 게 아니라 덮어쓴다). 처음엔 llm_utils의 contextvar로
    # 구현했다가 실제로 돌려보니 항상 비어 있었다 — LangGraph 노드 실행이 asyncio
    # 태스크 경계를 만들어서, 그 안에서 contextvar.set()해도 밖(pipeline.finalize())
    # 에서는 안 보였다(직접 겪음). 그래서 트레이스와 같은 방식으로 그래프 상태를
    # 통해 값을 들고 나온다.
    active_model: str | None
    # 안전장치 4(SAFEGUARDS.md) — 이번 턴에 서브 에이전트/execution_agent가 실제로
    # 만든 Bedrock 호출 수(ReAct 루프 각 반복 = 1회). trace처럼 스레드 전체 동안
    # operator.add로 계속 누적되고, llm_calls_baseline이 trace_baseline과 같은
    # 역할(이번 턴 시작 시점 값을 기록)을 한다. retrieve_docs 내부의 쿼리확장·
    # 리랭킹·자체 답변 합성 호출과 answer_chain 호출은 여기 안 잡힌다(그래프 노드가
    # 아니라 도구/파이프라인 안쪽에서 일어남) — "서브 에이전트 추론 호출"만 세는
    # 근사치라는 걸 SAFEGUARDS.md에 명시해뒀다.
    llm_calls_made: Annotated[int, operator.add]
    llm_calls_baseline: int


# 안전장치 4 — 한 턴 전체(여러 서브 에이전트가 나눠 처리하는 복합 질문 포함)에서
# 쓸 수 있는 Bedrock 추론 호출 수의 상한. route_question()이 한 질문을 최대
# 3개 에이전트(cost_lookup/anomaly/optimization)에 동시 배분할 수 있고, 각자
# 도구 호출 예산(4~7)만큼 ReAct 루프를 돌 수 있어 이론상 최대 15회 정도까지는
# 정상 시나리오다 — 그보다 넉넉히 위에 상한을 둬서, 정상 케이스는 절대 안 걸리고
# 진짜 이상(버그·반복 질문 등)한 경우만 막는다.
TURN_LLM_CALL_BUDGET = 20


def _human_message_count(messages: list) -> int:
    return sum(1 for m in messages if getattr(m, "type", None) == "human")


def _supervisor_node(state: SupervisorState) -> dict:
    """질문을 서브 에이전트에 배분한다 (최초 1회만, 같은 턴 안에서는 재계산하지 않는다).

    `pending`이 `None`인지만 보고 재계산 여부를 판단하면 버그가 난다: 체크포인터가
    같은 thread_id의 상태를 다음 질문에도 그대로 이어주므로, 이전 턴이 끝나면
    `pending`은 `[]`(빈 리스트, None이 아님)로 영구히 남는다. 다음 턴에 새 질문이
    들어와도 `pending is not None`이 True라서 라우팅을 건너뛰고 그래프가 곧장
    끝나버려, 사용자가 뭘 물어보든 첫 턴의 답변이 그대로 반복 반환되는 사고로
    이어졌다 (직접 재현해서 발견 — 두 번째 질문부터는 에이전트가 아예 호출되지
    않았다). 그래서 "이번에 실제로 처리한 human 메시지 수"를 같이 저장해두고,
    현재 human 메시지 수와 비교해서 "새 질문이 들어왔는가"를 판단한다 — 같은
    질문을 두 번 연달아 물어봐도(텍스트 비교였다면 놓쳤을 케이스) 메시지 개수는
    늘어나므로 정확히 구분된다.
    """
    human_count = _human_message_count(state["messages"])
    if state.get("pending") is not None and state.get("routed_human_count") == human_count:
        # 안전장치 4(SAFEGUARDS.md) — 같은 턴 안에서 워커가 막 돌아온 것이다. 새로
        # 라우팅할 필요는 없지만, 이번 턴에 이미 쓴 호출이 예산을 넘었으면 남은
        # pending을 비워서 더 이상 다음 에이전트로 넘어가지 않게 막는다.
        used = (state.get("llm_calls_made") or 0) - (state.get("llm_calls_baseline") or 0)
        if used >= TURN_LLM_CALL_BUDGET and state.get("pending"):
            return {
                "pending": [],
                "messages": [
                    AIMessage(
                        content=(
                            f"[supervisor] 이번 턴에서 처리 가능한 LLM 호출 예산({TURN_LLM_CALL_BUDGET}회)을 "
                            "다 써서 여기까지만 확인했습니다. 질문을 더 구체적으로 나눠서 다시 물어봐 주세요."
                        )
                    )
                ],
            }
        return {}

    question = _last_human_text(state["messages"])
    targets = route_question(question)
    if not targets and human_count > 1:
        # 키워드 매칭은 안 됐지만(예: "방금 뭐라고 물었어?" 같은 후속/메타 질문),
        # 이미 진행 중이던 대화라면 직전 턴에 실제로 라우팅됐던 에이전트에게 그대로
        # 이어서 맡긴다 — _make_agent_node가 이제 대화 히스토리를 프롬프트에 넣어주므로
        # (_history_before_last_human) 그 에이전트가 이전 맥락을 참고해 답할 수 있다.
        # 첫 턴부터 범위 밖이면(이전 라우팅 자체가 없음) 기존처럼 거절한다 — 대화
        # 맥락이 전혀 없는 새 스레드에서까지 아무 도구 에이전트나 억지로 호출하지 않기 위함.
        targets = list(state.get("targets") or [])
    update: dict = {
        "targets": targets,
        "pending": list(targets),
        "pending_tool_calls": [],
        "routed_human_count": human_count,
        "trace_baseline": len(state.get("trace") or []),
        "llm_calls_baseline": state.get("llm_calls_made") or 0,
    }
    if not targets:
        update["messages"] = [
            AIMessage(
                content=(
                    "이 질문은 비용 조회·이상탐지·최적화·실행 중 어디에도 해당하지 않아 "
                    "처리할 수 없습니다. 클라우드 비용 관련 질문으로 다시 물어봐 주세요."
                )
            )
        ]
    return update


def _route_from_supervisor(state: SupervisorState) -> str:
    pending = state.get("pending") or []
    return pending[0] if pending else END


# ══════════════════════════════════════════════════════════════════
# 조회형 서브 에이전트 — Day 3 ReAct 루프를 도구 범위만 바꿔 재사용
# ══════════════════════════════════════════════════════════════════

# 모듈 최상위에 둬야 한다: langgraph가 조건부 엣지 함수의 타입힌트를
# get_type_hints()로 읽는데, 함수 안에 중첩 정의된 TypedDict는 이름을 못 찾는다
# (PEP 563 지연 평가 + 로컬 스코프 조합 문제).
class _ReactSubState(TypedDict):
    messages: Annotated[list, add_messages]
    tool_calls_made: int
    active_model: str | None
    # 안전장치 4(SAFEGUARDS.md) — 이 ReAct 루프가 실제로 만든 Bedrock 호출 수(반복
    # 한 번=1회). _make_agent_node의 바깥 node()가 이 서브그래프 실행이 끝난 뒤
    # 총합을 꺼내 바깥 SupervisorState.llm_calls_made에 더해 넣는다.
    llm_calls_made: Annotated[int, operator.add]


# MCP 서버(aws/gcp/azure cost_server.py)는 별도 자식 프로세스라 authz의 contextvars가
# 안 건너간다(mcp_servers/cost_server.py의 "알려진 한계" 주석 참고). 리소스 단위로
# 조회하는 이 도구들만, 실제 MCP 프로세스를 부르기 전에 부모 프로세스(여기)에서 소유
# 팀을 먼저 확인해 가로챈다 — costs.db는 부모·자식이 같은 파일을 보므로 가능하다.
_MCP_RESOURCE_SCOPED_TOOLS = {"aws_get_utilization", "gcp_get_utilization", "azure_get_utilization"}


def _mcp_resource_authz_denial(name: str, args) -> str | None:
    if name not in _MCP_RESOURCE_SCOPED_TOOLS:
        return None
    resource_id = args.get("resource_id") if isinstance(args, dict) else None
    if not resource_id:
        return None
    team = domain_tools.resource_team(resource_id)
    if team is None:
        return None  # 존재하지 않는 리소스는 MCP 도구 자체가 "찾을 수 없음"으로 답하게 둔다
    return authz.check_resource_team(team)


def _build_react_subgraph(
    tool_fns: list, llm, label: str, max_calls: int = MAX_TOOL_CALLS_PER_AGENT, fallback_ids: tuple[str, ...] = ()
):
    """도구 실행을 ainvoke로 돌린다 — MCP 도구(aws_get_cost 등)는 원격 서버와 stdio로
    통신하는 비동기 전용 도구라 동기 invoke를 지원하지 않는다. 순수 로컬 동기 도구를
    쓰는 anomaly_agent도 같은 경로를 타지만, LangChain 도구는 sync만 정의돼 있으면
    ainvoke가 내부적으로 스레드에서 동기 실행을 감싸주므로 문제없다.

    label은 트레이스(observability.Timer)에 남기는 이름이다 (패턴 11).
    max_calls는 이 서브 에이전트의 도구 호출 예산 — _max_tool_calls_for() 참고.
    fallback_ids는 llm이 재시도까지 다 실패했을 때 이어서 시도할 모델 ID 목록이다
    (MODEL_FAILOVER.md 참고) — build_supervisor가 llm을 명시적으로 안 받았을 때만
    채워준다. 테스트가 FakeLLM을 주입하는 경로에서는 항상 빈 튜플이라 동작이 기존과
    완전히 같다.
    """
    if fallback_ids:
        # 실제 페일오버 구성일 때만 재시도를 1회로 줄인다 — 이유는
        # llm_utils.with_bedrock_retry 문서 참고. 테스트가 llm을 명시적으로 주입한
        # 경로(fallback_ids=())는 대체 모델이 없으니 기존처럼 3회 재시도를 유지한다.
        primary = with_bedrock_retry(llm.bind_tools(tool_fns), stop_after_attempt=1)
        fallbacks = llm_utils.build_fallback_candidates(tool_fns, fallback_ids)
        llm_with_tools = llm_utils.with_circuit_breaker_failover([(MODEL_ID, primary), *fallbacks])
    else:
        llm_with_tools = with_bedrock_retry(llm.bind_tools(tool_fns))
    tool_node = ToolNode(tool_fns)

    async def agent_node(state: _ReactSubState) -> dict:
        with observability.Timer("llm", label):
            response = await llm_with_tools.ainvoke(state["messages"])
        update: dict = {"messages": [response], "llm_calls_made": 1}
        model_id = llm_utils.extract_active_model(response)
        if model_id:
            update["active_model"] = model_id
        return update

    async def tools_node(state: _ReactSubState) -> dict:
        last = state["messages"][-1]
        calls = getattr(last, "tool_calls", None) or []

        denial_messages: list[ToolMessage] = []
        allowed_ids: set[str] = set()
        for call in calls:
            name = call["name"] if isinstance(call, dict) else call.name
            args = call["args"] if isinstance(call, dict) else call.args
            call_id = call["id"] if isinstance(call, dict) else call.id
            denial = _mcp_resource_authz_denial(name, args)
            if denial:
                denial_messages.append(ToolMessage(content=denial, tool_call_id=call_id, name=name))
            else:
                allowed_ids.add(call_id)

        if denial_messages and allowed_ids:
            # 일부만 거절됐다 -- 허용된 호출만 ToolNode(실제 MCP 프로세스 호출 포함)에 넘긴다.
            remaining = [c for c in calls if (c["id"] if isinstance(c, dict) else c.id) in allowed_ids]
            trimmed_last = last.model_copy(update={"tool_calls": remaining})
            sub_state = {**state, "messages": [*state["messages"][:-1], trimmed_last]}
            with observability.Timer("tool_batch", label):
                tool_result = await tool_node.ainvoke(sub_state)
            result = {"messages": denial_messages + tool_result.get("messages", [])}
        elif denial_messages:
            # 전부 거절됐다 -- MCP 프로세스를 아예 안 부른다.
            result = {"messages": denial_messages}
        else:
            with observability.Timer("tool_batch", label):
                result = await tool_node.ainvoke(state)
        # 가드레일 규칙 4: 도구 결과(리소스 태그·설명 등 외부 데이터)가 다음 LLM
        # 호출의 컨텍스트로 들어가기 전에 지시문처럼 보이는 패턴을 무력화한다.
        # 로컬 도구든 MCP 도구든 여기를 한 번은 지나가므로 한 곳에서 전부 막힌다.
        sanitized_messages = [
            ToolMessage(
                content=guardrails.sanitize_tool_output(_get_text(m)),
                tool_call_id=m.tool_call_id,
                name=m.name,
            )
            if isinstance(m, ToolMessage)
            else m
            for m in result["messages"]
        ]
        made = state.get("tool_calls_made", 0) + len(result.get("messages", []))
        return {"messages": sanitized_messages, "tool_calls_made": made}

    def route(state: _ReactSubState) -> str:
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            return END
        made = state.get("tool_calls_made", 0)
        return END if made >= max_calls else "tools"

    graph = StateGraph(_ReactSubState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()


def _tool_fns_for(name: str, retrieve_docs_tool, mcp_tools: list) -> list:
    mcp_map = {t.name: t for t in mcp_tools}
    fns = []
    for tool_name in AGENT_TOOLS[name]:
        if tool_name == "retrieve_docs":
            fns.append(retrieve_docs_tool)
        elif tool_name in mcp_map:
            fns.append(mcp_map[tool_name])
        elif tool_name in domain_tools.TOOL_MAP:
            fns.append(domain_tools.TOOL_MAP[tool_name])
        else:
            # MCP 서버 중 하나가 기동에 실패했거나 도구를 덜 노출한 경우 여기 걸린다.
            # 그냥 두면 다른 도구 이름과 구분 안 되는 KeyError가 나서 원인을 알기 어렵다.
            raise RuntimeError(
                f"'{name}' 서브 에이전트의 도구 '{tool_name}'을 찾을 수 없습니다. "
                "로컬 도구에도, 로드된 MCP 도구에도 없습니다 — MCP 서버(aws/gcp/azure "
                "cost_server.py)가 전부 정상 기동했는지 확인하세요."
            )
    return fns


def _make_agent_node(name: str, tool_fns: list, llm, fallback_ids: tuple[str, ...] = ()):
    max_calls = _max_tool_calls_for(name)
    subgraph = _build_react_subgraph(tool_fns, llm, label=name, max_calls=max_calls, fallback_ids=fallback_ids)

    async def node(state: SupervisorState) -> dict:
        question = _last_human_text(state["messages"])
        history = _history_before_last_human(state["messages"])
        sub_messages = [
            SystemMessage(content=_system_prompt_for(name)),
            *history,
            HumanMessage(content=question),
        ]
        result = await subgraph.ainvoke(
            {"messages": sub_messages, "tool_calls_made": 0, "active_model": None, "llm_calls_made": 0}
        )
        last_message = result["messages"][-1]

        if getattr(last_message, "tool_calls", None):
            # route()가 MAX_TOOL_CALLS_PER_AGENT에 걸려 도구를 더 못 부르고 강제
            # 종료된 경우다. 이 메시지의 content는 텍스트가 아니라 도구 호출
            # 요청이라 _get_text가 빈 문자열을 돌려주고, 그대로 두면 judge_output이
            # "저가치"로 침묵시켜 사용자는 왜 답이 없는지 알 길이 없다.
            text = (
                f"조사 가능한 도구 호출 횟수({max_calls}회)를 다 써서 "
                "여기까지만 확인했습니다. 질문을 더 구체적으로 나눠서 다시 물어봐 주세요."
            )
        else:
            text = _get_text(last_message)

        judged = judge_output(name, text)
        rendered = f"[{name}] {text}" if judged.get("keep") else f"[{name}] (억제됨: {judged.get('reason', '')})"

        tool_trace = [
            # MCP 도구는 content가 [{"type": "text", "text": "..."}] 블록 리스트로 온다
            # (로컬 도구는 그냥 문자열). _get_text가 두 형태 다 처리한다.
            {"step": name, "tool": getattr(m, "name", None), "output": _get_text(m)}
            for m in result["messages"]
            if isinstance(m, ToolMessage)
        ]

        remaining = [t for t in (state.get("pending") or []) if t != name]
        outer_update: dict = {"messages": [AIMessage(content=rendered)], "pending": remaining, "trace": tool_trace}
        if result.get("active_model"):
            outer_update["active_model"] = result["active_model"]
        outer_update["llm_calls_made"] = result.get("llm_calls_made", 0)
        return outer_update

    return node


# ══════════════════════════════════════════════════════════════════
# 실행 에이전트 — 승인(HITL) 이후에만 도구를 실행한다
# ══════════════════════════════════════════════════════════════════

def _execution_decide_node(llm, fallback_ids: tuple[str, ...] = ()):
    """어떤 실행 도구를 호출할지 LLM이 결정한다 (아직 실행하지 않는다).

    fallback_ids는 _build_react_subgraph와 같은 이유 — MODEL_FAILOVER.md 참고.
    """
    exec_tools = _tool_fns_for("execution_agent", retrieve_docs_tool=None, mcp_tools=[])
    if fallback_ids:
        primary = with_bedrock_retry(llm.bind_tools(exec_tools), stop_after_attempt=1)
        fallbacks = llm_utils.build_fallback_candidates(exec_tools, fallback_ids)
        llm_with_tools = llm_utils.with_circuit_breaker_failover([(MODEL_ID, primary), *fallbacks])
    else:
        llm_with_tools = with_bedrock_retry(llm.bind_tools(exec_tools))

    async def node(state: SupervisorState) -> dict:
        question = _last_human_text(state["messages"])
        history = _history_before_last_human(state["messages"])
        messages = [
            SystemMessage(content=_system_prompt_for("execution_agent")),
            *history,
            HumanMessage(content=question),
        ]
        with observability.Timer("llm", "execution_agent"):
            response = await llm_with_tools.ainvoke(messages)
        model_id = llm_utils.extract_active_model(response)
        raw_calls = getattr(response, "tool_calls", None) or []
        normalized = [
            {
                "name": c["name"] if isinstance(c, dict) else c.name,
                "args": c["args"] if isinstance(c, dict) else c.args,
            }
            for c in raw_calls
        ]

        if not normalized:
            text = _get_text(response)
            remaining = [t for t in (state.get("pending") or []) if t != "execution_agent"]
            update: dict = {
                "messages": [AIMessage(content=f"[execution_agent] {text}")],
                "pending": remaining,
                "pending_tool_calls": [],
            }
        else:
            update = {"pending_tool_calls": normalized}
        if model_id:
            update["active_model"] = model_id
        update["llm_calls_made"] = 1
        return update

    return node


def _execution_approve_node(state: SupervisorState) -> dict:
    """대기 중인 실행 도구 호출 중 맨 앞의 것 '하나만' 승인 확인 후 실행한다.

    이 노드는 LLM을 호출하지 않는다 — interrupt()로 멈췄다가 재개(resume)될 때
    이 함수가 처음부터 다시 실행되므로, LLM 호출이 섞여 있으면 재개할 때마다
    모델을 또 부르게 된다. 결정(LLM)과 승인+실행(결정적)을 노드로 분리한 이유다.

    호출을 여러 개 파이썬 for문으로 한 노드 안에서 처리하면 안 된다: interrupt()는
    노드가 반환한 값이 아니라 노드가 몇 번째 interrupt()를 지났는지로 재개 지점을
    구분한다. 재개되면 노드 함수가 처음부터 다시 실행되면서 이미 지난 interrupt()는
    캐시된 값을 즉시 돌려주지만, 그 사이/이후의 부수효과 코드(tool_fn.invoke 같은
    실제 실행)는 캐시되지 않고 매번 다시 실행된다. 호출이 2개 이상이면 앞선 호출이
    승인마다 중복 실행되는 사고로 이어진다. 그래서 호출 하나를 처리할 때마다
    pending_tool_calls에서 그 항목을 빼고 그래프 엣지로 자기 자신에게 돌아가게
    만들었다 — 매번 새 노드 실행이라 이전 호출의 실행 코드가 재실행되지 않는다.
    """
    calls = state.get("pending_tool_calls") or []
    if not calls:
        return {}

    call, *rest = calls
    name, args = call["name"], call["args"]
    trace: list[dict] = []

    needs, reason = guardrails.needs_approval(name, args)
    if needs:
        decision = interrupt({"tool": name, "args": args, "reason": reason})
        approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)
        trace.append({"step": "execution_agent", "tool": name, "output": f"승인 요청: {reason} -> {approved}"})
        if not approved:
            result_text = f"'{name}' 실행 보류: 승인 거부 ({reason})"
            return _finish_execution_call(state, rest, result_text, trace)

    tool_fn = domain_tools.TOOL_MAP.get(name)
    if tool_fn is None:
        result_text = f"'{name}'은 등록되지 않은 도구입니다."
    else:
        with observability.Timer("tool", name):
            output = tool_fn.invoke(args)
        trace.append({"step": "execution_agent", "tool": name, "output": str(output)})
        result_text = str(output)

    return _finish_execution_call(state, rest, result_text, trace)


def _finish_execution_call(state: SupervisorState, rest: list[dict], result_text: str, trace: list[dict]) -> dict:
    """이번 호출 결과를 쌓고, 남은 게 없으면 최종 메시지로 합쳐 supervisor로 돌아간다."""
    results = (state.get("execution_results") or []) + [result_text]
    update: dict = {"pending_tool_calls": rest, "execution_results": results, "trace": trace}

    if not rest:
        remaining = [t for t in (state.get("pending") or []) if t != "execution_agent"]
        update["messages"] = [AIMessage(content="[execution_agent] " + " / ".join(results))]
        update["pending"] = remaining
        update["execution_results"] = []

    return update


def _route_from_execution_approve(state: SupervisorState) -> str:
    return "execution_agent_approve" if state.get("pending_tool_calls") else "supervisor"


# ══════════════════════════════════════════════════════════════════
# 그래프 조립
# ══════════════════════════════════════════════════════════════════

def _default_retrieve_docs_tool():
    from retriever import (
        build_chunks,
        build_expanded_retriever,
        build_rag_chain,
        build_reranker,
        build_retriever,
        make_retrieve_docs_tool,
    )

    chunks = build_chunks()
    hybrid_retriever = build_retriever(chunks)
    expanded_retriever = build_expanded_retriever(hybrid_retriever)  # 쿼리 확장
    reranker = build_reranker()  # 리랭킹
    # base_retriever(hybrid_retriever)를 같이 넘기면, 확장 전 기본 검색만으로 이미
    # 확신도가 높은 질문은 쿼리 확장+리랭킹(LLM 호출 2회)을 건너뛴다(retriever.py의
    # build_rag_chain 문서 참고) — retrieve_docs 호출이 잦은 optimization_agent
    # 질문의 체감 지연을 줄이기 위함.
    rag_chain = build_rag_chain(expanded_retriever, base_retriever=hybrid_retriever, reranker=reranker)
    return make_retrieve_docs_tool(rag_chain)


def build_supervisor(llm=None, retrieve_docs_tool=None, mcp_tools=None, checkpointer=None):
    """Supervisor 그래프를 만들어 컴파일해 반환한다.

    - AGENT_NAMES 넷 모두 노드로 존재한다 (execution_agent는 decide/approve 2단계 내부 구조).
    - supervisor -> 각 에이전트 -> supervisor 로 돌아오는 경로, 종료 경로(END)가 있다.
    - checkpointer를 주면 execution_agent의 interrupt()를 이용한 HITL 재개가 가능하다.
      (interrupt는 체크포인터 없이는 재개할 상태를 저장할 곳이 없어 동작하지 않는다.)
    - mcp_tools를 주지 않으면 mcp_client로 aws/gcp/azure cost MCP 서버 3개를 직접 띄워
      가져온다. FastAPI처럼 이미 이벤트 루프 안에 있는 호출자는 asyncio.run을 또 부를 수
      없으므로, 그런 경우 mcp_client.load_mcp_tools()를 await 해서 얻은 값을 넘겨야 한다.
    - llm을 명시적으로 주면(테스트의 FakeLLM 등) 그 인스턴스만 쓰고 페일오버를 안 건다.
      llm=None(기본 경로)일 때만 llm_utils.MODEL_PRIORITY의 나머지 8개를 페일오버
      후보로 서브 에이전트·execution_agent 노드에 같이 넘긴다 (MODEL_FAILOVER.md 참고).
    """
    use_failover = llm is None
    llm = llm or _default_llm()
    fallback_ids: tuple[str, ...] = tuple(llm_utils.MODEL_PRIORITY[1:]) if use_failover else ()
    retrieve_docs_tool = retrieve_docs_tool or _default_retrieve_docs_tool()
    if mcp_tools is None:
        from mcp_client import load_mcp_tools_sync

        mcp_tools = load_mcp_tools_sync()

    graph = StateGraph(SupervisorState)
    graph.add_node("supervisor", _supervisor_node)

    for name in AGENT_NAMES:
        if name == "execution_agent":
            graph.add_node(name, _execution_decide_node(llm, fallback_ids=fallback_ids))
            graph.add_node("execution_agent_approve", _execution_approve_node)
            graph.add_edge(name, "execution_agent_approve")
            # 대기 중인 호출이 남아 있으면 자기 자신으로 돌아가 다음 호출 하나를
            # 새 노드 실행으로 처리한다 (한 노드 안에서 여러 개를 처리하면 안 되는
            # 이유는 _execution_approve_node 문서 참고).
            graph.add_conditional_edges(
                "execution_agent_approve",
                _route_from_execution_approve,
                {"execution_agent_approve": "execution_agent_approve", "supervisor": "supervisor"},
            )
        else:
            tool_fns = _tool_fns_for(name, retrieve_docs_tool, mcp_tools)
            graph.add_node(name, _make_agent_node(name, tool_fns, llm, fallback_ids=fallback_ids))
            graph.add_edge(name, "supervisor")

    graph.set_entry_point("supervisor")
    graph.add_conditional_edges(
        "supervisor",
        _route_from_supervisor,
        {**{name: name for name in AGENT_NAMES}, END: END},
    )
    return graph.compile(checkpointer=checkpointer)


# ══════════════════════════════════════════════════════════════════
# 워커 산출물 게이트 — Day 6 judge_output과 동일한 취지
# ══════════════════════════════════════════════════════════════════

_ASSERTIVE_PHRASES = ("확실합니다", "틀림없습니다", "틀림없이", "분명합니다", "명백합니다", "확실해요")
_DIGIT_PATTERN = re.compile(r"\d")
_SOURCE_WORDS = ("출처", "근거", "정책", "문서", "z-score", "http", "source")


def judge_output(agent_name: str, output: str) -> dict:
    """워커 산출물을 내보내기 전에 걸러낸다. LLM을 호출하지 않는다.

    판정 규칙 (Day 6와 동일한 취지, 우리 도메인 답변이 짧을 수 있어 길이 기준만 완화):
      - 내용이 비었거나 10자 미만                     -> 저가치
      - 근거 없는 단정 표현이 있는데 수치·출처가 없음  -> 근거 없는 단정
      - 그 외                                          -> 유지
    """
    text = (output or "").strip()
    if len(text) < 10:
        return {"keep": False, "reason": "저가치"}

    has_assertion = any(p in text for p in _ASSERTIVE_PHRASES)
    has_number = bool(_DIGIT_PATTERN.search(text))
    has_source = any(w in text.lower() for w in _SOURCE_WORDS)
    if has_assertion and not (has_number or has_source):
        return {"keep": False, "reason": "근거 없는 단정"}

    return {"keep": True, "reason": "정상 산출물로 판단했습니다."}
