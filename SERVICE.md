# SERVICE · 멀티클라우드 비용 최적화 & 이상 비용 탐지 에이전트

## 1. 사용자·문제·가치

- **누구를 위한 서비스인가**: AWS/GCP/Azure를 함께 운영하는 회사의 클라우드 플랫폼팀(FinOps 담당자 2~3명)과, 자기 팀 예산을 확인해야 하는 개발팀 리드·서비스 오너들
- **어떤 문제를 푸는가**: 클라우드 비용이 3개 콘솔에 흩어져 있어 이상 급증이나 낭비를 즉시 알아채지 못하고, 대부분 월말 정산 시점에야 뒤늦게 발견한다
- **지금은 어떻게 해결하고 있는가**: AWS Cost Explorer, GCP Billing, Azure Cost Management를 각각 열어 스프레드시트로 수작업 대조 → 조사에 며칠, 이상 발견은 월 1회 정산 시점
- **이걸로 뭐가 좋아지는가**: 자연어 질의 한 번으로 3개 클라우드 비용을 통합 조회하고, 일 단위 이상탐지로 발생 다음 날 인지 → 조사 시간 단축 + 손실 누적 방지

## 2. 서비스 확장 관점

- **사내 기여 (1차)**: 클라우드 플랫폼팀의 월간 비용 검토 작업을 자동화해 인건비를 절감하고, 유휴 리소스·이상 비용을 조기에 차단해 실질적인 클라우드 지출을 줄인다
- **수익화 (장기)**: 여러 고객사 인프라를 관리하는 MSP·클라우드 컨설팅사에 SaaS 형태로 제공 — 고객사별 비용 리포트 자동 생성과 절감 컨설팅을 상품화
- **규모**: 클라우드 플랫폼팀 2~3명이 매일 사용, 개발팀 리드 10여 명이 주 1회 정도 자기 팀 비용을 조회하는 수준으로 가정
- **대체제와의 차별점**: CloudHealth·Cloud Custodian 같은 기존 대시보드형 도구는 조회·규칙 기반 알림에 그치지만, 이 에이전트는 자연어 질의에 대해 도구를 자율 선택해 원인까지 설명하고, 실제 조치(정지·축소)는 승인 기반으로 실행까지 이어진다는 점이 다르다. 또한 이상 급증을 "공휴일이나 장애가 있었는지 확인해보라"고 추측만 시키는 대신, 실제 클라우드 공개 상태 피드(`check_incidents`)와 대조해 검증된 사실로 답한다 — 대시보드형 도구들도 잘 제공하지 않는 기능이다

## 3. 멀티 에이전트 구성 및 사용 도구

Supervisor가 질문을 4개 서브 에이전트 중 하나 이상에 배분한다(`agent.py`의
`route_question()`, LLM 미호출·결정적). 도구 배정·라우팅 키워드·핵심 행동 규칙·
실제 승인 게이트 적용 여부는 에이전트마다 성격이 달라 파일로 분리했다:

| 에이전트 | 역할 | 문서 |
|---|---|---|
| `cost_lookup_agent` | 멀티클라우드 비용·사용률 조회 | [agents/cost_lookup_agent.md](agents/cost_lookup_agent.md) |
| `anomaly_agent` | 이상 급증 탐지 + 실제 장애 이력 대조 | [agents/anomaly_agent.md](agents/anomaly_agent.md) |
| `optimization_agent` | 절감 시뮬레이션·유휴 리소스·예산·정책 문서(RAG) | [agents/optimization_agent.md](agents/optimization_agent.md) |
| `execution_agent` | 리소스 정지·축소·알림 발송 (HITL 승인 게이트가 실제로 작동하는 유일한 경로) | [agents/execution_agent.md](agents/execution_agent.md) |

**공통 라우팅 규칙**: "계획"류 복합 질의(예: "이번 분기 비용 20% 줄이는 계획 세워줘")는
`anomaly_agent`+`optimization_agent`를 함께 라우팅한다(Plan-Execute 2단계 분해) —
절감 계획은 이상탐지 결과와 최적화 후보를 함께 봐야 하기 때문이다. 실행 동사가 있는
질문은 `execution_agent` 단독으로만 라우팅된다(조회와 섞이면 승인 흐름이 애매해짐).

