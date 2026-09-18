"""로컬 개발용 데모 UI — 기존 FastAPI 서버(src/app.py)를 그대로 호출한다.

이 파일은 브라우저가 아니라 이 파이썬 프로세스(Streamlit 서버)가 requests로
FastAPI(POST /query 등)를 호출하는 구조라, 브라우저의 CORS 정책이 개입하지 않는다
(src/app.py에 CORSMiddleware가 없어도 동작하는 이유). 기존 src/*.py는 전혀 건드리지
않고, 이미 있는 API 응답 모양(answer/contexts/trace/structured, pending_approval)을
그대로 화면에 옮겨 그리기만 한다. 새 백엔드 엔드포인트는 추가하지 않는다 —
대시보드/차트도 전부 기존 GET /history, GET /batch-runs 데이터로만 그린다.

라이트 테마(밝은 배경 + 짙은 텍스트, 가독성 우선) + shadcn/ui 컴포넌트(streamlit-shadcn-ui,
실제 shadcn React 컴포넌트를 Streamlit 커스텀 컴포넌트로 감싼 패키지)로 꾸민다.
shadcn 컴포넌트는 자체적으로 라이트/다크를 따라가므로(`prefers-color-scheme` 감지)
`.streamlit/config.toml`의 테마만 바꾸면 같이 밝아진다. 카드/배지/버튼/탭처럼 "껍데기"
성격의 UI는 shadcn으로, 표(히스토리·배치 이력)처럼 정렬·다운로드가 필요한 데이터
그리드는 pandas Styler + st.dataframe을 그대로 쓴다 — shadcn 쪽 테이블 컴포넌트는
그 기능이 없어서다.

질의응답 화면은 v0.dev류 분할 화면(좌: 대화, 우: 실시간 미리보기)으로 구성한다.
다만 Streamlit은 "제출(엔터) 시에만" 스크립트가 다시 실행되는 구조라, 타이핑
글자 단위로 반응하는 완전한 실시간성은 없다 — 질문을 보낼 때마다 양쪽이 같이
갱신되는 정도가 이 스택에서 가능한 현실적인 목표다.

다국어(한국어/English) 지원: 화면 라벨·버튼·안내 문구 등 "UI 껍데기"만 번역 대상이다.
에이전트의 실제 답변 내용과 히스토리 원문은 번역하지 않는다 — 백엔드(src/agent.py의
시스템 프롬프트, route_question의 한국어 키워드 매칭)가 한국어 응답을 전제로 만들어져
있어서, 화면만 영어로 바꾼다고 에이전트가 영어로 답하지는 않는다(이 한계는 README/
UI_SPEC.md에도 명시). "자주 묻는 질문" 버튼도 라벨만 번역하고 실제로 전송되는 질문
텍스트는 한국어 그대로 유지한다 — 그래야 route_question 라우팅이 깨지지 않는다.

실행:
    uvicorn src.app:app --reload --port 8000   (터미널 1 — 기존 서버)
    streamlit run ui/streamlit_app.py          (터미널 2 — 이 UI)

프로덕션 배포용이 아니다 — 인증이 없고 Streamlit 자체가 로컬 데모/내부 도구 용도다.
"""

from __future__ import annotations

import html
import re
import time
import uuid
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
import streamlit as st
import streamlit_shadcn_ui as ui

LANG_KEYS = ["ko", "en"]
LANG_DISPLAY = {"ko": "한국어", "en": "English"}

