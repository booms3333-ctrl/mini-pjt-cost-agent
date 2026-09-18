# GUARDRAILS · 가드레일 규칙 카탈로그

[SERVICE.md](SERVICE.md) §4는 가드레일을 5개 정책 문장 + 함수명 링크로만 요약한다.
이 문서는 그 문장들이 실제로 **무엇을 감지하고 무엇을 의도적으로 안 막는지**를
`src/guardrails.py`(전부 LLM 미호출, 같은 입력엔 항상 같은 출력) 기준으로 펼쳐서
정리한다. 규칙을 추가·수정할 때 코드를 처음부터 다시 읽지 않아도 되도록 하는 게
목적이다 — 규칙을 바꾸면 이 문서도 같이 갱신한다([CLAUDE.md](CLAUDE.md) 문서 동기화 원칙).

## 1. 미들웨어 파이프라인 순서

`guardrails.MIDDLEWARE_ORDER`가 선언한 순서이고, 실제 호출은 `pipeline.py`에 흩어져
있다. **마스킹이 로깅보다 앞이어야 로그에 원본이 안 남는다**는 게 이 순서의 핵심
제약이다.

| 순서 | 이름 | 실제 구현 | 호출 시점 |
|---|---|---|---|
| 1 | `InputGuardMiddleware` | `guardrails.input_guard()` | `pipeline.ask()` — 그래프 실행 **전**, 질문 원문 검사 |
| 2 | `MaskingMiddleware` | `guardrails.mask_pii()` / `mask_pii_deep()` | `pipeline.finalize()` — 답변 텍스트, `contexts`/`trace`, `pending_approval` 요청 인자까지 재귀 마스킹 |
| 3 | `OutputCheckMiddleware` | `agent.judge_output()` | 서브 에이전트 ReAct 노드 안, 도구 호출이 끝나고 텍스트를 뽑은 직후 (도구 결과 자체는 `sanitize_tool_output()`이 별도로 소독 — 아래 4절) |
| 4 | `HistorySummaryMiddleware` | `pipeline._maybe_summarize_history()` | 그래프 실행 후, 메시지 20개 초과 시에만 |
| 5 | `LoggingMiddleware` | `qa_history.record()` | `pipeline.py`/`app.py` — 마스킹이 끝난 값을 `history.db`에 기록 |

`sanitize_tool_output()`은 이 5단계 목록에 이름이 없다 — 도구 **결과**(외부 데이터)를
대상으로 하는 별도 경로라서다. 아래 4절 참고.

## 2. `input_guard()` — 입력 차단 규칙

한 단어가 아니라 **"의도의 조합"**을 본다(예: "무시"라는 단어 하나만으론 안 걸리고,
"무시" + "지시"류 단어가 같은 문장에 같이 있어야 걸린다). 순서대로 검사하고, 하나라도
걸리면 즉시 차단한다.

