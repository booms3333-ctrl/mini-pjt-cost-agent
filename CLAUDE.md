# 프로젝트 규칙

멀티클라우드 비용 최적화 & 이상 비용 탐지 에이전트 (SERVICE.md 참고). 여기 적힌 건
이 미니 프로젝트에서 실제로 쓰고 있는 방식이다 — 다른 예시나 일반론이 아니라
이 코드베이스의 현재 상태를 기준으로 한다.

## 이 문서를 관리하는 원칙
- 200줄을 넘기지 않는다. 넘어갈 것 같으면 세부 규칙을 이 파일에 계속 채우지 말고
  `.claude/rules/`로 분리한다 (지금은 규칙이 이 정도 분량이라 아직 분리하지 않았다 —
  Day 8~10 작업으로 늘어나면 그때 쪼갠다)
- "깔끔하게", "적절히" 같은 모호한 표현을 쓰지 않는다. 숫자·파일명·함수명으로 못 박은
  제약만 적는다 — 아래 규칙들이 전부 그 형식이다

## 기술 스택
- Python, LangChain(1.x), LangGraph
- 모델은 Amazon Bedrock (`ChatBedrockConverse`). 모델 하나가 아니라 9개 우선순위
  페일오버 목록(`llm_utils.MODEL_PRIORITY`, `MODEL_FAILOVER.md`) — 1순위가 재시도까지
  다 실패해야 다음 순위로 넘어간다
- Agent는 `langchain.agents`의 `create_agent`를 쓰지 않는다 — `StateGraph`로 직접 만든
  Multi-Agent Supervisor(Day 6 기반) + 서브 에이전트별 ReAct 루프(Day 3 기반)다
- RAG 하이브리드 검색(`EnsembleRetriever`/`MultiQueryRetriever`)은
  **`langchain.retrievers`가 아니라 `langchain_classic.retrievers`에서 가져온다**
  (langchain 1.x대에서 이동됨 — `langchain.retrievers`로 쓰면 `ModuleNotFoundError`)
- `ragas` 패키지는 설치·사용 금지: `langchain-community` 0.4+와 호환이 안 돼 이 프로젝트의
  langchain 1.x 스택 전체를 깬다 (직접 겪음). 같은 지표는 `evaluation/ragas_lite.py`로 자체 계산

## 폴더 구조 (제출 규약. 바꾸지 않는다)
```
src/agent.py          Supervisor 그래프 + 서브 에이전트(cost_lookup/anomaly/optimization/execution)
src/tools.py          도메인 도구 (비용조회·이상탐지·절감계산·실행), data/costs.db 직접 조회
src/retriever.py      RAG 파이프라인 (하이브리드 검색 → 쿼리확장 → 리랭킹)
src/guardrails.py      입력 차단·PII 마스킹·도구 결과 소독·HITL 승인 판정
src/authz.py           요청자 팀 접근 범위 강제 (contextvars 기반)
src/observability.py   로컬 JSONL 트레이스 (TraceCollector/Timer)
src/answer_chain.py     LCEL + Pydantic 구조화 출력
src/pipeline.py         가드레일 → 그래프 실행 → 구조화 → 마스킹 (app.py/run_eval.py 공유)
src/app.py              FastAPI 진입점
src/mcp_client.py        MCP 서버 3개(aws/gcp/azure)에 접속하는 클라이언트
mcp_servers/cost_server.py  MCP 서버 본체 (MCP_PROVIDER 환경변수로 파라미터화)
data/                   합성 비용 데이터(costs.db)·정책/가격 문서
evaluation/             test_queries.csv, run_eval.py, ragas_lite.py, round{1,2}_report.md
scripts/generate_data.py  합성 데이터 생성기 (시드 고정, 재현 가능)
```

## 주고받는 형식 (제출 규약)
- `POST /query` — `question`(필수), `thread_id`/`requester_team`(선택) 필드를 읽는다
- 답은 `answer`, `contexts`, `trace` 세 키로 돌려주고, 구조화 결과가 있으면 `structured`를,
  이번 요청에서 실제로 응답한 모델이 있으면 `active_model`을 더한다 (`MODEL_FAILOVER.md` 참고)
- 승인이 필요한 실행(`stop_resource`/`resize_resource`/`send_cost_alert`)은
  `{"status": "pending_approval", "thread_id", "request"}`을 돌려주고
  `POST /query/approve`(`thread_id`, `approved`)로 재개한다