# 화면에 보이는 텍스트만 담는다(코드 주석/독스트링은 개발자용이라 번역 대상이 아님,
# CLAUDE.md의 "한국어 docstring" 관례와 같은 이유로 반대로 여기는 UI 텍스트만 다룬다).
# 에이전트 응답 원문·히스토리 데이터는 번역하지 않는다 — 위 모듈 독스트링 참고.
T: dict[str, dict[str, str]] = {
    "ko": {
        "page_title": "멀티클라우드 비용 에이전트",
        "app_name": "☁️ 비용 브리핑",
        "app_tagline": "오늘 아침, 세 클라우드 비용 상태를 한눈에",
        "lang_label": "언어",
        "settings_expander": "⚙️ 설정",
        "server_url_label": "서버 주소",
        "team_label": "요청자 팀 (authz)",
        "team_none": "제한 없음 (플랫폼팀)",
        "stat_questions_inline": "질문 {n}개",
        "stat_pending_inline": "🔒 승인 대기 중",
        "thread_id_caption": "thread_id: `{tid}…`",
        "new_chat_btn": "🔄 새 대화 시작",
        "resume_section_title": "📂 지난 대화 이어가기",
        "resume_offline_hint": "서버 연결 후 이용 가능합니다.",
        "resume_fetch_failed": "불러오기 실패: {err}",
        "resume_no_threads": "이어갈 만한 지난 대화가 없습니다.",
        "resume_select_label": "대화 선택",
        "resume_btn": "↩️ 이어서 대화하기",
        "resume_toast": "💬 이전 대화 {n}건을 불러왔습니다",
        "resume_pending_notice": (
            "이 대화는 마지막에 승인 대기 상태로 끝났습니다 — 그 시점의 정확한 도구/인자는 "
            "히스토리에 저장되지 않아 화면에 복원할 수 없습니다. 새 질문을 보내면 그래프가 "
            "예상과 다르게 동작할 수 있습니다."
        ),
        "nav_dashboard": "📊 대시보드",
        "nav_chat": "💬 질의응답",
        "nav_approve": "🔒 승인 대기",
        "nav_history": "🕓 히스토리",
        "nav_batch": "📈 배치 이력",
        "dash_offline_title": "서버에 연결할 수 없습니다",
        "dash_offline_desc": "대시보드를 채울 수 없습니다.",
        "dash_greeting": "☀️ 좋은 아침이에요 — 오늘의 비용 브리핑입니다",
        "dash_greeting_sub": "지난 배치 결과를 짧게 정리해 드릴게요.",
        "dash_window_caption": "배치 조회 기간",
        "window_6h": "최근 6시간",
        "window_24h": "최근 24시간",
        "window_3d": "최근 3일",
        "window_7d": "최근 7일",
        "window_all": "전체(최근 200건)",
        "dash_anomaly_alert_title": "😮 최근 배치에서 이상 신호 {n}건을 발견했어요",
        "dash_anomaly_alert_desc": "'{tab}' 화면에서 자세히 살펴보세요.",
        "dash_provider_note": "{provider}에서 이상 신호 {n}건을 발견했어요.",
        "dash_provider_calm": "{provider}는 평온해요 — 이상 신호가 없어요.",
        "dash_metric_recent_anomaly": "{provider} 최근 이상탐지",
        "dash_metric_value": "{n}건",
        "dash_metric_delta_check": "확인 필요",
        "dash_popover_label": "🔍 상세 보기 (클릭)",
        "dash_chart_subheader": "최근 배치 실행별 발견 건수",
        "dash_no_batch_title": "선택한 기간에 배치 실행 이력이 없습니다",
        "dash_no_batch_desc": "조회 기간을 늘려보거나, 서버가 뜬 지 얼마 안 됐을 수 있습니다.",
        "dash_total_history": "전체 대화 기록",
        "dash_pending_count": "승인 대기 중",
        "dash_blocked_count": "차단된 요청",
        "resume_alert_title": "↩️ 이어받은 대화 안내",
        "chat_pending_alert_title": "승인 대기 중인 요청이 있습니다",
        "chat_pending_alert_desc": "'{tab}' 화면에서 처리해야 다음 질문에 이어갈 수 있습니다.",
        "quick_questions_caption": "자주 묻는 질문",
        "chat_export_btn": "💾 대화 내보내기",
        "chat_input_placeholder": "질문을 입력하세요 (예: 이번 달 AWS EC2 비용 총액이 얼마야?)",
        "chat_input_disabled_placeholder": "답변을 기다리고 있어요...",
        "chat_spinner": "에이전트가 답변을 준비하고 있어요... (처음 질문은 서버가 깨어나는 중이라 조금 오래 걸릴 수 있어요)",
        "queued_caption": "⏳ 이전 질문 답변을 기다린 뒤 순서대로 처리됩니다.",
        "chat_pending_answer": "🔒 실행 승인이 필요합니다 — '{tab}' 화면에서 처리하세요.",
        "confidence_label": "확신도",
        "followup_label": "추가 확인 필요",
        "yes": "예",
        "no": "아니오",
        "conf_high": "높음",
        "conf_medium": "보통",
        "conf_low": "낮음",
        "conf_badge_high": "믿을만해요 ✅",
        "conf_badge_medium": "어느 정도 맞을 거예요",
        "conf_badge_low": "다시 확인해 보세요 ⚠️",
        "preview_subheader": "🔍 실시간 미리보기",
        "preview_empty_title": "아직 대화가 없습니다",
        "preview_empty_desc": "왼쪽에서 질문을 보내면 이 자리에 구조화 요약·출처·도구 호출 내역이 실시간으로 채워집니다.",
        "preview_pending_title": "답변을 기다리는 중입니다…",
        "preview_elapsed": "⏱ 응답 시간 {s}초",
        "elapsed_inline": "⏱ {s}초",
        "active_model_inline": "🤖 {model}",
        "preview_no_structured_title": "이 답변엔 구조화 요약이 없습니다",
        "preview_key_numbers_title": "핵심 수치",
        "preview_sources_title": "📄 출처 문서 ({n}건)",
        "preview_trace_caption": "🛠️ 도구 호출 트레이스 ({n}건, 호출 순서대로)",
        "quick_cost": "💰 이번 달 비용",
        "quick_idle": "🟡 유휴 리소스",
        "quick_anomaly": "📈 이상 탐지",
        "quick_budget": "📋 예산 현황",
        "approve_subheader": "실행 승인 대기",
        "approve_empty_title": "대기 중인 승인 요청이 없습니다",
        "approve_warn_title": "도구 `{tool}` 실행을 승인하시겠습니까?",
        "approve_yes": "✅ 승인",
        "approve_no": "❌ 거절",
        "approve_done_toast": "승인 완료",
        "approve_rejected_toast": "승인 거절",
        "history_subheader": "질문-답변 히스토리",
        "history_thread_filter": "thread_id로 필터 (비우면 전체)",
        "history_limit_label": "최대 건수",
        "refresh_btn": "🔄 조회",
        "history_keyword_label": "🔍 질문/답변 키워드 검색 (조회된 결과 안에서 클라이언트 측 필터링)",
        "history_no_match": "'{kw}'와 일치하는 기록이 없습니다.",
        "no_records": "기록이 없습니다.",
        "count_caption": "{n}건",
        "count_caption_keyword": "{n}건 (검색어 '{kw}' 적용)",
        "csv_export_btn": "⬇️ CSV로 내보내기",
        "batch_subheader": "이상탐지 배치 실행 이력",
        "batch_caption": "서버가 떠 있는 동안 src/batch.py가 주기적으로 자동 실행한 기록입니다 (SERVICE.md §5).",
        "err_conn": "서버({url})에 연결할 수 없습니다. `uvicorn src.app:app --port 8000`을 먼저 실행하세요.",
        "err_timeout": "요청이 120초 안에 끝나지 않았습니다 (최초 요청은 MCP 서버 기동으로 오래 걸릴 수 있음).",
        "err_http": "서버 오류: {exc}",
    },
    "en": {
        "page_title": "Multicloud Cost Agent",
        "app_name": "☁️ Cost Briefing",
        "app_tagline": "A quick look at your three clouds' costs, every morning",
        "lang_label": "Language",
        "settings_expander": "⚙️ Settings",
        "server_url_label": "Server URL",
        "team_label": "Requester Team (authz)",
        "team_none": "Unrestricted (Platform Team)",
        "stat_questions_inline": "{n} question(s)",
        "stat_pending_inline": "🔒 Pending approval",
        "thread_id_caption": "thread_id: `{tid}…`",
        "new_chat_btn": "🔄 New Conversation",
        "resume_section_title": "📂 Resume Past Conversation",
        "resume_offline_hint": "Available once connected to the server.",
        "resume_fetch_failed": "Failed to load: {err}",
        "resume_no_threads": "No past conversations to resume.",
        "resume_select_label": "Select conversation",
        "resume_btn": "↩️ Resume Conversation",
        "resume_toast": "💬 Loaded {n} previous message(s)",
        "resume_pending_notice": (
            "This conversation last ended in a pending-approval state — the exact tool/arguments "
            "from that moment weren't saved in history and can't be restored. Sending a new "
            "question may make the graph behave unexpectedly."
        ),
        "nav_dashboard": "📊 Dashboard",
        "nav_chat": "💬 Chat",
        "nav_approve": "🔒 Approvals",
        "nav_history": "🕓 History",
        "nav_batch": "📈 Batch Runs",
        "dash_offline_title": "Can't connect to the server",
        "dash_offline_desc": "The dashboard can't be populated.",
        "dash_greeting": "☀️ Good morning — here's today's cost briefing",
        "dash_greeting_sub": "Here's a quick rundown of the latest batch.",
        "dash_window_caption": "Batch lookback window",
        "window_6h": "Last 6 hours",
        "window_24h": "Last 24 hours",
        "window_3d": "Last 3 days",
        "window_7d": "Last 7 days",
        "window_all": "All (last 200)",
        "dash_anomaly_alert_title": "😮 Found {n} unusual cost signal(s) in the latest batch",
        "dash_anomaly_alert_desc": "Take a closer look on the '{tab}' screen.",
        "dash_provider_note": "Found {n} unusual signal(s) for {provider}.",
        "dash_provider_calm": "{provider} is calm — no unusual signals.",
        "dash_metric_recent_anomaly": "{provider} Recent Anomalies",
        "dash_metric_value": "{n}",
        "dash_metric_delta_check": "Needs review",
        "dash_popover_label": "🔍 View details (click)",
        "dash_chart_subheader": "Findings per Recent Batch Run",
        "dash_no_batch_title": "No batch runs in the selected window",
        "dash_no_batch_desc": "Try a wider window, or the server may have just started.",
        "dash_total_history": "Total Conversations",
        "dash_pending_count": "Pending Approvals",
        "dash_blocked_count": "Blocked Requests",
        "resume_alert_title": "↩️ Resumed conversation notice",
        "chat_pending_alert_title": "There's a pending approval request",
        "chat_pending_alert_desc": "Handle it on the '{tab}' screen before asking another question.",
        "quick_questions_caption": "Quick questions",
        "chat_export_btn": "💾 Export conversation",
        "chat_input_placeholder": "Ask a question (e.g. What's this month's total AWS EC2 cost?)",
        "chat_input_disabled_placeholder": "Waiting for a response...",
        "chat_spinner": "The agent is preparing an answer... (the first question can take a bit while the server wakes up)",
        "queued_caption": "⏳ Waiting for the previous answer — questions are processed in order.",
        "chat_pending_answer": "🔒 This action needs approval — handle it on the '{tab}' screen.",
        "confidence_label": "Confidence",
        "followup_label": "Needs follow-up",
        "yes": "Yes",
        "no": "No",
        "conf_high": "high",
        "conf_medium": "medium",
        "conf_low": "low",
        "conf_badge_high": "Trustworthy ✅",
        "conf_badge_medium": "Reasonably confident",
        "conf_badge_low": "Worth double-checking ⚠️",
        "preview_subheader": "🔍 Live Preview",
        "preview_empty_title": "No conversation yet",
        "preview_empty_desc": "Send a question on the left and the structured summary, sources, and tool trace will appear here.",
        "preview_pending_title": "Waiting for the answer…",
        "preview_elapsed": "⏱ Response time {s}s",
        "elapsed_inline": "⏱ {s}s",
        "active_model_inline": "🤖 {model}",
        "preview_no_structured_title": "This answer has no structured summary",
        "preview_key_numbers_title": "Key Numbers",
        "preview_sources_title": "📄 Source Documents ({n})",
        "preview_trace_caption": "🛠️ Tool Call Trace ({n}, in call order)",
        "quick_cost": "💰 This Month's Cost",
        "quick_idle": "🟡 Idle Resources",
        "quick_anomaly": "📈 Anomaly Detection",
        "quick_budget": "📋 Budget Status",
        "approve_subheader": "Pending Execution Approval",
        "approve_empty_title": "No pending approval requests",
        "approve_warn_title": "Approve running the tool `{tool}`?",
        "approve_yes": "✅ Approve",
        "approve_no": "❌ Reject",
        "approve_done_toast": "Approved",
        "approve_rejected_toast": "Rejected",
        "history_subheader": "Question-Answer History",
        "history_thread_filter": "Filter by thread_id (leave empty for all)",
        "history_limit_label": "Max records",
        "refresh_btn": "🔄 Refresh",
        "history_keyword_label": "🔍 Search question/answer keyword (client-side filter on fetched results)",
        "history_no_match": "No records match '{kw}'.",
        "no_records": "No records.",
        "count_caption": "{n} record(s)",
        "count_caption_keyword": "{n} record(s) (filtered by '{kw}')",
        "csv_export_btn": "⬇️ Export CSV",
        "batch_subheader": "Anomaly Detection Batch Run History",
        "batch_caption": "Recorded automatically by src/batch.py while the server is running (SERVICE.md §5).",
        "err_conn": "Can't connect to the server ({url}). Run `uvicorn src.app:app --port 8000` first.",
        "err_timeout": "The request didn't finish within 120s (the first request can be slow due to MCP server startup).",
        "err_http": "Server error: {exc}",
    },
}


def _t(key: str, **kwargs) -> str:
    lang = st.session_state.get("lang", "ko")
    text = T.get(lang, T["ko"]).get(key, key)
    return text.format(**kwargs) if kwargs else text


st.session_state.setdefault("lang", "ko")  # set_page_config보다 먼저 있어야 page_title 번역에 쓸 수 있다
st.set_page_config(page_title=_t("page_title"), page_icon="☁️", layout="wide")

TEAM_KEYS = ["none", "team-a", "team-b", "team-c"]
TEAM_VALUES = {"none": None, "team-a": "team-a", "team-b": "team-b", "team-c": "team-c"}