| # | 감지 조합 | 실제 패턴/키워드 | 차단 사유 문구 |
|---|---|---|---|
| 1 | 오버라이드 동사 **+** 지시 대상 | `_OVERRIDE_VERBS`("무시"/"잊"/"무효화"/ignore/disregard/override 등) **+** `_INSTRUCTION_TARGETS`("지시"/"규칙"/system prompt 등) | "지시를 덮어쓰려는 요청으로 판단해 차단했습니다" |
| 2 | 인젝션 마커 | `###\s*new instruction`, `new instruction\s*:`, `ignore (all )?previous instructions` | "프롬프트 주입 마커가 감지되어 차단했습니다" |
| 3 | 역할 재정의 시도 | `너의/당신의/니 역할은`, `역할을/로 부여/전환`, `you are now`, `\bdan\b`, `관리자 모드로 전환` | "역할 재정의 시도로 판단해 차단했습니다" |
| 4 | 탈옥/무제한 모드 | `개발자 모드`, `developer mode`, `제한/제약 없이`, `필터 없는`, `무제한 (ai/모드)`, `unrestricted`, `jailbreak` | "탈옥/무제한 모드 요청으로 판단해 차단했습니다" |
| 5 | 셸 파괴 명령 | `rm -rf`, `format (the )?(disk\|drive\|c:)`, `shutdown -h`, `kill -9` | "시스템을 직접 파괴하는 명령이 감지되어 차단했습니다" |
| 6 | 추출 동사 **+** 추출 대상 | 강한 동사(출력해/보여줘/reveal/show 등) 또는 (약한 동사(알려줘/말해줘) **이면서** 절차 질문(`_PROCEDURAL_WORDS`: 방법/절차/how to)이 **아닐 때**) **+** `_EXTRACTION_TARGETS`(시스템 프롬프트/api key/시크릿/계정 정보/청구 정보 등) | "내부 정보/계정 정보 추출 시도로 판단해 차단했습니다" |
| 7 | 추출 동사 **+** 인프라 설정 대상 **+** (값 덤프 또는 시크릿 단어) | 6과 같은 추출 동사 **+** `_INFRA_SECRET_TARGETS`(환경 변수/.env/설정 파일) **+** (`_VALUE_DUMP_WORDS`: 값/내용/전부/모두 또는 `_SECRET_WORDS`: 키/비밀번호/토큰) | "환경설정/자격정보 통째 노출 요청으로 판단해 차단했습니다" |
| 8 | "그대로 따라해" **+** 시크릿 단어 | `_REPEAT_AFTER_ME`(그대로 따라 해/repeat after me/say exactly) **+** `_SECRET_WORDS` | "민감한 값을 그대로 출력하게 하려는 시도로 판단해 차단했습니다" |