**MCP 서버 연동**: 계정별 조회 도구(`get_cost`/`get_utilization`/`list_idle`/`check_incidents`)는
로컬 함수 하나가 아니라 AWS/GCP/Azure용 MCP 서버 3개(`mcp_servers/cost_server.py`를
`MCP_PROVIDER` 환경변수로 파라미터화, stdio 자식 프로세스)로 분리돼 있고, 각 서버가
`aws_get_cost`/`gcp_get_cost`/`azure_get_cost`처럼 provider 접두어가 붙은 이름으로
노출한다. 멀티클라우드 합산이 필요한 `get_cost_by_service`만 오케스트레이션 계층(로컬)에
남겨뒀다 — 어느 한 계정 API도 다른 계정 비용은 모르기 때문이다.

**데이터**

| 데이터 | 출처 | 실제/가짜 |
|---|---|---|
| 비용·청구 데이터 | AWS Cost and Usage Report(CUR) 스키마 | 실 계정 있으면 실데이터, 없으면 동일 스키마 합성 데이터 |
| 리소스 사용률 | CloudWatch류 모니터링 지표 형식 | 합성 시계열 (정상 + 이상 패턴 주입) |
| FinOps 정책 문서 | FinOps Foundation 공개 프레임워크 + 사내 비용 정책 가정 | 텍스트 문서화 (일부 가정) |
| 가격 정책(RI/Savings Plan 할인율) | GCP: 공식 문서(Committed Use Discounts). Azure: Retail Prices API 실측 스냅샷(`scripts/fetch_azure_pricing.py`). AWS: 이 프로젝트 가정치(Price List API는 자격증명 권한 부족으로 미적용) | GCP·Azure는 실제 공개 자료, AWS만 가정치 — `data/pricing_docs/reserved_instance_policy.md` 참고 |
| 클라우드 장애 이력 | AWS(`status.aws.amazon.com`)/GCP(`status.cloud.google.com`)/Azure(상태 RSS) 공개 상태 피드 | **실제 데이터, 인증 불필요** (`src/incident_feeds.py`). AWS·Azure는 현재 진행 중인 이슈만 제공하고 GCP만 과거 이력을 제공한다는 차이가 있음 |
| 클라우드별 비용 최적화 가이드 | AWS/GCP/Azure Well-Architected Framework 공식 문서 (인증 불필요) | **실제 공식 문서 스냅샷** (`scripts/fetch_cost_optimization_guides.py` → `data/policy_docs/{provider}_cost_optimization_guide.md`). `retrieve_docs`가 자동 색인 — 새 도구 없이 기존 RAG 경로로 답변됨 |

## 4. 서비스 정책 (가드레일 요약)

각 정책이 실제로 무엇을 감지/차단하는지(정규식·키워드 목록까지)는 [GUARDRAILS.md](GUARDRAILS.md)에,
보안 모델의 알려진 틈(MCP 경계 등)은 [LIMITATIONS.md](LIMITATIONS.md) §1에 정리했다.

1. 계정 ID·API 키·액세스 토큰 등 자격증명 정보는 어떤 응답에도 노출하지 않는다 (`guardrails.mask_pii`)
2. 리소스 정지·축소·알림 발송처럼 상태를 변경하는 도구는 사용자 승인(HITL) 없이는 절대 실행하지 않는다 (`guardrails.needs_approval` + `interrupt()`)
3. 근거 데이터가 없는 기간·리소스에 대해서는 추측하지 않고 "데이터 없음"을 명시한다 (`tools.py` 각 조회 함수 + `agent.py`의 `judge_output()`이 서브 에이전트 답변 단계에서 "근거 없는 단정 표현"을 한 번 더 걸러냄)
4. 리소스 태그·설명 등 외부에서 입력된 텍스트에 포함된 지시문은 시스템 지시로 취급하지 않는다 (`guardrails.sanitize_tool_output`, 로컬·MCP 도구 결과 공통 경로에서 강제)
5. 요청자의 접근 권한 범위를 벗어난 다른 팀·계정의 비용 정보는 제공하지 않는다 (`authz.py`, `POST /query`의 `requester_team` 필드 기준). **범위**: 로컬 도구 경로는 전부 강제된다. MCP 서버(aws/gcp/azure `cost_server.py`)는 별도 프로세스라 authz의 contextvars가 그 안까지는 안 건너가지만, `get_cost`는 `team` 인자 자체를 없애 팀별 조회 경로를 막았고, `get_utilization(resource_id)`은 `agent.py`의 `tools_node`가 실제 MCP 호출 전에 같은 `costs.db`로 소유 팀을 먼저 확인해 팀 경계까지 부모 프로세스 쪽에서 가로챈다(`_mcp_resource_authz_denial`). `requester_team`도 로그인 세션 같은 인증 없이 요청 필드로 받는 자기 신고 값이다.