# 탭 값 자체(키)는 고정 문자열로 두고, 화면에 보이는 라벨만 ui.tabs의 format_func로
# 매번 새로 계산한다(미확인 배치 배지 숫자나 언어가 바뀌어도 선택된 탭이 안 풀리게
# 하려고) — 라벨 문자열 자체를 값으로 쓰면 라벨이 바뀔 때마다 선택 상태가 리셋된다.
NAV_KEYS = ["dashboard", "chat", "approve", "history", "batch"]

BATCH_WINDOW_KEYS = ["6h", "24h", "3d", "7d", "all"]
BATCH_WINDOW_HOURS: dict[str, int | None] = {"6h": 6, "24h": 24, "3d": 24 * 3, "7d": 24 * 7, "all": None}

# (표시 라벨 번역 키, 실제로 전송되는 질문 — 한국어 고정, route_question이 한국어
# 키워드로 라우팅하므로 번역하면 라우팅이 깨진다)
QUICK_QUESTIONS = [
    ("quick_cost", "3개 클라우드 이번 달 비용 합쳐서 얼마야?"),
    ("quick_idle", "요즘 유휴 상태인 리소스 있어?"),
    ("quick_anomaly", "어제 비용에 이상한 변화 있었어?"),
    ("quick_budget", "우리 팀 예산 얼마나 썼어?"),
]

STATUS_ICON = {"answered": "✅", "pending_approval": "🔒", "blocked": "🚫", "error": "⚠️"}
# 배지 배경색 — 검은 텍스트(.pill)와 대비가 뚜렷하도록 채도 높은 값을 그대로 쓴다.
# 페이지가 밝든 어둡든 배지 자체가 자기 배경을 갖고 있어 가독성에 영향이 없다.
CONFIDENCE_COLOR = {"high": "#22c55e", "medium": "#f59e0b", "low": "#ef4444"}
# st.dataframe은 캔버스 기반 렌더러라 색상 문자열을 직접 파싱해야 한다 — CSS
# color-mix()/변수는 브라우저 DOM에서만 계산되고 여기선 안 먹으므로 rgba()를 그대로 준다.
# 밝은 배경 위에서 옅은 색 tint로 보이도록(엑셀 조건부 서식과 비슷한 느낌) 불투명도를 낮췄다.
STATUS_BG = {
    "answered": "background-color: rgba(34, 197, 94, 0.16)",
    "pending_approval": "background-color: rgba(245, 158, 11, 0.18)",
    "blocked": "background-color: rgba(239, 68, 68, 0.16)",
    "error": "background-color: rgba(239, 68, 68, 0.16)",
}

# detect_cost_anomaly()가 만드는 한 줄 형식(tools.py)을 그대로 파싱한다:
# "- {resource_id} (계정: {account_id}, {date}): ${cost} (직전 {N}일 평균 ${mean} 대비 z-score {z})"
_ANOMALY_LINE = re.compile(
    r"^-\s*(?P<rid>\S+)\s*\(계정:\s*(?P<account>[\w-]+),\s*(?P<date>\d{4}-\d{2}-\d{2})\):\s*"
    r"\$(?P<cost>[\d,.]+)\s*\(직전\s*(?P<window>\d+)일\s*평균\s*\$(?P<mean>[\d,.]+)\s*대비\s*z-score\s*(?P<z>[\d.]+)\)"
)


def _format_anomaly_popup(detail: str) -> str:
    """batch_runs의 detail 원문을 파싱해 리스트 형태 문자열로 바꾼다.

    ui.popover의 content는 순수 문자열 하나만 받는다(구조화된 자식 엘리먼트를
    못 넣음) — 그래서 "리스트"는 실제 리스트 위젯이 아니라 항목마다 줄바꿈 +
    불릿(•)으로 정리한 텍스트다. 파싱에 실패하는 줄(예: 이상 없음 안내 문구)이
    하나라도 있으면 원문을 그대로 보여준다 — 무리하게 파싱해서 정보를 잘라먹지
    않기 위함. detail 자체(리소스ID·수치)는 번역 대상이 아니다 — 백엔드 원문이다.
    """
    lines = [line.strip() for line in detail.splitlines() if line.strip()]
    items = [m.groupdict() for m in (_ANOMALY_LINE.match(line) for line in lines) if m]
    if len(items) != len([line for line in lines if line.startswith("-")]):
        return detail  # 일부라도 파싱 실패 -> 원문 그대로(안전한 폴백)
    if not items:
        return detail  # 애초에 "- "로 시작하는 항목이 없음(이상 없음 안내 등)
    return "\n".join(
        f"• {it['date']} · {it['rid']} (계정 {it['account']}) — "
        f"${it['cost']} (직전 {it['window']}일 평균 ${it['mean']} 대비 z-score {it['z']})"
        for it in items
    )

# shadcn 컴포넌트는 격리된 shadow DOM에서 그려져서(isolate_styles=True) 이 CSS가 안
# 닿는다 — 카드/배지/버튼 색상은 .streamlit/config.toml의 테마 토큰으로만 바뀐다.
# 여기서는 순수 Streamlit 네이티브 엘리먼트(제목, 챗 말풍선, 캡션)에만 "아침 브리핑"
# 방향의 타이포(Libre Franklin 제목 + Karla 본문)와 카드형 말풍선을 얹는다.
CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Libre+Franklin:wght@600;700&family=Karla:wght@400;500;700&family=IBM+Plex+Mono:wght@500;600&display=swap');
/* 2.6rem — 첫 제목("비용 브리핑")의 위쪽이 살짝 잘려 보이는 문제 리포트로 올림.
   Libre Franklin bold + 이모지(☁️) 조합이 기본 줄 높이보다 위로 튀어나와서, 예전
   padding-top(1.6rem)에서는 Streamlit 상단 툴바 바로 아래에 살짝 가려졌다. */
.block-container { padding-top: 2.6rem; }
/* .stApp에만 걸고 상속으로 내려보낸다 — 예전엔 .stApp div, .stApp span까지 직접
   지정해서, Streamlit이 사이드바 접기/펴기 화살표 같은 아이콘을 그리는 데 쓰는
   아이콘 폰트(Material Symbols) span까지 Karla로 덮어써 버렸다. 그 아이콘은
   ligature(글자 그대로의 텍스트, 예: "keyboard_double_arrow_left")를 아이콘
   폰트로 렌더링해서 화살표 모양을 만드는 방식이라, 폰트가 바뀌면 그 글자가 아이콘
   대신 텍스트 그대로 보인다 — 사이드바에 "Keyboard_..."가 보이던 원인. .stApp
   하나에만 걸면 상속 특이성이 낮아서 Streamlit 자체 아이콘 규칙이 정상적으로
   우선한다. */
.stApp { font-family: 'Karla', sans-serif; }
[data-testid="stIconMaterial"] { font-family: 'Material Symbols Rounded', 'Material Icons', sans-serif !important; }
h1, h2, h3, .stApp [data-testid="stHeading"] {
    font-family: 'Libre Franklin', sans-serif !important;
    font-weight: 700 !important;
    line-height: 1.35 !important;
    padding-top: 0.15em;
}
.pill {
    display: inline-block;
    padding: 0.12rem 0.65rem;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 700;
    color: #09090b;
    font-family: 'Karla', sans-serif;
}
[data-testid="stChatMessage"] {
    border-radius: 18px;
    border: 1px solid #e2e6dc;
    box-shadow: 0 6px 16px -12px rgba(35, 41, 32, 0.4);
}
/* 대시보드의 프로바이더 카드·경고 배너 — shadcn(ui.metric_card/ui.alert)은 shadow
   DOM이라 모양을 못 바꾸므로, 이 두 요소만 순수 HTML(st.markdown)로 직접 그린다. */