규칙 6의 "절차 질문이면 약한 동사는 안 걸리게" 예외는 실제로 겪은 오탐(예: "시스템
프롬프트 작성 방법 알려줘" 같은 정상 질문이 차단되던 문제)을 고치며 넣은 것이다.

### 의도적으로 안 넣은 규칙

Day 5 원본엔 "파괴적 명령 + 스코프 + 실행 동사" 조합을 입력 단계에서 통째로 차단하는
규칙이 있었는데, 이 프로젝트는 **일부러 뺐다**. `stop_resource`/`resize_resource`는
`RISK_LEVELS`에서 이미 무조건 `destructive`로 분류돼 `needs_approval()`이 항상 승인을
요구하고, `execution_agent`가 `interrupt()`로 실제 사람 승인을 받은 뒤에만 실행한다.
입력 단계에서 "정지해줘" 같은 평범한 표현까지 더 막으면, 정상적으로 승인 절차를 밟아야
할 요청이 그 절차에 닿기도 전에 차단돼 버린다([SERVICE.md](SERVICE.md) 정책 2번과
충돌) — 실제로 이 문제로 규칙 하나를 통째로 제거한 적이 있다([CLAUDE.md](CLAUDE.md)
"하지 말 것" 참고).

## 3. `mask_pii()` / `mask_pii_deep()` — 출력 마스킹

`mask_pii()`는 문자열 하나, `mask_pii_deep()`은 dict/list를 재귀적으로 순회해 문자열
값을 전부 마스킹한다(HITL 승인 요청의 `args`, `contexts`/`trace` 같은 자유 형식 중첩
구조에 자격증명이 섞여 나올 수 있는 경로용 — 코드 리뷰에서 이 경로들이 `mask_pii()`를
아예 안 거치고 있던 걸 발견해서 추가했다).

| # | 대상 | 패턴 | 치환 |
|---|---|---|---|
| 1 | JWT | `eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+` | `[REDACTED_JWT]` |
| 2 | AWS 액세스 키 | `AKIA[0-9A-Z]{16}` | `[REDACTED_AWS_KEY]` |
| 3 | AWS ARN(계정ID 포함) | `arn:aws:[a-z0-9-]+:[a-z0-9-]*:\d{12}:[\w/:-]+` | `[REDACTED_ARN]` |
| 4 | 이메일 | `[\w.+-]+@[\w-]+\.[\w.-]+` | `[REDACTED_EMAIL]` |
| 5 | 전화번호 | `01[0-9][-\s]?\d{3,4}[-\s]?\d{4}` | `[REDACTED_PHONE]` |
| 6 | 사번 | `\bE\d{6}\b` | `[REDACTED_ID]` |

이 프로젝트의 합성 데이터엔 이 패턴에 실제로 걸리는 값이 거의 없다 — 실 서비스로
확장해 사용자가 자유 텍스트(리소스 태그·메모 등)를 입력하게 되면 이 경로가 방어선이
된다.

## 4. `sanitize_tool_output()` — 도구 결과 소독 (가드레일 규칙 4)

`input_guard()`는 사용자의 최초 질문 전체를 검사해서 **통째로 거부**하지만, 도구
결과는 거부할 대상이 아니라 사용자에게 그대로 보여줘야 하는 데이터다. 그래서 이 함수는
`_INJECTION_MARKERS` + `_ROLE_REASSIGN_PATTERNS` + `_JAILBREAK_PATTERNS`(1절 표의
2/3/4번 패턴)에 걸리는 부분만 `[제거됨: 지시문으로 의심되는 내용]`으로 치환하고 나머지
내용은 그대로 둔다 — **차단이 아니라 부분 무력화**라는 점이 `input_guard()`와 다르다.

지금 쓰는 합성 데이터엔 이런 악성 태그가 없어서 평소엔 아무것도 안 바뀐다. 실 서비스로
확장해 사용자가 리소스 이름·태그를 직접 입력할 수 있게 되면(예: `resources.team`을
사용자가 직접 편집), 이 경로가 "리소스 태그·설명 등 외부 입력의 지시문은 시스템 지시로
취급하지 않는다"는 정책을 실제로 강제하는 지점이 된다.

## 5. `needs_approval()` / `RISK_LEVELS` — HITL 승인 게이트

| 도구 | 위험도 | 승인 필요? |
|---|---|---|
| `get_cost_by_service`, `get_resource_utilization`, `detect_cost_anomaly`, `estimate_savings`, `list_idle_resources`, `retrieve_docs` | `read` | 불필요 — 자동 실행 |
| `send_cost_alert` | `write` | 필요 |
| `stop_resource`, `resize_resource` | `destructive` | 필요 **+ 이중 확인** |
| (등록 안 된 도구) | - | 필요 — "모르는 것은 막는다" |

승인 판정 자체는 결정적 룰이고, 실제 게이트는 `execution_agent`가 `interrupt()`로
그래프를 멈추는 것으로 강제된다(LLM이 스스로 "승인 필요합니다"라고 말만 하고 도구
호출 자체를 안 하면 이 게이트가 아예 작동하지 않는다는 걸 여러 번 겪었다 —
[agents/execution_agent.md](agents/execution_agent.md) 참고).

## 6. SERVICE.md §4 정책 문장 ↔ 실제 구현 매핑

| SERVICE.md 정책 | 이 문서의 절 |
|---|---|
| 1. 자격증명 정보 미노출 | 3절 (`mask_pii`) |
| 2. 상태 변경 도구는 승인 없이 실행 안 함 | 5절 (`needs_approval` + `interrupt()`) |
| 3. 근거 없으면 추측하지 않음 | `judge_output()` — [ROUTING_SPEC.md](ROUTING_SPEC.md) §3(판정 로직은 라우팅과 같은 "결정적 판단 로직" 범주라 거기서 다룬다) |
| 4. 외부 입력의 지시문은 시스템 지시로 취급 안 함 | 4절 (`sanitize_tool_output`) |
| 5. 권한 범위 밖 데이터 미제공 | `src/authz.py` — [LIMITATIONS.md](LIMITATIONS.md) §1(보안 모델) |

정책 1번은 `input_guard()`가 아니라 `mask_pii()`(출력 단계)로 지켜진다는 점에 주의 —
`input_guard()`는 SERVICE.md 5개 정책 중 어느 것에도 직접 안 걸리는 **더 앞단의
방어선**(프롬프트 인젝션·탈옥·정보 추출 시도 자체를 차단)이라, 이 카탈로그에서 별도
1절로 다뤘다.
