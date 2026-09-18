# 화면 정의서 — 로컬 데모 UI (`ui/streamlit_app.py`)

이 문서는 `ui/streamlit_app.py`(Streamlit 기반 로컬 데모 UI)의 화면 구성을 정의한다.
백엔드 프로세스는 [PROCESS_SPEC.md](PROCESS_SPEC.md), 서비스 정책은 [SERVICE.md](SERVICE.md),
DB 구조는 [ERD.md](ERD.md) 참고. 이 UI는 `src/app.py`(FastAPI)를 그대로 호출하는
**로컬 개발/데모 전용** 화면이다 — 인증 없음, 프로덕션 배포 대상 아님.

## 1. 개요

| 항목 | 내용 |
|---|---|
| 프레임워크 | Streamlit 1.64 + `streamlit-shadcn-ui`(shadcn/ui 컴포넌트를 감싼 커스텀 컴포넌트 패키지) |
| 테마 | "아침 브리핑"(Morning Briefing) 방향 — 세이지빛 종이 배경 + 따뜻한 골드 강조 (`.streamlit/config.toml`, `backgroundColor` `#f4f6f1` + `primaryColor` `#cf8a2e`). 제목은 Libre Franklin, 본문은 Karla(둘 다 구글 폰트, `streamlit_app.py`의 `CUSTOM_CSS`에서 로드) — shadcn 컴포넌트는 격리된 shadow DOM이라 이 폰트가 안 닿고 `config.toml` 테마 토큰만 따라간다 |
| 백엔드 연동 방식 | 이 프로세스가 `requests`로 FastAPI(`POST /query` 등)를 서버-서버 호출 — 브라우저 CORS 정책이 개입하지 않는다 |
| 실행 | 터미널 1: `uvicorn src.app:app --reload --port 8000` / 터미널 2: `streamlit run ui/streamlit_app.py` |
| 레이아웃 골격 | 좌측 고정 사이드바(연결 설정) + 상단 화면 전환 탭(`ui.tabs`) + 화면별 본문 |

성능: 사이드바의 "요청자 팀" 선택과 대시보드/히스토리/배치 이력 세 화면의 본문은
각각 `@st.fragment`로 감싼 함수(`_render_team_select`/`_render_dashboard`/
`_render_history`/`_render_batch`)다. Streamlit은 위젯 하나가 바뀌면 기본적으로
전체 스크립트를 처음부터 다시 실행하는데, 이 프래그먼트들이 없으면 요청자 팀을
바꾸거나 히스토리 화면에서 필터 하나만 바꿔도 사이드바 나머지·다른 화면 데이터
조회까지 전부 다시 돈다. 프래그먼트로 감싸면 그 안의 위젯이 바뀔 때 해당 함수
안쪽만 재실행되고 나머지 화면은 그대로 남는다(직접 겪은 문제 — 지난 대화
이어가기의 대화 선택 드롭다운도 같은 이유로 먼저 분리했었다).

## 2. 공통 레이아웃 — 사이드바

모든 화면에서 항상 보이는 영역이다 ([streamlit_app.py](ui/streamlit_app.py)). "좀 더 직관적이고
심플하게" 요청으로 재구성했다 — 평소에 계속 봐야 하는 것(새 대화·지난 대화 이어가기)만
위에 두고, 자주 안 건드리는 설정(서버 주소·요청자 팀·언어)은 맨 아래 "⚙️ 설정"
`st.expander` 하나로 접었다. 연결 상태 배지는 사용자 요청으로 제거했다(대시보드 등
다른 화면에서 이미 오프라인 여부를 안내함) — `online` 값 자체는 대시보드 프래그먼트
호출·미확인 배치 배지 계산에 계속 쓰여서 내부적으로는 남아 있다.

| 구성 요소 | 컴포넌트 | 설명 | 데이터 소스 |
|---|---|---|---|
| 새 대화 시작 | `st.button` (primary) | `thread_id` 새로 발급 + `chat_log`/`pending_request`/`resume_notice` 초기화 | - |
| 세션 통계 캡션 | `st.caption` | "질문 N개" 항상 표시, "🔒 승인 대기 중"은 `pending_request`가 있을 때만 이어붙임(0건일 땐 아예 안 보여줘서 있을 때 더 눈에 띄게 함) | 클라이언트 세션 상태 |
| 지난 대화 이어가기 | `ui.select` + `ui.button` (secondary) | 최근 활동 스레드 최대 15개 중 선택 → `chat_log` 재구성 | `GET /history`(최근 200건을 thread_id로 그룹핑) |
| **⚙️ 설정** (`st.expander`, 기본 접힘) | | 아래 3개는 이 안에 있다 | |
| ㄴ 언어 | `ui.select` | 한국어/English | - |
| ㄴ 요청자 팀 선택 | `st.selectbox` | `TEAM_OPTIONS`(제한 없음/team-a/b/c) — SERVICE.md 가드레일 규칙 5의 `requester_team` | - |
| ㄴ 서버 주소 입력 | `st.text_input` | 기본값 `http://localhost:8000`. 세션 상태 `base_url` | - |
| ㄴ 현재 thread_id | `st.caption` | 앞 13자만 표시(디버그용, 평소엔 안 보여도 되는 정보라 설정 안으로 옮김) | 세션 상태 `thread_id` |