.brief-card {
    background: #ffffff;
    border-radius: 16px;
    padding: 0.95rem 1.1rem;
    box-shadow: 0 6px 18px -12px rgba(35, 41, 32, 0.35);
    display: flex;
    gap: 0.8rem;
    align-items: flex-start;
    margin-bottom: 0.6rem;
}
.brief-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin-top: 0.4rem;
    flex: none;
}
.brief-card .brief-provider { font-weight: 700; font-size: 0.8rem; margin-bottom: 0.2rem; }
.brief-card .brief-note { font-size: 0.9rem; line-height: 1.5; margin: 0; }
.brief-card .brief-count {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem;
    color: #6c7263;
    margin-top: 0.35rem;
}
.brief-alert {
    background: #fdf1ea;
    border-left: 4px solid #c1483f;
    border-radius: 10px;
    padding: 0.8rem 1rem;
    margin-bottom: 0.9rem;
}
.brief-alert .brief-alert-title { font-weight: 700; margin: 0 0 0.25rem; }
.brief-alert .brief-alert-desc { font-size: 0.85rem; color: #6c7263; margin: 0; }
.brief-spark-days {
    display: flex;
    justify-content: space-between;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.68rem;
    color: #6c7263;
    margin-top: 0.2rem;
}
.pill-row { display: flex; gap: 0.6rem; flex-wrap: wrap; margin-top: 0.4rem; }
.pill-stat {
    background: #ffffff;
    border-radius: 999px;
    padding: 0.45rem 0.9rem;
    font-size: 0.82rem;
    color: #232920;
    box-shadow: 0 4px 10px -8px rgba(35, 41, 32, 0.4);
}
.pill-stat b { font-family: 'IBM Plex Mono', monospace; margin-left: 0.35rem; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def _pill(text: str, color: str) -> str:
    return f'<span class="pill" style="background:{color}">{text}</span>'


def _stat_pill_html(label: str, value: object) -> str:
    return f'<span class="pill-stat">{html.escape(label)}<b>{html.escape(str(value))}</b></span>'


# "아침 브리핑" 방향 — 프로바이더 카드/경고 배너는 shadcn(ui.metric_card/ui.alert)이
# 격리된 shadow DOM이라 모양(둥근 정도·그림자·아이콘 배치)을 못 바꾼다. 그래서 이
# 두 요소만 순수 HTML(st.markdown)로 직접 그려서 CUSTOM_CSS의 .brief-* 클래스가
# 먹히게 한다. provider/count_label/title/desc는 전부 고정된 provider 목록이나
# _t() 템플릿 포맷 결과라 사용자 입력이 섞일 일이 없지만, HTML로 그대로 꽂아 넣는
# 문자열이라 html.escape()로 한 번 더 방어한다.
def _brief_card_html(provider: str, note: str, count_label: str, ok: bool) -> str:
    dot_color = "#4f9d69" if ok else "#c1483f"
    return (
        '<div class="brief-card">'
        f'<span class="brief-dot" style="background:{dot_color}"></span>'
        '<div>'
        f'<div class="brief-provider">{html.escape(provider)}</div>'
        f'<p class="brief-note">{html.escape(note)}</p>'
        f'<div class="brief-count">{html.escape(count_label)}</div>'
        "</div></div>"
    )


def _brief_alert_html(title: str, desc: str) -> str:
    return (
        '<div class="brief-alert">'
        f'<p class="brief-alert-title">{html.escape(title)}</p>'
        f'<p class="brief-alert-desc">{html.escape(desc)}</p>'
        "</div>"
    )


def _sparkline_svg(values: list[int], color: str = "#cf8a2e") -> str:
    """일별 총 findings_count로 목업(E)의 골드색 둥근-끝 라인 스파크라인을 그린다.

    st.bar_chart(Vega-Lite)는 provider별 막대라 정보량은 더 많았지만, provider별
    최신 현황은 바로 위 브리핑 카드에서 이미 보여주므로 여기서는 "전체 추이 한눈에"
    용도로 날짜별 합계 하나만 본다. 값이 1개뿐이면 점만 찍는다(선을 그릴 좌표가
    2개는 있어야 하는데 데이터가 배치 1회뿐인 경우 — 서버 막 기동 시 흔함).
    """
    width, height, pad = 280, 64, 10
    n = len(values)
    vmax = max(values) if values else 0

    def _y(v: int) -> float:
        if vmax <= 0:
            return height - pad
        return height - pad - (v / vmax) * (height - 2 * pad)

    if n == 0:
        return ""
    if n == 1:
        cy = _y(values[0])
        return (
            f'<svg viewBox="0 0 {width} {height}" style="display:block;width:100%;height:{height}px" '
            f'role="img" aria-label="최근 배치 findings 1건"><circle cx="{width / 2:.1f}" cy="{cy:.1f}" '
            f'r="4" fill="{color}"/></svg>'
        )
    step = (width - 2 * pad) / (n - 1)
    points = " ".join(f"{pad + i * step:.1f},{_y(v):.1f}" for i, v in enumerate(values))
    last_x, last_y = pad + (n - 1) * step, _y(values[-1])
    label_x = max(last_x - 22, 0.0)
    label_y = max(last_y - 10, 10.0)
    return (
        f'<svg viewBox="0 0 {width} {height}" style="display:block;width:100%;height:{height}px" '
        f'role="img" aria-label="최근 {n}일 findings 추이, 마지막 값 {values[-1]}건">'
        f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="3" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="4.5" fill="{color}"/>'
        f'<text x="{label_x:.1f}" y="{label_y:.1f}" font-size="11" '
        f'font-family="IBM Plex Mono, monospace" fill="{color}">{values[-1]}</text>'
        "</svg>"
    )


def _init_state() -> None:
    st.session_state.setdefault("base_url", "http://localhost:8000")
    st.session_state.setdefault("thread_id", str(uuid.uuid4()))
    st.session_state.setdefault("chat_log", [])  # [{question, response}]
    st.session_state.setdefault("pending_request", None)  # {"tool","args","reason"} or None
    st.session_state.setdefault("pending_question", None)  # 퀵 질문 버튼이 예약한 질문
    st.session_state.setdefault("resume_notice", None)  # 지난 대화 이어가기 시 보여줄 경고 문구
    st.session_state.setdefault("last_seen_batch_at", None)  # "배치 이력" 탭을 마지막으로 본 시각(ISO) — 미확인 배지 계산용
    st.session_state.setdefault("active_nav", "dashboard")  # 현재 선택된 화면 — "controlled" 컴포넌트라 코드에서 값을 강제할 수 있다
    # ui.tabs가 내부적으로 "지난 렌더에서 넘긴 value의 fingerprint"만 비교해서 강제
    # 전환 여부를 판단하는데, 우리 쪽 value=는 항상 "이번 클릭을 반영하기 전" 값을
    # 넘기는 구조라 한 렌더 지연이 생긴다. 두 번째 강제 전환의 목표값이 그 지연된
    # 값과 우연히 같으면(예: "chat"->직접 클릭으로 "dashboard"->다시 "chat" 강제)
    # 컴포넌트가 "기본값이 안 바뀌었다"고 오판해 사용자가 직접 클릭해 둔 값을 그대로
    # 돌려버린다 — 강제 전환 버튼(새 대화 시작/이어서 대화하기)을 누를 때마다 이
    # epoch를 올려서 위젯 key를 바꾸면 매번 새 mount로 시작해 이 문제를 피한다.
    st.session_state.setdefault("nav_epoch", 0)
    st.session_state.setdefault("is_answering", False)  # 지금 처리 중인 질문이 있는지 — 동시에 두 번째 요청을 못 보내게 막는 데 쓴다


def _api(method: str, path: str, **kwargs):
    """공통 호출 래퍼 — 서버 미기동/타임아웃을 화면에 바로 보여준다.

    그래프 콜드 스타트(MCP 서버 3개 기동 + RAG 임베딩)가 최초 요청에서 수십 초 걸릴
    수 있어 timeout을 넉넉히 잡는다 (README 실행 로그 기준 15초 내외 관측됨).
    """
    url = st.session_state.base_url.rstrip("/") + path
    try:
        resp = requests.request(method, url, timeout=120, **kwargs)
        resp.raise_for_status()
        return resp.json(), None
    except requests.exceptions.ConnectionError:
        return None, _t("err_conn", url=url)
    except requests.exceptions.Timeout:
        return None, _t("err_timeout")
    except requests.exceptions.HTTPError as exc:
        return None, _t("err_http", exc=exc)


@st.cache_data(ttl=8, show_spinner=False)
def _ping(base_url: str) -> bool:
    try:
        requests.get(base_url.rstrip("/") + "/history", params={"limit": 1}, timeout=3)
        return True
    except requests.exceptions.RequestException:
        return False


@st.cache_data(ttl=8, show_spinner=False)
def _fetch(base_url: str, path: str, limit: int) -> tuple[list[dict], str | None]:
    try:
        resp = requests.get(base_url.rstrip("/") + path, params={"limit": limit}, timeout=10)
        resp.raise_for_status()
        return resp.json().get("items", []), None
    except requests.exceptions.RequestException as exc:
        return [], str(exc)


@st.cache_data(ttl=8, show_spinner=False)
def _fetch_page(base_url: str, path: str, params: tuple) -> tuple[dict | None, str | None]:
    """히스토리/배치 이력 화면 조회를 짧게 캐싱한다.

    이 두 화면은 진입 즉시 전체 조회를 하고, 필터 위젯을 프래그먼트로 감싸놨어도
    같은 화면 안의 다른 위젯(검색어, 최대 건수 등)을 바꾸면 그 프래그먼트가 다시
    실행되면서 조회 조건이 그대로인데도 매번 백엔드를 다시 불렀다 — `_ping`/`_fetch`
    처럼 캐싱해서 TTL(8초) 안에서는 같은 조건이면 네트워크 호출 없이 캐시를 쓴다.

    에러는 여기서 `_t()`로 번역한 문구를 만들지 않고 종류만 돌려준다 — 번역된
    문자열을 그대로 캐싱하면 캐시가 살아있는 동안 언어를 바꿔도 예전 언어로 굳은
    에러 문구가 나온다. 실제 번역은 `_fetch_page_localized()`가 매번 새로 한다.
    `params`는 dict가 아니라 정렬된 (key, value) 튜플로 받는다 — st.cache_data가
    인자를 캐시 키로 해싱하는데, dict는 호출부마다 새로 만들어지는 객체라 매번
    같은 값이어도 다른 것으로 오인되지 않도록 튜플로 정규화해서 넘긴다.
    """
    url = base_url.rstrip("/") + path
    try:
        resp = requests.get(url, params=dict(params), timeout=120)
        resp.raise_for_status()
        return resp.json(), None
    except requests.exceptions.ConnectionError:
        return None, "conn"
    except requests.exceptions.Timeout:
        return None, "timeout"
    except requests.exceptions.HTTPError as exc:
        return None, f"http:{exc}"


def _fetch_page_localized(base_url: str, path: str, **params) -> tuple[dict | None, str | None]:
    """_fetch_page()를 부르고 에러 종류를 현재 언어로 번역해서 돌려준다."""
    data, err_kind = _fetch_page(base_url, path, tuple(sorted(params.items())))
    if err_kind is None:
        return data, None
    if err_kind == "conn":
        return None, _t("err_conn", url=base_url.rstrip("/") + path)
    if err_kind == "timeout":
        return None, _t("err_timeout")
    return None, _t("err_http", exc=err_kind[len("http:"):])


@st.cache_data(ttl=8, show_spinner=False)
def _recent_threads(base_url: str, scan_limit: int = 200, max_threads: int = 15) -> tuple[list[dict], str | None]:
    """최근 활동한 대화 스레드 목록을 만든다 (사이드바 '지난 대화 이어가기'용).

    GET /history는 thread_id 단위 요약을 안 주므로, 최근 scan_limit건을 가져와
    thread_id별로 묶는다. /history가 최신순(DESC)이라 한 thread_id를 처음 만나는
    지점이 그 스레드의 가장 최근 메시지다.
    """
    items, err = _fetch(base_url, "/history", scan_limit)
    if err:
        return [], err
    seen: dict[str, dict] = {}
    order: list[str] = []
    for row in items:
        tid = row["thread_id"]
        if tid not in seen:
            seen[tid] = {
                "thread_id": tid,
                "last_question": row["question"],
                "last_status": row["status"],
                "last_created_at": row["created_at"],
            }
            order.append(tid)
    return [seen[t] for t in order[:max_threads]], None


def _thread_label(t: dict) -> str:
    # 과거 질문 내용(t["last_question"])은 실제 대화 원문이라 번역 대상이 아니다.
    icon = STATUS_ICON.get(t["last_status"], "💬")
    when = t["last_created_at"][:16].replace("T", " ")
    q = t["last_question"]
    q = (q[:26] + "…") if len(q) > 26 else q
    return f"{icon} {when} · {q}"


def _resume_thread(thread_id: str) -> None:
    """과거 thread_id의 대화 이력을 불러와 현재 세션의 chat_log로 복원한다.

    이 스레드의 그래프 상태(data/checkpoints.db)는 서버가 이미 영구 보관하고 있어서
    ── 같은 thread_id로 새 질문을 보내는 것 자체가 이미 지원되는 멀티턴 이어가기
    메커니즘이다(tests/test_regression.py의 test_multiturn_reroutes_on_new_question).
    여기서는 그 thread_id를 세션에 다시 세팅하고, 화면에 보일 과거 대화 말풍선만
    GET /history로 재구성한다 — contexts/trace/structured는 history.db에 저장되지
    않아 복원 대상이 아니다(요약된 answer 텍스트만 복원됨).
    """
    data, err = _api("GET", "/history", params={"thread_id": thread_id, "limit": 200})
    if err:
        st.error(err)
        return
    items = list(reversed(data.get("items", [])))  # 최신순 -> 시간순
    chat_log = []
    for row in items:
        answer = row["answer"]
        icon = STATUS_ICON.get(row["status"])
        if icon and row["status"] != "answered":
            answer = f"{icon} {answer}"
        chat_log.append({"question": row["question"], "response": {"answer": answer}})

    st.session_state.thread_id = thread_id
    st.session_state.chat_log = chat_log
    st.session_state.pending_request = None
    last_status = items[-1]["status"] if items else None
    st.session_state.resume_notice = _t("resume_pending_notice") if last_status == "pending_approval" else None
    st.toast(_t("resume_toast", n=len(chat_log)), icon="↩️")


def _chat_transcript_md() -> str:
    """지금 세션의 chat_log를 마크다운 텍스트로 직렬화한다 (내보내기용). 대화 원문은 번역하지 않는다."""
    lines = [
        "# Chat Transcript" if st.session_state.get("lang") == "en" else "# 대화 기록",
        f"- thread_id: `{st.session_state.thread_id}`",
        f"- {'Exported at' if st.session_state.get('lang') == 'en' else '내보낸 시각'}: "
        f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC",
        "",
    ]
    for turn in st.session_state.chat_log:
        lines.append(f"## 🧑‍💻 {turn['question']}")
        resp = turn.get("response") or {}
        lines.append(resp.get("answer") or "*(pending)*")
        lines.append("")
    return "\n".join(lines)


def _queue_question(question: str) -> None:
    """질문을 즉시 chat_log에 "답변 대기" 상태로 얹는다 — API 호출은 아직 안 한다.

    질문 제출 -> 곧바로 rerun() -> 이번 rerun에서는 네트워크 호출이 없어 빠르게
    끝나서 사용자 질문 말풍선이 먼저 화면에 뜬다. 실제 API 호출(느림, 수십 초까지도
    걸림)은 이 턴을 렌더링하는 시점(_fill_pending_turn)으로 미룬다 — 그래야 "질문은
    바로 보이고 답변만 로딩 표시 후 채워지는" 흐름이 된다(질문+답변이 한꺼번에
    나타나던 이전 방식과의 차이).
    """
    st.session_state.chat_log.append({"question": question, "response": None})


def _fill_pending_turn(turn: dict) -> None:
    """response가 None인 턴(_queue_question이 만든 자리)에 실제 API 응답을 채운다.

    이 함수는 그 턴을 그리는 st.chat_message("assistant") 블록 안, st.spinner로 감싼
    채로 호출된다 — 그래서 이 안의 네트워크 호출이 끝날 때까지 그 자리에만 로딩
    표시가 뜨고, 이미 그려진 질문 말풍선이나 이전 턴들은 그대로 보인다.
    """
    question = turn["question"]
    team = st.session_state.get("team_choice")
    body = {"question": question, "thread_id": st.session_state.thread_id, "requester_team": team}
    t0 = time.monotonic()
    data, err = _api("POST", "/query", json=body)
    elapsed = time.monotonic() - t0  # UI에 표시할 체감 응답 시간(콜드 스타트 포함, 서버 내부 시간이 아니라 클라이언트 왕복 시간)
    if err:
        turn["response"] = {"answer": f"⚠️ {err}", "_elapsed": elapsed}
    elif data.get("status") == "pending_approval":
        st.session_state.pending_request = data["request"]
        st.session_state.thread_id = data.get("thread_id", st.session_state.thread_id)
        turn["response"] = {
            "answer": _t("chat_pending_answer", tab=_t("nav_approve")),
            "_elapsed": elapsed,
        }
    else:
        data["_elapsed"] = elapsed
        turn["response"] = data
    st.session_state.is_answering = False  # 이 요청은 끝났다 — 대기 중이던 다음 질문이 있으면 다음 rerun에서 처리 시작
    _fetch.clear()
    _recent_threads.clear()


def _approve(approved: bool) -> None:
    team = st.session_state.get("team_choice")
    body = {"thread_id": st.session_state.thread_id, "approved": approved, "requester_team": team}
    data, err = _api("POST", "/query/approve", json=body)
    st.session_state.pending_request = None
    if err:
        st.error(err)
        return
    if data.get("status") == "pending_approval":
        # 승인 대기가 여러 개 겹친 경우(예: 리소스 2개 동시 정지) 다음 대기가 이어서 뜬다
        st.session_state.pending_request = data["request"]
    st.session_state.chat_log.append(
        {"question": f"[{_t('approve_done_toast') if approved else _t('approve_rejected_toast')}]", "response": data}
    )
    st.toast(_t("approve_done_toast") if approved else _t("approve_rejected_toast"), icon="✅" if approved else "🚫")
    _fetch.clear()
    _recent_threads.clear()


@st.fragment(parallel=True)
def _render_assistant_turn(turn: dict) -> None:
    """대화창의 assistant 말풍선 하나를 그린다 — 답변 대기 중이면 이 프래그먼트
    안에서만 API를 호출하고 기다린다.

    `parallel=True`는 이 프래그먼트를 별도 스레드로 돌려서(Streamlit 공식 기능),
    느린 네트워크 호출이 앱 전체를 막지 않게 한다 — 이전에는 이 호출이 화면
    전체를 다시 그리는 st.rerun()(scope="app")의 일부였어서, 응답을 기다리는 동안
    사이드바·질문 입력창을 포함한 화면 전체가 "실행 중" 상태로 잠겨 있었다. 이제는
    이 말풍선 자리만 스피너로 대기하고, 나머지 화면(새 질문 입력 등)은 그동안에도
    계속 조작할 수 있다. 완료되면 st.rerun(scope="fragment")로 이 프래그먼트만
    다시 그린다 — 화면 전체가 아니라.
    """
    if turn["response"] is None:
        with st.spinner(_t("chat_spinner")):
            _fill_pending_turn(turn)
        # 첫 호출(= 전체 앱 rerun의 일부로 이 프래그먼트가 처음 그려지는 시점)엔
        # scope="fragment"를 못 쓴다(프래그먼트 전용 rerun 도중에만 허용됨) —
        # 그래서 여기는 기본 scope인 st.rerun()을 쓴다. 중요한 건 이 위의
        # _fill_pending_turn() 호출 자체가 parallel=True 덕에 별도 스레드에서
        # 돌아서, 기다리는 동안 나머지 화면(질문 입력 등)이 안 막힌다는 점이다.
        st.rerun()
        return

    resp = turn["response"]
    st.write(resp.get("answer", ""))
    meta_bits = []
    if resp.get("_elapsed") is not None:
        meta_bits.append(_t("elapsed_inline", s=f"{resp['_elapsed']:.1f}"))
    # 실제로 응답한 모델 — MODEL_FAILOVER.md 참고. 1순위가 막혀 페일오버가 걸리면
    # 여기 값도 그 턴만 자동으로 바뀐다(다음 턴에 1순위가 살아있으면 다시 돌아옴).
    if resp.get("active_model"):
        meta_bits.append(_t("active_model_inline", model=resp["active_model"]))
    if meta_bits:
        st.caption("  ·  ".join(meta_bits))
    structured = resp.get("structured")
    if structured:
        conf = structured.get("confidence", "-")
        # "아침 브리핑" 방향: "확신도: 높음" 같은 딱딱한 라벨+값 대신, 뱃지 문구
        # 자체가 뜻을 담게 한다("믿을만해요 ✅") — conf가 high/medium/low가 아닌
        # 예상 밖의 값이면 _t()가 키를 그대로 돌려주므로 CONFIDENCE_COLOR와 함께
        # 안전하게 폴백된다(기존 동작과 동일).
        badge = _pill(_t(f"conf_badge_{conf}"), CONFIDENCE_COLOR.get(conf, "#a1a1aa"))
        followup = _t("yes") if structured.get("needs_followup") else _t("no")
        st.markdown(
            f"{badge} &nbsp;·&nbsp; {_t('followup_label')}: **{followup}**",
            unsafe_allow_html=True,
        )


def _render_preview(turn: dict | None) -> None:
    """분할 화면 오른쪽 — 최신 답변의 구조화 요약·출처·트레이스를 shadcn 카드로 보여준다."""
    if not turn:
        ui.alert(title=_t("preview_empty_title"), description=_t("preview_empty_desc"), key="preview_empty")
        return
    if turn.get("response") is None:
        # _queue_question이 방금 얹은 "답변 대기" 턴 — 왼쪽에서 곧 st.rerun()이
        # 걸리므로 이 상태가 오래 보이진 않지만, 방어적으로 처리한다.
        ui.alert(title=_t("preview_pending_title"), key="preview_pending")
        return

    resp = turn["response"]
    if resp.get("_elapsed") is not None:
        st.caption(_t("preview_elapsed", s=f"{resp['_elapsed']:.1f}"))
    structured = resp.get("structured")
    if structured:
        conf = structured.get("confidence", "-")
        c1, c2 = st.columns(2)
        with c1:
            ui.metric_card(
                label=_t("confidence_label"), value=_t(f"conf_{conf}"), variant="dashboard", key="preview_conf"
            )
        with c2:
            ui.metric_card(
                label=_t("followup_label"),
                value=_t("yes") if structured.get("needs_followup") else _t("no"),
                variant="dashboard",
                key="preview_followup",
            )
        if structured.get("key_numbers"):
            ui.card(
                title=_t("preview_key_numbers_title"),
                content=", ".join(structured["key_numbers"]),
                key="preview_numbers",
            )
    else:
        ui.alert(title=_t("preview_no_structured_title"), description=resp.get("answer", "")[:200], key="preview_raw")

    if resp.get("contexts"):
        ui.card(
            title=_t("preview_sources_title", n=len(resp["contexts"])),
            content=" / ".join(c["doc_id"] for c in resp["contexts"]),
            key="preview_sources",
        )
        for ctx in resp["contexts"]:
            with st.expander(ctx["doc_id"]):
                st.text(ctx["text"])

    if resp.get("trace"):
        st.caption(_t("preview_trace_caption", n=len(resp["trace"])))
        # 표(st.dataframe) 대신 스텝별 카드로 그린다 — 순서를 한눈에 훑어보기 쉽도록.
        for i, t in enumerate(resp["trace"], start=1):
            with st.container(border=True):
                step_col, detail_col = st.columns([1, 6])
                with step_col:
                    st.markdown(f"**{i}**")
                with detail_col:
                    ui.badge(text=t.get("tool") or t.get("step") or "-", variant="secondary", key=f"trace_badge_{i}")
                    output = str(t.get("output") or "")
                    st.caption(output[:180] + ("…" if len(output) > 180 else ""))


_init_state()


@st.fragment
def _render_resume_section() -> None:
    """'지난 대화 이어가기' 카드 — 이 함수만 프래그먼트로 분리해서, 대화 선택
    드롭다운을 바꿔도 이 카드 안쪽만 다시 그려지게 한다. 프래그먼트로 감싸기 전에는
    ui.select 값이 바뀔 때마다 전체 앱이 처음부터 다시 실행돼(사이드바 위쪽 항목,
    대시보드/히스토리 fetch 등 전부) 화면이 통째로 리프레시되는 것처럼 보였다 —
    선택 자체는 아무 동작도 하지 않아야 하고, 실제 이어가기는 버튼을 눌러야만
    일어나야 한다는 요구로 분리했다.
    """
    with st.container(border=True):
        st.markdown(f"**{_t('resume_section_title')}**")
        if not _ping(st.session_state.base_url):
            st.caption(_t("resume_offline_hint"))
            return
        threads, threads_err = _recent_threads(st.session_state.base_url)
        threads = [t for t in threads if t["thread_id"] != st.session_state.thread_id]
        if threads_err:
            st.caption(_t("resume_fetch_failed", err=threads_err))
            return
        if not threads:
            st.caption(_t("resume_no_threads"))
            return
        sel_idx = ui.select(
            label=_t("resume_select_label"),
            options=list(range(len(threads))),
            format_func=lambda i: _thread_label(threads[i]),
            key="resume_select",
        )
        st.caption(f"`{threads[sel_idx]['thread_id'][:13]}…`")
        if ui.button(_t("resume_btn"), variant="secondary", width="stretch", key="resume_btn"):
            _resume_thread(threads[sel_idx]["thread_id"])
            st.session_state.active_nav = "chat"  # 이어서 대화하기 -> 질의응답 화면으로 바로 이동
            st.session_state.nav_epoch += 1  # 탭 위젯을 새로 mount시켜 강제 전환이 확실히 반영되게 한다
            st.rerun()  # scope="app"(기본값) — 프래그먼트 밖 nav 전환·챗 화면까지 바뀌어야 해서 전체 재실행이 필요하다


@st.fragment
def _render_team_select() -> None:
    """요청자 팀 선택만 별도 프래그먼트로 분리한다.

    이 값(requester_team)은 채팅 질문을 보낼 때만 쓰이고 대시보드·히스토리·배치
    이력의 데이터와는 전혀 무관한데, 프래그먼트로 안 감싸면 이 셀렉트를 바꿀 때마다
    Streamlit 기본 동작(위젯이 바뀌면 전체 스크립트를 처음부터 다시 실행)에 따라
    사이드바 나머지 항목은 물론 현재 화면의 데이터 조회·차트 재계산까지 전부 다시
    돈다. 프래그먼트로 감싸면 이 위젯이 바뀔 때 이 함수 안쪽만 다시 실행된다.

    ui.select(shadcn)가 아니라 네이티브 st.selectbox를 쓴다 — shadcn 쪽은 shadow
    DOM이라 "아침 브리핑" 색·폰트가 안 먹는데, st.selectbox는 일반 DOM이라 CUSTOM_CSS가
    그대로 적용된다. 선택값 유지·on_change 같은 기능은 st.selectbox가 key= 하나로
    동일하게 처리하므로 동작 차이는 없다.
    """
    team_key = st.selectbox(
        _t("team_label"),
        options=TEAM_KEYS,
        format_func=lambda k: _t("team_none") if k == "none" else k,
        key="team_choice_label",
    )
    st.session_state.team_choice = TEAM_VALUES[team_key]


with st.sidebar:
    # 사용자 피드백("좀 더 직관적이고 심플하게")으로 다시 짠 구조 — 평소에 계속
    # 눈에 보여야 하는 것(연결 상태 · 새 대화 · 지난 대화 이어가기)만 사이드바
    # 맨 위에 두고, 자주 안 건드리는 설정(서버 주소 · 요청자 팀 · 언어)은 맨 아래
    # "⚙️ 설정" expander 하나로 접어 넣었다. 예전엔 언어 선택이 맨 위, 서버 주소·
    # 요청자 팀이 그 사이사이에 구분선과 함께 끼어 있어서 "지금 뭘 할 수 있는지"가
    # 한눈에 안 들어왔다.
    # 연결 상태 배지는 사용자 요청으로 제거했다 — online 자체는 대시보드
    # 프래그먼트 호출·미확인 배치 배지 계산 등에서 계속 쓰이므로 값만 남긴다.
    online = _ping(st.session_state.base_url)

    if st.button(_t("new_chat_btn"), key="new_chat_btn", width="stretch", type="primary"):
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.chat_log = []
        st.session_state.pending_request = None
        st.session_state.resume_notice = None
        st.session_state.active_nav = "chat"  # 새 대화 시작 -> 질의응답 화면으로 바로 이동
        st.session_state.nav_epoch += 1  # 탭 위젯을 새로 mount시켜 강제 전환이 확실히 반영되게 한다
        st.rerun()

    # 세션 통계는 미니 카드 2개 대신 캡션 한 줄로 — 승인 대기는 0일 때는 아예 안
    # 보여준다("0건"을 늘 보여주는 건 정보가 아니라 잡음이고, 있을 때만 보이면
    # 오히려 더 눈에 잘 띈다).
    stat_line = _t("stat_questions_inline", n=len(st.session_state.chat_log))
    if st.session_state.pending_request:
        stat_line += "  ·  " + _t("stat_pending_inline")
    st.caption(stat_line)

    st.divider()
    _render_resume_section()

    st.divider()
    with st.expander(_t("settings_expander")):
        # ui.select도 ui.tabs와 같은 "controlled" 컴포넌트라, 매번 st.session_state.lang에서
        # 새로 계산한 index를 강제로 넘기면 사용자가 방금 고른 값을 그 자리에서 다시
        # 덮어써 버려서 클릭이 반영 안 되는 문제가 있었다(예전 index= 방식의 버그) —
        # value=로 "현재 확정된 언어"만 넘기고, 반환값이 그것과 다를 때만 갱신+rerun한다.
        lang = ui.select(
            label=_t("lang_label"),
            options=LANG_KEYS,
            value=st.session_state.lang,
            format_func=lambda k: LANG_DISPLAY[k],
            key="lang_select",
        )
        if lang != st.session_state.lang:
            st.session_state.lang = lang
            st.rerun()  # 언어가 바뀌면 이미 그려진 라벨들도 새 언어로 다시 그리도록 즉시 재실행

        _render_team_select()
        st.session_state.base_url = st.text_input(_t("server_url_label"), value=st.session_state.base_url)
        st.caption(_t("thread_id_caption", tid=st.session_state.thread_id[:13]))

st.subheader(_t("app_name"))
st.caption(_t("app_tagline"))

# 미확인 이상탐지 배지 — "배치 이력" 탭에 안 들어가 있어도 새로 발견된 이상이 있으면
# 탭 라벨에 숫자로 보여준다. nav를 렌더링하기 전에 계산해야 라벨에 반영된다.
# limit을 대시보드 본문(_render_dashboard)이 쓰는 것과 똑같이 200으로 맞춘다 —
# _fetch()는 (base_url, path, limit)로 캐시 키를 잡으므로, limit이 같으면 같은
# 캐시 항목을 공유해서 대시보드 화면일 때 이 호출과 대시보드 본문의 호출이 실제
# 네트워크 요청 하나로 합쳐진다(전엔 limit 30/200이 서로 달라 캐시가 안 겹쳐서
# 매번 두 번 호출됐다). 배지 계산은 최근 30건이면 충분하니 앞에서 30개만 자른다.
unseen_batch_count = 0
if online:
    _badge_items, _ = _fetch(st.session_state.base_url, "/batch-runs", 200)
    _badge_items = _badge_items[:30]
    last_seen = st.session_state.last_seen_batch_at
    unseen_batch_count = sum(
        1 for r in _badge_items if r["findings_count"] > 0 and (last_seen is None or r["started_at"] > last_seen)
    )


def _nav_label(key: str) -> str:
    label = _t(f"nav_{key}")
    return f"{label} · {unseen_batch_count}" if key == "batch" and unseen_batch_count else label


# 대시보드/히스토리/배치 이력 화면 본문을 각각 @st.fragment로 감싼다 — 안 감싸면
# 화면 안의 필터 위젯(배치 조회 기간, thread_id 필터, 최대 건수 등)을 하나만 바꿔도
# Streamlit 기본 동작대로 전체 스크립트가 처음부터 다시 실행돼 사이드바(연결 확인,
# 팀 선택 등)까지 같이 재계산된다. 프래그먼트로 감싸면 그 위젯이 바뀔 때 이 함수
# 안쪽만 다시 실행되고 사이드바·다른 화면은 그대로 남는다.
@st.fragment
def _render_dashboard(online: bool) -> None:
    st.subheader(_t("dash_greeting"))
    st.caption(_t("dash_greeting_sub"))
    if not online:
        ui.alert(title=_t("dash_offline_title"), description=_t("dash_offline_desc"), variant="destructive", key="dash_offline")
    else:
        st.caption(_t("dash_window_caption"))
        window_key = st.selectbox(
            _t("dash_window_caption"),
            options=BATCH_WINDOW_KEYS,
            index=1,
            format_func=lambda k: _t(f"window_{k}"),
            key="dash_batch_window",
            label_visibility="collapsed",
        )
        _raw_batch_items, batch_err = _fetch(st.session_state.base_url, "/batch-runs", 200)
        hours = BATCH_WINDOW_HOURS[window_key]
        if hours is None:
            batch_items = _raw_batch_items
        else:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
            batch_items = [r for r in _raw_batch_items if r["started_at"] >= cutoff]
        hist_items, hist_err = _fetch(st.session_state.base_url, "/history", 100)

        latest_by_provider: dict[str, dict] = {}
        for row in batch_items:  # 최신순으로 오므로 처음 만나는 provider가 최신 실행
            latest_by_provider.setdefault(row["provider"], row)

        if latest_by_provider:
            total_findings = sum(r["findings_count"] for r in latest_by_provider.values())
            if total_findings > 0:
                st.markdown(
                    _brief_alert_html(
                        _t("dash_anomaly_alert_title", n=total_findings),
                        _t("dash_anomaly_alert_desc", tab=_t("nav_batch")),
                    ),
                    unsafe_allow_html=True,
                )
            cols = st.columns(len(latest_by_provider) or 1)
            for col, (provider, row) in zip(cols, latest_by_provider.items()):
                with col:
                    # ui.metric_card는 shadow DOM이라 카드 모양을 못 바꿔서, "아침
                    # 브리핑" 방향에 맞춰 순수 HTML 카드로 직접 그린다(건수보다
                    # 서술형 문장이 먼저 보이도록). 클릭형 상세 팝업(ui.popover)은
                    # shadow DOM이라도 기능 자체는 그대로 유지한다.
                    ok = row["findings_count"] == 0
                    note = (
                        _t("dash_provider_calm", provider=provider.upper())
                        if ok
                        else _t("dash_provider_note", provider=provider.upper(), n=row["findings_count"])
                    )
                    st.markdown(
                        _brief_card_html(
                            provider.upper(), note, _t("dash_metric_value", n=row["findings_count"]), ok
                        ),
                        unsafe_allow_html=True,
                    )
                    ui.popover(
                        label=_t("dash_popover_label"),
                        content=_format_anomaly_popup(row["detail"]),
                        key=f"dash_popover_{provider}",
                    )

            st.subheader(_t("dash_chart_subheader"))
            # st.bar_chart(Vega-Lite) 대신 "아침 브리핑" 방향의 골드색 둥근-끝
            # 스파크라인(SVG)을 직접 그린다 — provider별 구분은 위 브리핑 카드가
            # 이미 보여주므로, 여기서는 날짜별 총 findings_count 추이만 본다.
            daily_totals = (
                pd.DataFrame(batch_items)
                .assign(day=lambda d: d["started_at"].str[:10])
                .groupby("day")["findings_count"]
                .sum()
                .sort_index()
            )
            st.markdown(_sparkline_svg(daily_totals.tolist()), unsafe_allow_html=True)
            st.markdown(
                '<div class="brief-spark-days">' + "".join(f"<span>{d[5:]}</span>" for d in daily_totals.index) + "</div>",
                unsafe_allow_html=True,
            )
        else:
            ui.alert(title=_t("dash_no_batch_title"), description=_t("dash_no_batch_desc"), key="dash_no_batch")

        st.divider()
        status_counts = pd.Series([r["status"] for r in hist_items]).value_counts() if hist_items else pd.Series()
        # ui.metric_card 3개(shadow DOM) 대신 목업의 .pill 알약형 뱃지 행으로 그린다 —
        # "아침 브리핑"에서는 이 세 수치가 카드 하나씩보다 한 줄 요약처럼 보이는 게 더 맞다.
        st.markdown(
            '<div class="pill-row">'
            + _stat_pill_html(_t("dash_total_history"), len(hist_items))
            + _stat_pill_html(_t("dash_pending_count"), int(status_counts.get("pending_approval", 0)))
            + _stat_pill_html(_t("dash_blocked_count"), int(status_counts.get("blocked", 0)))
            + "</div>",
            unsafe_allow_html=True,
        )


@st.fragment
def _render_history() -> None:
    st.subheader(_t("history_subheader"))
    col1, col2, col3 = st.columns([3, 1, 1])
    thread_filter = col1.text_input(_t("history_thread_filter"), value="")
    limit = col2.number_input(_t("history_limit_label"), min_value=1, max_value=500, value=50)
    col3.write("")
    col3.write("")
    col3.button(_t("refresh_btn"), key="history_refresh", width="stretch")
    keyword = st.text_input(_t("history_keyword_label"), value="", key="history_keyword")
    # 화면에 처음 들어왔을 때도(필터 입력·새로고침 클릭 전) 전체 조회 결과가 바로
    # 보여야 한다는 요구로, 조건 없이 매번 조회한다 — thread_filter가 비어 있으면
    # /history가 전체를 반환하므로 "전체 검색"이 기본값이 된다. 조회 자체는
    # _fetch_page_localized()가 8초 캐싱하므로, 조건이 그대로면(예: 검색어만 입력)
    # 실제 네트워크 호출 없이 캐시를 재사용한다.
    if thread_filter:
        data, err = _fetch_page_localized(st.session_state.base_url, "/history", limit=int(limit), thread_id=thread_filter)
    else:
        data, err = _fetch_page_localized(st.session_state.base_url, "/history", limit=int(limit))
    if err:
        st.error(err)
    elif data.get("items"):
        items = data["items"]
        if keyword:
            kw = keyword.lower()
            items = [r for r in items if kw in r["question"].lower() or kw in r["answer"].lower()]
        if not items:
            st.info(_t("history_no_match", kw=keyword) if keyword else _t("no_records"))
        else:
            df = pd.DataFrame(items)
            st.caption(_t("count_caption_keyword", n=len(df), kw=keyword) if keyword else _t("count_caption", n=len(df)))

            def _status_style(val):
                return STATUS_BG.get(val, "")

            st.dataframe(
                df.style.map(_status_style, subset=["status"]) if "status" in df.columns else df,
                width="stretch",
                hide_index=True,
            )
            st.download_button(
                _t("csv_export_btn"),
                df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"qa_history_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.csv",
                mime="text/csv",
            )
    else:
        st.info(_t("no_records"))


@st.fragment
def _render_batch() -> None:
    st.subheader(_t("batch_subheader"))
    st.caption(_t("batch_caption"))
    limit_b = st.number_input(_t("history_limit_label"), min_value=1, max_value=500, value=50, key="batch_limit")
    st.button(_t("refresh_btn"), key="batch_refresh")
    # 히스토리와 동일한 이유로 버튼 클릭 전에도 전체 조회 결과를 바로 보여주고,
    # 조회 자체는 _fetch_page_localized()가 8초 캐싱한다.
    data, err = _fetch_page_localized(st.session_state.base_url, "/batch-runs", limit=int(limit_b))
    if err:
        st.error(err)
    else:
        items = data.get("items", [])
        st.caption(_t("count_caption", n=len(items)))
        if items:
            df = pd.DataFrame(items)

            def _highlight(row):
                color = STATUS_BG["blocked"] if row["findings_count"] > 0 else ""
                return [color] * len(row)

            st.dataframe(df.style.apply(_highlight, axis=1), width="stretch", hide_index=True)
            st.download_button(
                _t("csv_export_btn"),
                df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"batch_runs_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.csv",
                mime="text/csv",
            )
        else:
            st.info(_t("no_records"))


# ui.tabs는 "controlled" 컴포넌트라(공식 docstring: "Render controlled shadcn Tabs") value를
# 넘기면 그 값을 강제로 반영한다 — st.session_state.active_nav를 넣었다 뺐다 하면서
# "새 대화 시작"/"이어서 대화하기" 버튼이 화면을 강제로 전환할 수 있게 한다. 사용자가
# 탭을 직접 클릭해서 값이 달라지면 바로 아래에서 active_nav에 되먹임한다.
#
# key에 nav_epoch를 섞는 이유: 이 컴포넌트는 "지난 렌더에서 넘긴 value"의 fingerprint만
# 저장해뒀다가 지금 넘긴 value의 fingerprint와 같으면 "기본값 안 바뀜"으로 보고 사용자가
# 방금 직접 클릭한 값을 그대로 돌려준다. 그런데 우리 value=는 항상 "이 클릭을 반영하기
# 전" 값이라 한 렌더 지연이 있어서, 강제 전환 목표가 그 지연된 값과 우연히 같아지면
# (예: chat 강제 -> 직접 클릭으로 dashboard 선택 -> chat으로 다시 강제) 두 번째 강제
# 전환이 무시되고 화면이 dashboard에 머무는 버그가 있었다. 강제 전환 버튼을 누를 때만
# nav_epoch를 올려 key를 바꾸면 그 순간 위젯이 완전히 새로 mount되어(과거 fingerprint
# 이력이 없음) 이런 오판 없이 항상 반영된다.
nav = ui.tabs(
    options=NAV_KEYS,
    value=st.session_state.active_nav,
    format_func=_nav_label,
    key=f"main_nav_{st.session_state.nav_epoch}",
    width="stretch",
)
st.session_state.active_nav = nav

if nav == "batch" and online and _badge_items:
    # 탭을 실제로 열어봤으니 지금까지 본 것 중 가장 최근 시각으로 "확인함" 표시 —
    # 다음 렌더부터 그 시각 이후 항목만 미확인으로 센다.
    st.session_state.last_seen_batch_at = max(r["started_at"] for r in _badge_items)

if nav == "dashboard":
    _render_dashboard(online)

elif nav == "chat":
    left, right = st.columns([3, 2])

    with left:
        if st.session_state.resume_notice:
            ui.alert(
                title=_t("resume_alert_title"), description=st.session_state.resume_notice, variant="destructive", key="resume_alert"
            )
        if st.session_state.pending_request:
            ui.alert(
                title=_t("chat_pending_alert_title"),
                description=_t("chat_pending_alert_desc", tab=_t("nav_approve")),
                key="chat_pending_alert",
            )

        st.caption(_t("quick_questions_caption"))
        qcols = st.columns(len(QUICK_QUESTIONS))
        for i, (col, (label_key, q)) in enumerate(zip(qcols, QUICK_QUESTIONS)):
            with col:
                if ui.button(
                    _t(label_key),
                    variant="outline",
                    size="sm",
                    width="stretch",
                    disabled=st.session_state.is_answering,
                    key=f"quick_{i}",
                ):
                    st.session_state.pending_question = q

        chat_box = st.container(height=420, border=True)
        with chat_box:
            # 답변 대기 중인(response=None) 턴이 여러 개여도 한 번에 하나씩만 실제로
            # 처리한다 — 안 그러면 두 번째 질문을 보냈을 때 같은 thread_id로 첫
            # 번째 요청이 아직 안 끝난 상태에서 두 번째 요청까지 동시에 나가버려서
            # (서버 쪽 체크포인터가 같은 thread_id의 동시 실행을 감당 못 해) 오류가
            # 났다. 목록을 순서대로 훑다가 "아직 안 끝난 첫 턴"을 만나면 그 뒤에
            # 오는 턴은 전부 대기만 시킨다.
            _first_pending_seen = False
            for turn in st.session_state.chat_log:
                with st.chat_message("user", avatar="🧑‍💻"):
                    st.write(turn["question"])
                with st.chat_message("assistant", avatar="☁️"):
                    if turn["response"] is not None:
                        _render_assistant_turn(turn)
                    elif _first_pending_seen:
                        # 이미 앞에 처리 중인 턴이 있다 — 이 턴은 아직 순서가 아니다.
                        st.caption(_t("queued_caption"))
                    else:
                        _first_pending_seen = True
                        if st.session_state.is_answering:
                            # 이 턴은 이전 run에서 이미 dispatch돼 백그라운드
                            # 스레드가 처리 중이다 — 여기서 또 dispatch(중복 호출)
                            # 하지 않고 진행 중이라는 표시만 보여준다.
                            st.caption(_t("chat_spinner"))
                        else:
                            st.session_state.is_answering = True
                            _render_assistant_turn(turn)

        input_col, export_col = st.columns([9, 1])
        with input_col:
            question = st.chat_input(
                _t("chat_input_disabled_placeholder") if st.session_state.is_answering else _t("chat_input_placeholder"),
                disabled=st.session_state.is_answering,
            )
        with export_col:
            if st.session_state.chat_log:
                st.download_button(
                    "💾",
                    _chat_transcript_md().encode("utf-8"),
                    file_name=f"chat_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.md",
                    mime="text/markdown",
                    key="chat_export_btn",
                    help=_t("chat_export_btn"),
                )
        if st.session_state.pending_question:
            question = st.session_state.pending_question
            st.session_state.pending_question = None
        if question:
            _queue_question(question)
            st.rerun()

    with right:
        st.subheader(_t("preview_subheader"))
        _render_preview(st.session_state.chat_log[-1] if st.session_state.chat_log else None)

elif nav == "approve":
    st.subheader(_t("approve_subheader"))
    req = st.session_state.pending_request
    if not req:
        ui.alert(title=_t("approve_empty_title"), key="approve_empty")
    else:
        with st.container(border=True):
            ui.alert(
                title=_t("approve_warn_title", tool=req.get("tool")),
                description=req.get("reason", "-"),
                variant="destructive",
                key="approve_warn",
            )
            st.json(req.get("args", {}))
            col1, col2 = st.columns(2)
            with col1:
                if ui.button(_t("approve_yes"), variant="default", width="stretch", key="approve_yes"):
                    _approve(True)
                    st.rerun()
            with col2:
                if ui.button(_t("approve_no"), variant="destructive", width="stretch", key="approve_no"):
                    _approve(False)
                    st.rerun()

elif nav == "history":
    _render_history()

elif nav == "batch":
    _render_batch()