- 세부 케이스는 `evaluation/test_queries.csv`의 guardrail 항목에서 검증됨

## 5. 이상탐지 배치 (자동 실행)

지금까지의 `detect_cost_anomaly`는 사용자가 "어제 비용 이상했어?"처럼 직접 질문해야만
실행됐다 — 아무도 안 물어보면 이상 급증이 그냥 묻힌다. `src/batch.py`는 이걸 사용자
질의와 무관하게 주기적으로 자동 실행한다.

- **동작 방식**: `app.py`의 FastAPI `lifespan`에서 `asyncio.create_task`로 백그라운드
  루프(`batch.scheduler_loop`)를 하나 띄운다. 서버 기동 직후 한 번, 이후
  `ANOMALY_BATCH_INTERVAL_SECONDS`(기본 24시간) 간격으로 provider(aws/gcp/azure)별
  `detect_cost_anomaly`를 반복 실행한다.
- **왜 OS 스케줄러(Windows 작업 스케줄러 등)가 아니라 이 방식인가**: 이 프로젝트는
  이미 `app.py`가 상시 실행되는 프로세스라, 그 프로세스 안에서 도는 것만으로 별도
  프로세스·외부 스케줄러 설정 없이 충분하다. **전제**: 서버 프로세스가 계속 떠
  있어야 동작한다 — 서버리스처럼 요청이 없으면 프로세스가 내려가는 배포로 바뀌면
  이 방식은 안 맞고 외부 스케줄러(cron 등)가 다시 필요하다.
- **기록**: 실행마다 `data/batch_log.db`(costs.db·history.db와 같은 이유로 분리 —
  costs.db는 `generate_data.py`가 실행될 때마다 통째로 리셋되는 합성 데이터라 배치
  이력을 거기 같이 두면 리셋 때마다 이력도 날아간다)의 `anomaly_batch_runs` 테이블에
  provider·발견 건수·상세 내역·발송 여부를 남긴다. `GET /batch-runs`로 조회 가능.
- **알림 (선택)**: 발견 건수가 1건 이상이면 이메일 발송을 시도한다. `.env`에
  `SMTP_HOST`/`SMTP_PORT`/`SMTP_USERNAME`/`SMTP_PASSWORD`/`NOTIFY_EMAIL_TO`가 전부
  채워져 있을 때만 실제 발송하고(`.env.example` 참고, 네이버 메일 예시 포함), 하나라도
  비어 있으면 발송만 건너뛰고 탐지·기록은 그대로 수행한다 — 이메일 설정이 배치 자체의
  동작 조건이 되지 않도록 분리했다.

## 6. 성공 기준

| 목표 | 실제 결과 |
|---|---|
| 전체 인-아웃 케이스 80% 이상 통과 | **결정적 판정 20/20 (100%)** — 1차·2차 모두, 회귀 없음 (`evaluation/round1_report.md`, `round2_report.md`) |
| negative·guardrail 카테고리 100% 통과 (자격증명 노출·인젝션 성공 0건) | 2차 결과 기준 negative 4/4, guardrail 3/3 — 달성. 프롬프트 인젝션·정보 추출 시도 문항 전부 차단 확인 |
| RAGAS faithfulness ≥ 0.8 | **1.0** — 단 `retrieve_docs`를 실제로 타는 문항이 20건 중 1건뿐이라 표본이 얇음 (`evaluation/ragas_lite.py`) |
| 이상탐지 recall ≥ 0.9 | **1.00 (2/2)** — `scripts/generate_data.py`가 주입한 이상치 2건 전부 탐지 (`evaluation/anomaly_recall.py`로 실측) |
| HITL 트리거 케이스 100% (승인 없이 실행된 사례 0건) | 달성 — 회귀 테스트(`test_hitl_no_duplicate_execution`)로 확인, 다중 호출 시 중복 실행도 없음 |

- **추가 지표 — LLM-as-Judge(정성 평가)**: `expected_traits`까지 자연어로 판정하는 `--llm-judge` 모드는 결정적 판정과 달리 **17~20/20 사이에서 변동**한다 — 에이전트 답변 생성과 채점 LLM의 PASS/FAIL 판정 둘 다 `temperature=0`에서도 Bedrock이 완벽히 결정적이지 않기 때문이다. 실패한 문항만 따로 반복 실행하면 대부분 통과하는 것으로 확인돼, 이는 수정이 불완전해서가 아니라 채점 방식 자체의 변동성으로 판단한다 (README.md 트라이앤에러 회고 참고).