## 3. 공통 레이아웃 — 상단 네비게이션

`ui.tabs(options=NAV_OPTIONS, key=f"main_nav_{st.session_state.nav_epoch}")`
([streamlit_app.py](ui/streamlit_app.py)) 로 아래 5개 화면을 전환한다. 선택값에 따라 `if/elif`
분기로 본문을 그린다(각 화면 코드는 매 렌더링마다 전부 평가되지만, 선택 안 된 분기는
화면에 안 그려짐). key에 `nav_epoch`를 섞는 이유 — "새 대화 시작"/"이어서 대화하기"
버튼으로 탭을 강제 전환할 때만 `nav_epoch`를 올려 위젯을 완전히 새로 mount시킨다.
그렇지 않으면 shadcn 탭 컴포넌트가 "지난 렌더에서 넘긴 기본값의 fingerprint"만 보고
변경 여부를 판단해서, 강제 전환 목표값이 그 사이 사용자가 직접 클릭해 둔 값과 우연히
겹치면 강제 전환이 무시되는 버그가 있었다(직접 겪음).

| 화면 ID | 이름 | 목적 |
|---|---|---|
| S1 | 📊 대시보드 | 최근 이상탐지·대화 통계를 한눈에 요약 |
| S2 | 💬 질의응답 | 에이전트와 실제 대화(좌: 대화, 우: 실시간 미리보기 분할 화면) |
| S3 | 🔒 승인 대기 | HITL 실행 승인/거절 처리 |
| S4 | 🕓 히스토리 | 전체 질문-답변 이력 조회·CSV 내보내기 |
| S5 | 📈 배치 이력 | 자동 이상탐지 배치 실행 기록 조회·CSV 내보내기 |

---

## S1. 📊 대시보드

### 목적
서버를 열자마자 "지금 상태가 괜찮은지"를 한눈에 보여주는 요약 화면.

### 연동 API
- `GET /batch-runs?limit=30`
- `GET /history?limit=100`

### 구성 요소

| 요소 | 컴포넌트 | 조건부 표시 |
|---|---|---|
| 아침 인사 헤더 | `st.subheader` + `st.caption` | 항상 표시 — "아침 브리핑" 컨셉의 인사말(`dash_greeting`/`dash_greeting_sub`) |
| 오프라인 안내 | `ui.alert` (destructive) | 서버 연결 안 될 때만 |
| 이상 발견 경고 | `st.markdown`(`_brief_alert_html`, 순수 HTML) | 최근 배치 findings 합계 > 0 일 때만. `ui.alert`은 shadow DOM이라 카드 모양(세이지 톤+왼쪽 색 스트라이프)을 못 내서 네이티브 HTML로 직접 그린다 |
| provider별 최근 이상탐지 카드 | `st.markdown`(`_brief_card_html`, 순수 HTML) × provider 수 | provider별 최신 실행 1건씩. 건수보다 서술형 문장이 먼저 보이는 "브리핑 카드" 모양(둥근 모서리+그림자+좌측 상태 점) — 같은 이유로 `ui.metric_card` 대신 네이티브 HTML로 그린다 |
| 카드 안 서술형 문장 | 위 카드에 포함 | "OO에서 이상 신호 N건을 발견했어요"/"OO는 평온해요" (`dash_provider_note`/`dash_provider_calm`) — 카드 밖 별도 캡션이 아니라 카드 본문 |
| 상세 보기 팝업 | `ui.popover` | 카드 바로 아래, 클릭 시 `_format_anomaly_popup()`로 파싱한 리스트 표시(그대로 유지) |
| 배치 실행 추이 차트 | `st.markdown`(`_sparkline_svg`, 순수 SVG) | `batch_items`를 날짜별로 합산한 총 findings_count 추이(골드색 둥근-끝 라인). provider별 구분은 위 카드가 이미 보여주므로 여기선 전체 추이만 본다. 값이 1일치뿐이면 점만 표시 |
| 배치 이력 없음 안내 | `ui.alert` | `latest_by_provider`가 비어있을 때 |
| 전체 통계 3종 | `st.markdown`(`_stat_pill_html`, 순수 HTML) × 3 | 전체 대화 기록 / 승인 대기 중 / 차단된 요청 (히스토리 status 집계). `ui.metric_card`(shadow DOM) 대신 목업의 알약형(`.pill-stat`) 뱃지 한 줄로 표시 |

