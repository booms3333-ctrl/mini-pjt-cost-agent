"""가드레일 · HITL 판정 · 미들웨어 순서.

Day 5 (day05/practice/starter/submission.py) 를 기반으로, 클라우드 비용 도메인에
맞춰 확장했다. input_guard/mask_pii 의 규칙 기반 구조는 그대로 가져오고,
RISK_LEVELS/needs_approval 은 이 프로젝트의 도구 이름으로 새로 정의했다.

원칙(Day 5와 동일): 이 파일의 함수는 LLM을 호출하지 않는다. 같은 입력엔 항상 같은 출력.
"""

from __future__ import annotations

import re

# ══════════════════════════════════════════════════════════════════
# 입력 가드레일 — 프롬프트 인젝션 · 파괴적 명령 · 정보 추출 시도 차단
# (Day 5 input_guard 그대로 재사용. 단어 하나가 아니라 '의도의 조합'을 본다.)
# ══════════════════════════════════════════════════════════════════

_OVERRIDE_VERBS = (
    "무시", "잊", "무효화", "버리고", "벗어나", "취소",
    "ignore", "disregard", "forget", "override", "bypass",
)
_INSTRUCTION_TARGETS = (
    "지시", "지침", "규칙", "가이드라인", "명령", "대화", "프롬프트",
    "system prompt", "system message", "instruction", "rule", "guideline", "prompt",
)
_ROLE_REASSIGN_PATTERNS = (
    re.compile(r"(너의|당신의|니)\s*역할은"),
    re.compile(r"역할(을|로)\s*(부여|전환)"),
    re.compile(r"you are now\b"),
    re.compile(r"\bdan\b"),
    re.compile(r"관리자\s*모드로\s*전환"),
)
_INJECTION_MARKERS = (
    re.compile(r"###\s*new instruction"),
    re.compile(r"new instruction\s*:"),
    re.compile(r"ignore (all )?previous instructions"),
)
_JAILBREAK_PATTERNS = (
    re.compile(r"개발자\s*모드"),
    re.compile(r"developer\s*mode"),
    re.compile(r"제한\s*없이"),
    re.compile(r"제약\s*없이"),
    re.compile(r"필터\s*없는"),
    re.compile(r"무제한\s*(ai|모드)"),
    re.compile(r"unrestricted"),
    re.compile(r"jailbreak"),
)
_SHELL_DESTRUCTIVE_MARKERS = (
    re.compile(r"rm\s+-rf"),
    re.compile(r"format\s+(the\s+)?(disk|drive|c:)"),
    re.compile(r"shutdown\s+-h"),
    re.compile(r"kill\s+-9"),
)

_WEAK_EXTRACTION_VERBS = ("알려줘", "알려주", "알려다오", "말해줘", "말해", "말씀해")
_STRONG_EXTRACTION_VERBS = (
    "출력해", "출력", "보여줘", "보여주", "전문을", "공유해",
    "reveal", "print", "output", "show me", "show", "display",
)
_PROCEDURAL_WORDS = ("절차", "방법", "방식", "가이드", "프로세스", "어떻게", "how to")
# 클라우드 도메인 확장: 계정/청구/자격증명 관련 추출 대상을 추가
_EXTRACTION_TARGETS = (
    "시스템 프롬프트", "시스템 지침", "시스템 메시지", "system prompt", "system message",
    "내부 토큰", "api 키", "api key", "액세스 키", "access key", "시크릿", "secret",
    "비밀번호", "패스워드", "password", "인증 정보", "인증정보",
    "credential", "자격증명", "prompt",
    "계정 정보", "청구 정보", "billing info", "account credential", "구독 id", "subscription id",
)
_INFRA_SECRET_TARGETS = ("환경 변수", "env var", ".env", "설정 파일", "config file")
_VALUE_DUMP_WORDS = ("값", "내용", "전부", "전체", "모두", "다")
_REPEAT_AFTER_ME = re.compile(r"(그대로\s*따라\s*해|repeat after me|say exactly)")
_SECRET_WORDS = ("키", "비밀번호", "토큰", "credential", "key", "password", "token")