## 코드 규칙
- 파일 하나에 한 가지 역할만 둔다 (가드레일/권한/트레이스/파이프라인을 각각 분리해 둔 이유)
- 도구·주요 함수에는 한국어 docstring을 쓰고, Day 1~7의 어느 패턴을 가져다 썼는지 주석에 남긴다
- 비밀 값은 `.env`에서 읽는다(`load_dotenv`) — 코드에 자격 증명을 적지 않는다
- 도구 이름을 바꾸거나 어느 에이전트에 붙일지 바꾸면 `evaluation/test_queries.csv`의
  `expected_tools`도 같이 갱신한다 (안 그러면 실제로 맞는 답도 채점에서 fail 처리된다 —
  MCP 분리 때 겪은 문제)
- Chroma 벡터스토어는 재색인 전에 반드시 `delete_collection()`으로 기존 컬렉션을 지운다
  (안 지우면 실행할 때마다 같은 청크가 계속 쌓인다 — 직접 겪음)
- MCP 서버(`aws_get_cost` 등)는 별도 자식 프로세스라 `authz`/`observability`의
  contextvars가 안 건너간다 — 팀 단위 권한처럼 요청별로 달라져야 하는 값은
  MCP 도구에 노출하지 말고 로컬 도구 쪽에만 둔다
- 새 도구·에이전트를 async 그래프 노드에 물릴 때는 `llm.invoke()`가 아니라
  `await llm.ainvoke()`를 쓴다 (MCP 도구가 비동기 전용이라 섞어 쓰면 이벤트 루프가 막힌다)

## 문서 동기화 (기능 추가/수정/삭제 시)
기능을 추가·수정·삭제하면 코드만 바꾸고 끝내지 않는다 — 바뀐 성격에 따라 아래 문서도
같은 작업 안에서 갱신한다(문서가 실제 코드와 어긋나면 다음에 참고할 때 더 큰 혼란을 만든다):
- 도구·서브 에이전트 추가/삭제/담당 변경 → `SERVICE.md` §3 표 + 해당 `agents/*.md`
- DB 테이블·컬럼 추가/변경 → `ERD.md`
- API 엔드포인트·요청-응답 처리 흐름 변경 → `PROCESS_SPEC.md`
- `ui/streamlit_app.py` 화면 구성 변경 → `UI_SPEC.md`
- 새 스크립트·새 의존성·실행 절차 변경 → `README.md` 실행 방법 + `requirements.txt`
- 새 `.env` 변수 추가 → `.env.example`
- 가드레일·승인 정책 변경 → `SERVICE.md` §4 + `guardrails.py`의 실제 규칙(정규식·패턴 목록)이 바뀌면 `GUARDRAILS.md`도
- `route_question()`/도구 호출 예산/`judge_output()` 판정 규칙 변경 → `ROUTING_SPEC.md`
- 도구 이름 변경/재배치 → `evaluation/test_queries.csv`의 `expected_tools` (위 코드 규칙과 같은 이유)
- authz 경계·보안 한계가 새로 드러나거나 해소되면 → `LIMITATIONS.md` §1
- `costs.db`/`history.db`/`batch_log.db` 스키마를 대용량 대비 구조(인덱스·파티션 등)로 바꾸면 → `LIMITATIONS.md` §4
- Bedrock 모델 우선순위·페일오버 목록(`llm_utils.MODEL_PRIORITY`) 변경 → `MODEL_FAILOVER.md`
- 요청 타임아웃/MCP 재기동/HITL 승인 TTL/턴 단위 LLM 호출 예산 값이나 동작 변경 → `SAFEGUARDS.md`
- 위 목록에 안 맞는 변경이라도, "이 변경 때문에 기존 문서 중 하나가 거짓말을 하게 됐는가"를 먼저 확인한다

## 하지 말 것
- 요청하지 않은 파일을 새로 만들지 않는다
- 기존 파일을 통째로 다시 쓰지 않는다. 바뀐 부분만 고친다
- `guardrails.input_guard()`에 "이건 위험해 보이니 차단" 식 규칙을 함부로 추가하지 않는다
  — 실행 도구는 이미 `needs_approval()` + `interrupt()`로 승인 게이트를 타므로,
  입력 단계에서 또 막으면 정상적인 HITL 요청까지 승인 절차에 닿기도 전에 차단해버린다
  (실제로 이 문제로 규칙 하나를 통째로 제거한 적이 있다)
- `test_queries.csv`를 통과시키려고 프롬프트에 특정 테스트 문항을 그대로 인용해 넣지 않는다
  (일반적인 지시로 해결이 안 되면, 프롬프트를 더 밀어붙이는 대신 해당 문항의 기대값을
  현실적으로 낮추고 이유를 note에 남긴다)