### 예외·엣지 케이스
- 서버 미연결 시 API 호출 자체를 생략하고 경고만 표시(불필요한 타임아웃 대기 방지)
- 배치 실행이 아직 한 번도 없으면(서버 막 기동) 차트 대신 안내 문구

---

## S2. 💬 질의응답 (분할 화면)

### 목적
실제 에이전트와 대화하는 메인 화면. v0.dev류 좌/우 분할 레이아웃 — 좌측에서 묻고, 우측에서
그 답변의 구조화 데이터를 바로 확인한다. **주의**: Streamlit은 제출(엔터) 시에만 스크립트가
재실행되므로, 타이핑 글자 단위로 반응하는 완전한 실시간 프리뷰는 아니다 — 질문을 보낼
때마다 양쪽이 함께 갱신되는 정도.

### 연동 API
- `POST /query` (질문 전송)

### 레이아웃

```
┌───────────────────────────┬─────────────────────┐
│ 좌측(60%): 대화            │ 우측(40%): 실시간 미리보기│
│  - 안내 배너(승인대기 등)   │  - 확신도/후속확인 카드   │
│  - 자주 묻는 질문 버튼 4개  │  - 핵심 수치 카드        │
│  - 대화창(고정 높이 420px) │  - 출처 문서 카드+펼침    │
│  - 하단 chat_input        │  - 도구 호출 트레이스 표  │
└───────────────────────────┴─────────────────────┘
```

### 구성 요소 — 좌측

| 요소 | 컴포넌트 | 설명 |
|---|---|---|
| 이어받은 대화 경고 | `ui.alert` (destructive) | `resume_notice`가 있을 때만(마지막이 승인 대기 상태였던 대화를 이어받은 경우) |
| 승인 대기 안내 | `ui.alert` | `pending_request`가 있으면 표시 |
| 자주 묻는 질문 | `ui.button` (outline, sm) × 4 | `QUICK_QUESTIONS` — 클릭 시 그 질문으로 즉시 전송 예약 |
| 대화창 | `st.chat_message`(user 🧑‍💻 / assistant ☁️) | `chat_log` 순서대로 렌더링, 답변 아래 확신도/후속확인 인라인 배지 — 확신도 뱃지는 "높음/보통/낮음" 대신 "믿을만해요 ✅"/"어느 정도 맞을 거예요"/"다시 확인해 보세요 ⚠️" 같은 문장형 문구(`conf_badge_*`) |
| 응답 시간·사용 모델 캡션 | `st.caption` | 답변 말풍선 맨 위, "⏱ N초 · 🤖 모델ID" 형태. `active_model`은 이번 턴에서 실제로 응답한 Bedrock 모델(`MODEL_FAILOVER.md`) — 1순위가 막혀 페일오버되면 그 턴만 다른 모델 ID가 보인다 |
| 질문 입력 | `st.chat_input` | 제출 시 `_send_query()` 호출 후 `st.rerun()` |

### 구성 요소 — 우측(`_render_preview`, [streamlit_app.py:246-291](ui/streamlit_app.py#L246-L291))

| 상태 | 표시 내용 |
|---|---|
| 대화 없음 | `ui.alert` — "아직 대화가 없습니다" 안내 |
| 구조화 답변 있음 | `ui.metric_card` 2개(확신도/추가 확인 필요) + `ui.card`(핵심 수치, `key_numbers`가 있을 때만) |
| 구조화 답변 없음 | `ui.alert` — 원시 답변 앞부분만 표시 |
| 출처 문서 있음 | `ui.card`(문서 목록 요약) + 문서별 `st.expander`(원문) |
| 트레이스 있음 | `st.dataframe`(도구 호출 내역) |

### 예외·엣지 케이스
- 서버 오류/타임아웃 시 해당 턴의 답변 자리에 `⚠️ <사유>` 텍스트로 표시(대화는 끊기지 않음)
- HITL 승인이 필요한 질문은 답변 대신 "🔒 실행 승인이 필요합니다" 안내로 대체되고, `pending_request`가 세팅됨 → S3로 이동 유도

---

## S3. 🔒 승인 대기

### 목적
`execution_agent`가 승인이 필요한 도구(`stop_resource`/`resize_resource`/`send_cost_alert`)를
고른 경우, 실제 실행 여부를 사람이 결정하는 화면.

### 연동 API
- `POST /query/approve`

### 구성 요소

| 요소 | 컴포넌트 | 설명 |
|---|---|---|
| 대기 없음 안내 | `ui.alert` | `pending_request`가 `None`일 때 |
| 승인 요청 카드 | `st.container(border=True)` 안에 `ui.alert`(destructive) + `st.json`(도구 인자) | 도구명·사유·인자를 그대로 노출(마스킹은 서버가 이미 `mask_pii_deep`로 처리) |
| 승인/거절 버튼 | `ui.button`(default) / `ui.button`(destructive) | 클릭 시 `_approve(True/False)` → `st.rerun()` |