# Day 5 원본에는 "파괴적 명령 + 스코프 + 실행 동사" 조합을 여기서 통째로 차단하는
# 규칙이 있었다. 이 프로젝트에서는 일부러 뺐다: stop_resource/resize_resource는
# RISK_LEVELS에서 이미 무조건 "destructive"로 분류돼 needs_approval()이 항상
# True를 돌려주고, execution_agent가 interrupt()로 사람 승인을 받은 뒤에만
# 실행한다. 입력 단계에서 "정지해줘" 같은 평범한 표현까지 더 막으면, 승인
# 절차로 안전하게 처리되어야 할 정상 요청이 그 절차에 도달하기도 전에
# 차단되어 버린다 (SERVICE.md 정책 2번과 충돌). 진짜 공격(프롬프트 인젝션,
# 정보 추출)은 위의 다른 규칙들이 이미 막는다.


def input_guard(text: str) -> tuple[bool, str]:
    """입력을 검사해 차단 여부를 정한다. Returns (차단할지 여부, 사유)."""
    if not text or not text.strip():
        return False, "빈 입력입니다."

    lowered = text.lower()

    has_override_verb = any(v in lowered for v in _OVERRIDE_VERBS)
    has_instruction_target = any(t in lowered for t in _INSTRUCTION_TARGETS)
    if has_override_verb and has_instruction_target:
        return True, "지시를 덮어쓰려는 요청으로 판단해 차단했습니다 (재정의 시도)."

    if any(p.search(lowered) for p in _INJECTION_MARKERS):
        return True, "프롬프트 주입 마커가 감지되어 차단했습니다."

    if any(p.search(lowered) for p in _ROLE_REASSIGN_PATTERNS):
        return True, "역할 재정의 시도로 판단해 차단했습니다."

    if any(p.search(lowered) for p in _JAILBREAK_PATTERNS):
        return True, "탈옥/무제한 모드 요청으로 판단해 차단했습니다."

    if any(p.search(lowered) for p in _SHELL_DESTRUCTIVE_MARKERS):
        return True, "시스템을 직접 파괴하는 명령이 감지되어 차단했습니다."

    is_procedural = any(p in lowered for p in _PROCEDURAL_WORDS)
    has_strong_verb = any(v in lowered for v in _STRONG_EXTRACTION_VERBS)
    has_weak_verb = any(v in lowered for v in _WEAK_EXTRACTION_VERBS)
    has_extraction_verb = has_strong_verb or (has_weak_verb and not is_procedural)
    has_extraction_target = any(t in lowered for t in _EXTRACTION_TARGETS)
    if has_extraction_verb and has_extraction_target:
        return True, "내부 정보/계정 정보 추출 시도로 판단해 차단했습니다."

    has_infra_target = any(t in lowered for t in _INFRA_SECRET_TARGETS)
    has_value_dump = any(v in lowered for v in _VALUE_DUMP_WORDS)
    has_secret_word = any(s in lowered for s in _SECRET_WORDS)
    if has_extraction_verb and has_infra_target and (has_value_dump or has_secret_word):
        return True, "환경설정/자격정보 통째 노출 요청으로 판단해 차단했습니다."

    if _REPEAT_AFTER_ME.search(lowered) and any(s in lowered for s in _SECRET_WORDS):
        return True, "민감한 값을 그대로 출력하게 하려는 시도로 판단해 차단했습니다."

    return False, "차단 규칙에 해당하지 않습니다."


# ══════════════════════════════════════════════════════════════════
# 출력 마스킹 — 자격증명 · 계정 정보 노출 방지
# ══════════════════════════════════════════════════════════════════

_PII_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"), "[REDACTED_JWT]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"arn:aws:[a-z0-9-]+:[a-z0-9-]*:\d{12}:[\w/:-]+"), "[REDACTED_ARN]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[REDACTED_EMAIL]"),
    (re.compile(r"01[0-9][-\s]?\d{3,4}[-\s]?\d{4}"), "[REDACTED_PHONE]"),
    (re.compile(r"\bE\d{6}\b"), "[REDACTED_ID]"),
)


def mask_pii(text: str) -> str:
    """자격증명·계정 식별 정보를 마스킹한다.

    최소 여섯 가지: 사번 · 전화번호 · 이메일 · AWS 액세스 키 · JWT · AWS ARN(계정ID 포함)
    """
    masked = text
    for pattern, placeholder in _PII_PATTERNS:
        masked = pattern.sub(placeholder, masked)
    return masked