### 예외·엣지 케이스
- 한 턴에 승인 대기가 여러 개 겹치면(예: 리소스 2개 동시 정지), 하나 처리할 때마다 서버가 다음 대기 항목을 이어서 돌려주고 화면이 자동으로 그 다음 항목을 보여준다
- 승인/거절 결과는 대화창(S2)에도 `[승인 완료]`/`[승인 거절]` 턴으로 함께 기록됨

---

## S4. 🕓 히스토리

### 목적
`data/history.db`에 쌓인 전체 질문-답변 이력을 조회하고 CSV로 내보낸다.

### 연동 API
- `GET /history?thread_id=&limit=`

### 구성 요소

| 요소 | 컴포넌트 | 설명 |
|---|---|---|
| 필터 입력 | `st.text_input`(thread_id) + `st.number_input`(최대 건수, 기본 50) | thread_id 비우면 전체 조회 |
| 조회 버튼 | `st.button` | 클릭 없이도 화면 진입 시 즉시 전체 조회(thread_id 비운 상태)가 실행됨 — 필터를 바꾸면 그 값으로 다시 조회, 버튼은 수동 새로고침용 |
| 결과 표 | `st.dataframe` + pandas Styler | `status` 값에 따라 행 배경색(`STATUS_BG`: answered=초록/pending_approval=주황/blocked·error=빨강) |
| CSV 내보내기 | `st.download_button` | UTF-8 BOM 인코딩(엑셀 한글 호환) |

### 예외·엣지 케이스
- 조회 결과 0건이면 표 대신 안내 문구만 표시

---

## S5. 📈 배치 이력

### 목적
`src/batch.py`가 서버 기동 중 자동으로 주기 실행하는 이상탐지 배치의 실행 기록을 조회한다
([PROCESS_SPEC.md §3](PROCESS_SPEC.md)).

### 연동 API
- `GET /batch-runs?limit=`

### 구성 요소

| 요소 | 컴포넌트 | 설명 |
|---|---|---|
| 최대 건수 입력 | `st.number_input` (기본 50) | |
| 조회 버튼 | `st.button` | 클릭 없이도 화면 진입 시 즉시 전체 조회가 실행됨 — 버튼은 수동 새로고침용 |
| 결과 표 | `st.dataframe` + pandas Styler | `findings_count > 0`인 행을 빨간색으로 강조 |
| CSV 내보내기 | `st.download_button` | UTF-8 BOM 인코딩 |

### 예외·엣지 케이스
- 결과 0건이면 표 대신 안내 문구만 표시

---

## 4. 세션 상태(`st.session_state`) 사전

화면 간 공유되는 클라이언트 측 상태 전체 목록 ([streamlit_app.py:88-94](ui/streamlit_app.py#L88-L94)).

| 키 | 타입 | 초기값 | 설명 |
|---|---|---|---|
| `base_url` | str | `http://localhost:8000` | 대상 FastAPI 서버 주소 |
| `thread_id` | str | 새 `uuid4()` | 현재 대화 스레드 — 서버의 `data/checkpoints.db` 상태와 짝을 이루는 키 |
| `chat_log` | list[dict] | `[]` | 화면에 그릴 `{question, response}` 목록(서버 상태의 로컬 사본, 화면 표시 전용) |
| `pending_request` | dict \| None | `None` | 승인 대기 중인 `{tool, args, reason}` |
| `pending_question` | str \| None | `None` | 자주 묻는 질문 버튼이 예약한 질문(다음 렌더링에서 소비되고 초기화) |
| `resume_notice` | str \| None | `None` | 지난 대화를 이어받았는데 그 대화가 승인 대기 상태로 끝났을 때의 경고 문구 |
| `team_choice` | str \| None | - | `TEAM_OPTIONS[team_choice_label]`, 요청마다 `requester_team`으로 전송 |

## 5. 상태 아이콘·색상 범례

| 값 | 아이콘/색상 | 의미 | 사용처 |
|---|---|---|---|
| `answered` | ✅ / 초록 | 정상 응답 | 히스토리 표, 지난 대화 목록 |
| `pending_approval` | 🔒 / 주황 | 승인 대기 중 | 히스토리 표, 지난 대화 목록 |
| `blocked` | 🚫 / 빨강 | 가드레일에 의해 차단 | 히스토리 표 |
| `error` | ⚠️ / 빨강 | 처리 중 오류 | 히스토리 표 |
| `confidence: high/medium/low` | 초록/주황/빨강 인라인 배지 | `answer_chain`이 매긴 답변 확신도 | 대화창 답변 하단 |