def mask_pii_deep(value):
    """딕셔너리/리스트/문자열을 재귀적으로 순회하며 문자열 값을 전부 마스킹한다.

    mask_pii()는 문자열 하나만 처리한다. HITL 승인 요청(request.args)이나
    trace/contexts처럼 자유 형식 중첩 구조 안에 PII·자격증명이 섞여 나올 수
    있는 곳에는 이걸 쓴다 — 코드 리뷰에서 이 경로들이 mask_pii()를 아예 안
    거치고 있던 걸 발견해서 추가했다.
    """
    if isinstance(value, str):
        return mask_pii(value)
    if isinstance(value, dict):
        return {k: mask_pii_deep(v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_pii_deep(v) for v in value]
    return value


# ══════════════════════════════════════════════════════════════════
# 도구 결과 소독 — 외부 데이터에 섞인 지시문을 무력화 (가드레일 규칙 4)
# ══════════════════════════════════════════════════════════════════

_TOOL_OUTPUT_SANITIZE_PATTERNS = _INJECTION_MARKERS + _ROLE_REASSIGN_PATTERNS + _JAILBREAK_PATTERNS


def sanitize_tool_output(text: str) -> str:
    """도구 결과(리소스 태그·설명 등 외부에서 채워질 수 있는 데이터)에 지시문처럼
    보이는 패턴이 섞여 있으면 무력화한다.

    input_guard()는 사용자의 최초 질문 전체를 검사해서 통째로 거부하지만, 도구
    결과는 거부할 대상이 아니라 사용자에게 보여줘야 하는 데이터다. 그래서 여기서는
    의심스러운 부분만 표시로 바꿔 무력화하고 나머지 내용은 그대로 둔다 — 이게
    SERVICE.md 가드레일 규칙 4("리소스 태그·설명 등 외부 입력의 지시문은 시스템
    지시로 취급하지 않는다")의 실제 코드 강제다. 지금 쓰는 합성 데이터엔 이런
    악성 태그가 없어서 평소엔 아무것도 안 바뀌지만, 실 서비스로 확장해 사용자가
    리소스 이름·태그를 직접 입력할 수 있게 되면 이 경로가 방어선이 된다.
    """
    sanitized = text
    for pattern in _TOOL_OUTPUT_SANITIZE_PATTERNS:
        sanitized = pattern.sub("[제거됨: 지시문으로 의심되는 내용]", sanitized)
    return sanitized


# 원칙: 차단 -> 정제 -> 검증 -> 기록. 마스킹이 로깅보다 앞이어야 로그에 원본이 안 남는다.
MIDDLEWARE_ORDER: list[str] = [
    "InputGuardMiddleware",
    "MaskingMiddleware",
    "OutputCheckMiddleware",
    "HistorySummaryMiddleware",
    "LoggingMiddleware",
]


# ══════════════════════════════════════════════════════════════════
# HITL — 도구별 위험도와 승인 필요 여부
# ══════════════════════════════════════════════════════════════════

RISK_LEVELS: dict[str, str] = {
    "get_cost_by_service": "read",
    "get_resource_utilization": "read",
    "detect_cost_anomaly": "read",
    "estimate_savings": "read",
    "list_idle_resources": "read",
    "retrieve_docs": "read",
    "send_cost_alert": "write",
    "stop_resource": "destructive",
    "resize_resource": "destructive",
}


def needs_approval(tool_name: str, args: dict) -> tuple[bool, str]:
    """이 도구 호출에 사람 승인이 필요한지 판정한다. LLM을 호출하지 않는다.

    규칙 (Day 5와 동일):
      - read        -> 승인 불필요
      - write       -> 승인 필요
      - destructive -> 승인 필요 + 이중 확인
      - 미등록 도구  -> 승인 필요 (모르는 것은 막는다)
    """
    level = RISK_LEVELS.get(tool_name)

    if level is None:
        return True, f"등록되지 않은 도구입니다: '{tool_name}'. 알 수 없는 도구는 승인이 필요합니다."
    if level == "read":
        return False, "조회 작업이라 승인 없이 자동 실행합니다."
    if level == "write":
        return True, f"'{tool_name}'은 상태를 변경하는 작업이라 승인이 필요합니다."
    return True, f"'{tool_name}'은 되돌릴 수 없는 작업입니다. 승인과 이중(double) 확인이 필요합니다."
