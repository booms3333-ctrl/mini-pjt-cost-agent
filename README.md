# 미니 PJT: 멀티클라우드 비용 최적화 & 이상 비용 탐지 에이전트

## 무엇을 푸나

AWS/GCP/Azure에 흩어진 클라우드 비용을 자연어 질의로 통합 조회하고, 이상 급증을 조기에 탐지하며,
근거 있는 절감안을 제안하고, 실제 리소스 변경은 사람 승인을 거쳐서만 실행하는 FinOps 에이전트.

## 활용한 패턴 (Day 1~7)

- Day 1: LCEL 구조화 출력 — 서브 에이전트의 원시 답변을 `StructuredAnswer`(Pydantic) 스키마로 정규화하는 `prompt | llm | JsonOutputParser` 체인 (`src/answer_chain.py`, `build_triage_chain`과 동일 구조)
- Day 2: RAG — FinOps 정책·가격 정책 문서를 하이브리드(BM25+벡터) 검색 → 쿼리 확장(`MultiQueryRetriever`, LLM이 질문을 3버전으로 변형) → 리랭킹(LLM이 관련도 순 재정렬, LCEL+Pydantic) 3단계로 조회 (`retrieve_docs`, `src/retriever.py`)
- Day 3: ReAct — 질의 유형에 따라 비용조회/이상탐지/절감계산 도구를 자율 선택
- Day 4: MCP 서버 연동 + 도구 다중 — AWS/GCP/Azure Cost API를 MCP 서버 3개(stdio, 각각 자식 프로세스)로 노출하고 `MultiServerMCPClient`로 붙여 씀, 한 질의에 로컬·MCP 도구 여러 개 결합
- Day 5: 가드레일·HITL·미들웨어 — 자격증명 마스킹·프롬프트 인젝션 방어, `stop_resource`/`resize_resource`/`send_cost_alert` 승인 게이트, 대화 이력 요약·API 재시도
- Day 6: Multi-Agent Supervisor — 비용조회 / 이상탐지 / 최적화제안 / 실행 4개 서브 에이전트로 역할 분할·위임
- Day 7: 평가 + Observability — `TraceCollector`(`src/observability.py`)를 실제 실행 경로에 심어 llm/tool 호출마다 `data/traces/<thread_id>.jsonl`을 남기고, 같은 `TraceCollector`/`run_eval`/`compare_eval`을 `evaluation/eval_lib.py`가 재사용해 `test_queries.csv` 20건을 자동 채점하는 `evaluation/run_eval.py` 작성. `.env`에 `LANGCHAIN_TRACING_V2`+`LANGCHAIN_API_KEY`를 채우면 LangSmith도 코드 변경 없이 추가로 붙는다

추가로 Plan-Execute·장기 메모리(Day 범위 밖 패턴)를 적용해 "분기 절감 계획" 같은 복합 질의를 단계 분해하고,
사용자별 비용 추이·조치 이력을 LangGraph Store에 저장한다.

## 아키텍처

```
User Query (POST /query) ── guardrails.input_guard() 차단 검사
   │
   ▼
[Supervisor] ── route_question() (키워드 기반, LLM 미호출)
   ├─▶ [cost_lookup_agent]    Day 3 ReAct 루프: get_cost_by_service(로컬, 멀티클라우드 합산)
   │                          + aws/gcp/azure_get_cost, aws/gcp/azure_get_utilization (MCP)
   ├─▶ [anomaly_agent]        Day 3 ReAct 루프: detect_cost_anomaly (로컬)
   ├─▶ [optimization_agent]   Day 3 ReAct 루프: estimate_savings, retrieve_docs (로컬)
   │                          + aws/gcp/azure_list_idle (MCP)
   └─▶ [execution_agent]      decide(LLM, 도구 선택) -> approve(승인 확인)
                                 needs_approval() = True 면 interrupt() 로 그래프 정지
                                 POST /query/approve 로 재개 -> 승인된 것만 실제 실행
   │
   ▼
answer_chain (LCEL, 패턴 1) 로 원시 답변을 {summary, key_numbers, confidence,
needs_followup} Pydantic 스키마로 정규화 → guardrails.mask_pii() 마스킹
→ {answer, contexts, trace, structured} 반환

MCP 서버 3개 (mcp_servers/cost_server.py를 MCP_PROVIDER=aws/gcp/azure로 각각 기동, stdio)
   └─ src/mcp_client.py 의 MultiServerMCPClient가 자식 프로세스로 띄우고 도구를 가져옴
   └─ 각 서버는 자기 계정 리소스만 조회 가능 (다른 계정 리소스 조회 시 "속한 리소스가 아님" 응답)
```

- Supervisor는 pending 목록을 하나씩 소진하며 서브 에이전트에 위임하고, 각 서브 에이전트가 끝나면 다시 supervisor로 돌아온다 (Day 6 `route_question`/`build_supervisor` 구조)
- 조회형 서브 에이전트 3개는 Day 6 원본(도구 설명만 프롬프트로 던짐)과 달리 Day 3의 `bind_tools`+`ToolNode` 루프를 그대로 내장해 실제로 SQLite/MCP를 조회한다
- MCP 도구는 원격 프로세스와 stdio로 통신하는 비동기 전용 도구라 그래프 전체를 `ainvoke`로 돌린다 (`app.py`의 두 엔드포인트도 `async def`)
- `execution_agent`만 decide(LLM 호출)와 approve(LLM 미호출, `interrupt()`) 두 단계로 분리했다 — 승인 재개 시 LLM을 중복 호출하지 않기 위함
- `get_cost_by_service`(멀티클라우드 합산)만 로컬로 남긴 이유: 어느 한 계정 API도 다른 계정 비용은 모르므로, 클라우드 3곳을 합산하는 건 오케스트레이션 계층(우리 에이전트)의 몫이지 개별 MCP 서버의 몫이 아니다
- 트레이스는 `contextvars`로 요청 하나(=`pipeline.ask`/`resume` 한 번) 동안 전역으로 공유한다 — 그래프 노드 시그니처를 안 건드리고 `observability.get_collector()`로 같은 콜렉터를 찾게 하기 위함
- **주의**: 이 저장소의 langchain은 1.x대라(requirements.txt `langchain>=0.3`는 하한선일 뿐), `EnsembleRetriever`/`MultiQueryRetriever`가 `langchain.retrievers`가 아니라 `langchain_classic.retrievers`에 있다. 실제로 이 차이 때문에 `ModuleNotFoundError`가 났던 걸 발견해서 고쳤다 — `pip install -r requirements.txt`로 새 환경을 만들 때도 `langchain-classic`이 같이 깔리는지 확인할 것
- 상세 설계는 [SERVICE.md](SERVICE.md)(서브 에이전트별 상세는 `agents/` 폴더), DB 구조는 [ERD.md](ERD.md), 각 프로세스의 단계별 사양은 [PROCESS_SPEC.md](PROCESS_SPEC.md), 로컬 데모 UI 화면 구성은 [UI_SPEC.md](UI_SPEC.md) 참고

## 구현 현황

| 항목 | 상태 |
|---|---|
| LCEL 구조화 출력(1) · RAG(3, 하이브리드+쿼리확장+리랭킹 전부) · ReAct(2) · 도구 다중(4) · MCP 서버 연동(5) · 가드레일(6) · HITL(7) · Multi-Agent Supervisor(9) · Plan-Execute 간이형(10) · Observability(11, 로컬 트레이스) | 구현 완료. 실제 AWS Bedrock으로 `evaluation/run_eval.py --round 1` 20문항을 돌려 전 구간(서브 에이전트 ReAct 루프, MCP 도구 호출, answer_chain 구조화, HITL interrupt/resume, RAG 검색·리랭킹) 실행 검증 완료 — 20/20 통과 (트라이앤에러 회고 참고) |
| Observability(11) — LangSmith/LangFuse | 코드는 준비됨(`.env`에 `LANGCHAIN_TRACING_V2`+`LANGCHAIN_API_KEY` 설정만 하면 자동 연동), 이 샌드박스엔 계정이 없어 실제 전송은 미검증 |
| 미들웨어(8) — 요약/재시도 | 둘 다 구현 완료. API 재시도는 `llm_utils.with_bedrock_retry`(모든 Bedrock LLM 호출에 적용, ThrottlingException 등에 지수 백오프 3회). 대화 이력 요약은 `pipeline._maybe_summarize_history`(메시지 20개 초과 시 오래된 부분을 LLM 요약 1개로 교체, `RemoveMessage`로 체크포인트에서 실제로 제거) — 실 Bedrock으로 같은 thread_id에 10턴 연속 질의해 10턴째(메시지 20개)에 트리거되어 7개로 줄어드는 것까지 확인 |
| 평가(12) — pass/fail 자동화 · LLM-as-Judge | 구현 완료 (`evaluation/run_eval.py`). CSV 파싱·결정적 판정(forbidden/expected_tools)·리포트 생성·`compare_eval` 라운드 비교까지 가짜 답변 함수로 전 구간 실행 검증 완료. LLM-as-Judge(`--llm-judge`)는 실 Bedrock으로도 돌려봤다 — 다만 run-to-run 변동성이 있다(트라이앤에러 회고 참고) |
| 평가(12) — RAGAS | 구현 완료, `ragas` 패키지는 안 씀 (`evaluation/ragas_lite.py`). `ragas`는 langchain-community 0.4+ 와 호환이 안 돼(버전 무관하게 재현됨 — 0.2.15/0.4.3 둘 다 확인) 설치 자체가 이 프로젝트의 langchain 1.x 스택을 깬다. 같은 지표(faithfulness·answer_relevancy·context_precision, LLM-as-Judge)를 직접 구현해 `--ragas` 옵션으로 계산. 실 Bedrock으로 전부 1.0(목표 ≥0.8 충족) — 단 `retrieve_docs`를 타는 문항이 1건뿐이라 표본이 얇다 |
| 이상탐지 recall (SERVICE.md 목표 ≥0.9) | 구현 완료 (`evaluation/anomaly_recall.py`) — `scripts/generate_data.py`가 주입한 정답과 `detect_cost_anomaly()` 실제 탐지 결과를 비교. 실 실행 결과 recall 1.00 (2/2) |
| 이상탐지 배치 (자동 실행, 사용자 질의 불필요) | 구현 완료 (`src/batch.py`, 상세는 SERVICE.md §5). `app.py` lifespan에서 asyncio 백그라운드 태스크로 provider별 `detect_cost_anomaly`를 주기 실행 → `data/batch_log.db`에 기록, 발견 시 이메일 발송(선택, `.env`의 SMTP_* 설정 시에만). 서버 기동 직후 실제 실행해 aws 2건·gcp 2건·azure 1건 탐지·기록·`GET /batch-runs` 조회까지 확인 |

## 실행 방법

```bash
# 1. 의존성 설치
pip install -r requirements.txt

# 2. 합성 데이터 생성 (표준 라이브러리만 사용, 시드 고정으로 재현 가능)
python scripts/generate_data.py

# 2-1. Azure RI 할인율 스냅샷 갱신 (선택 — 인증 불필요, 안 돌리면 저장된 스냅샷/폴백값 사용)
python scripts/fetch_azure_pricing.py

# 2-2. AWS/GCP/Azure 공식 비용 최적화 가이드 스냅샷 갱신 (선택 — 인증 불필요,
#      안 돌리면 저장된 스냅샷 사용). retrieve_docs가 data/policy_docs/*.md를
#      자동 색인하므로 새 도구·에이전트 코드 없이 바로 답변에 반영된다.
python scripts/fetch_cost_optimization_guides.py

# 3. 환경변수 설정 (API 키 등)
cp .env.example .env

# 4. 서버 실행
uvicorn src.app:app --reload --port 8000

# 5. 질의 예시 (승인이 필요 없는 조회형)
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "이번 달 AWS EC2 비용 총액이 얼마야?"}'
# -> {"answer": "...", "contexts": [...], "trace": [...],
#     "structured": {"summary": "...", "key_numbers": ["$332.35"], "confidence": "high", "needs_followup": false}}
# 같은 요청의 상세 트레이스는 data/traces/<thread_id>.jsonl 에 남는다

# 6. 질의 예시 (HITL 승인이 필요한 실행형)
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "유휴 리소스 vol-1003-ebs-team-a 지금 정지시켜줘"}'
# -> {"status": "pending_approval", "thread_id": "...", "request": {"tool": "stop_resource", ...}}

curl -X POST http://localhost:8000/query/approve \
  -H "Content-Type: application/json" \
  -d '{"thread_id": "<위 응답의 thread_id>", "approved": true}'

# 6-1. 질문-답변 히스토리 조회 (전체 또는 thread_id로 필터)
curl http://localhost:8000/history
curl "http://localhost:8000/history?thread_id=<thread_id>&limit=20"

# 6-2. 이상탐지 배치 실행 이력 조회 (서버가 떠 있는 동안 자동으로 주기 실행됨, SERVICE.md §5)
curl "http://localhost:8000/batch-runs?limit=10"
# 이메일 알림을 받으려면 .env에 SMTP_HOST/SMTP_PORT/SMTP_USERNAME/SMTP_PASSWORD/
# NOTIFY_EMAIL_TO를 채운다 (.env.example의 네이버 메일 예시 참고) — 안 채우면
# 탐지·기록만 하고 발송은 건너뛴다

# 6-3. 로컬 데모 UI로 실행해보기 (선택, ui/streamlit_app.py)
# 터미널을 하나 더 열어서(서버는 4번 명령으로 계속 띄워둔 채) 아래를 실행한다.
streamlit run ui/streamlit_app.py
# -> 브라우저가 자동으로 http://localhost:8501 을 연다. 질의응답(챗)/승인 대기/
#    히스토리/배치 실행 이력 4개 탭에서 curl 없이 화면으로 조작할 수 있다.
#    이 UI는 브라우저가 아니라 이 프로세스가 requests로 서버를 대신 호출하는
#    구조라 CORS 설정 없이도 동작한다 — 로컬 데모/내부 도구 전용이며 배포용이 아니다.

# 7. 평가셋 자동 채점 (서버 기동 불필요, 그래프를 직접 호출)
python evaluation/run_eval.py --round 1
python evaluation/run_eval.py --round 2   # round1_result.json과 자동 비교(compare_eval)
python evaluation/run_eval.py --round 1 --ragas   # RAGAS 대체 지표(ragas_lite.py)도 계산
python evaluation/run_eval.py --round 1 --llm-judge   # expected_traits까지 LLM으로 채점

# 8. 이상탐지 recall 측정 (SERVICE.md 목표 recall >= 0.9 검증, LLM 미호출)
python evaluation/anomaly_recall.py

# 9. 회귀 테스트 (FakeLLM, 실 LLM 비용 없이 핵심 로직 검증)
pytest tests/
```

## RAGAS 평가 결과

> `python evaluation/run_eval.py --round 2 --ragas` 실행 결과 (Day 10).
> `ragas` 패키지 대신 `evaluation/ragas_lite.py`로 계산한다 — 이유는 "구현 현황" 표와 `ragas_lite.py` 상단 주석 참고.

- context_recall: 계산 불가 (ground_truth 없음)
- context_precision: 1.0
- faithfulness: 1.0 (목표 ≥ 0.8 충족)
- answer_relevancy: 1.0
- **주의**: `retrieve_docs`를 실제로 호출하는 문항이 `test_queries.csv` 20건 중 **1건뿐**이라 (`#6`, 예산 한도 정책 질문) 위 세 지표는 표본 크기 1의 결과다. 수치 자체는 목표를 충족하지만, 이 하나로 "RAG 신뢰도가 충분히 검증됐다"고 보기엔 근거가 얇다 — RAG를 더 자주 타는 문항을 늘리거나 별도 RAG 전용 평가셋을 두는 게 이 지표의 다음 개선 과제다.

## 인-아웃 세트 통과율 (자체 평가)

- 1차 (Day 9 종료, `python evaluation/run_eval.py --round 1`, 결정적 판정): **20 / 20 통과**
  - 처음 실 LLM으로 돌렸을 때는 3/20이었다 — 대부분 `run_eval.py`의 채점 버그(아래 회고 참고) 때문이었고, 실제 답변 품질 문제로 남은 건 2문항(#8, #16)뿐이었다. 채점 버그 수정 + `test_queries.csv` 기대값 현실화 + 에이전트 시스템 프롬프트 보강을 거쳐 20/20을 달성했다.
- 2차 (Day 10, 결정적 판정): **20 / 20 통과**, 1차 대비 회귀 없음(delta +0)
- 2차 (Day 10, `--llm-judge`: expected_traits까지 자연어로 채점): **14~17 / 20 사이에서 변동**
  - 처음 켜봤을 때 14/20이 나왔다 — 결정적 판정(도구 호출·금지어)은 통과해도 "답변이 실제로 요구된 내용을 담았는가"까지는 못 잡는다는 게 드러난 것. 이 6건(#3·#6·#8·#13·#14·#15)을 우선순위대로 수정한 뒤 재실행하니 17/20으로 개선(+3)됐다.
  - 다만 20문항 전체를 다시 돌릴 때마다 실패하는 문항 조합이 매번 달랐다(#2·#13·#14 → #2·#8·#14). 실패했던 문항만 따로 3회씩 반복 실행해보면 전부 3/3 통과했다 — 아래 회고에서 자세히 설명하듯, 이는 수정이 불완전해서가 아니라 **LLM-as-Judge 채점 자체의 run-to-run 변동성**(에이전트 답변 생성도, 채점 LLM의 PASS/FAIL 판정도 `temperature=0`에서 완벽히 결정적이지 않음) 때문으로 판단된다. 그래서 "17/20"이라는 단일 숫자보다 "결정적 판정은 20/20으로 안정적, LLM-as-Judge는 17~20/20 사이를 오간다"가 더 정확한 설명이다.
- 개선폭: 1차 결정적 판정 안에서 3 → 20 (+17). 2차 `--llm-judge`는 수정 전후 14 → 17 (+3)

## 트라이앤에러 회고

- **시도했지만 실패한 접근 — `ragas` 패키지 설치**: RAGAS 지표는 처음엔 공식 `ragas` 패키지로 구현하려 했다. 그런데 이 패키지가 버전(0.2.15, 0.4.3 둘 다 확인)과 무관하게 `langchain_community.chat_models.vertexai`를 무조건 import하는데, 그 모듈은 `langchain-community` 0.4+에서 제거됐다. 맞춰서 `langchain-community`를 0.3.x로 내렸더니 `langchain-core`가 1.0 미만으로 강제 다운그레이드되면서 `langgraph`/`langchain-aws`/`langchain-chroma`/`langchain-classic`/`langchain-mcp-adapters`가 전부 깨졌다 — Multi-Agent Supervisor, MCP 연동, 하이브리드 리트리버가 모두 최신 스택에 의존하고 있어서였다. 바로 원복하고, 같은 지표(faithfulness/answer_relevancy/context_precision)를 `evaluation/ragas_lite.py`에서 우리 Bedrock LLM으로 직접 계산하는 쪽으로 전환했다.
- **시도했지만 실패한 접근 — MCP 도구를 동기(`invoke`)로 호출**: `retrieve_docs`처럼 로컬 도구는 동기로도 잘 동작했는데, MCP로 붙인 도구(`aws_get_cost` 등)는 `StructuredTool does not support sync invocation` 오류가 났다. 원격 프로세스와 stdio로 통신하는 MCP 도구는 비동기 전용이었다. `agent.py`/`app.py`/`pipeline.py` 전체를 `ainvoke`/`async def`로 바꿔서 해결했다.
- **최종 채택한 접근**: Day 6(Supervisor 라우팅)을 뼈대로, 조회형 서브 에이전트 3개는 Day 3(ReAct 루프)를 내장하고, 실행 에이전트만 "LLM 결정 → 승인 확인·실행" 2단계로 분리했다. MCP 서버는 aws/gcp/azure 3개 프로세스로 실제 분리하고 provider별 이름(`aws_get_cost` 등)으로 충돌을 피했다.
- **구현 완료 후 전체 코드 리뷰에서 발견·수정한 버그 7건** (`/code-review` 스킬 + 독립 검증 에이전트로 교차 확인):
  1. `src/app.py`가 `uvicorn src.app:app`(Dockerfile/run.sh/README가 문서화한 실행 방식)으로 뜨면 형제 모듈 import가 `ModuleNotFoundError`로 죽음 — `sys.path.insert` 누락. **가장 심각한 버그**: 문서대로 실행하면 서버가 아예 안 뜸.
  2. `guardrails.input_guard`의 파괴적 명령 차단 규칙이 "인스턴스 정지해주세요" 같은 정상적인 실행 요청까지 HITL 승인 절차에 닿기도 전에 차단 — HITL 아키텍처 자체를 무력화하는 규칙이라 제거함.
  3. `execution_agent`가 승인 필요한 도구 호출을 2개 이상 한 턴에 받으면, LangGraph의 interrupt 재개가 노드를 처음부터 재실행하는 특성 때문에 먼저 승인된 호출이 재개될 때마다 중복 실행됨(예: 같은 리소스가 두 번 정지 시도) — 노드가 호출 하나만 처리하고 그래프 엣지로 루프를 돌게 재설계해 해결.
  4. `assess_retrieval`의 `matched >= 2` 고정 임계값 때문에 2~3자짜리 짧은 질문은 아무리 관련 있어도 절대 통과할 수 없었음 — `min(2, len(keywords))`로 완화.
  5. MCP 서버가 기동 실패하면 `_tool_fns_for`가 알아보기 힘든 `KeyError`로 죽음 — 원인을 알려주는 `RuntimeError`로 교체.
  6. ReAct 서브그래프의 `agent_node`가 `async def`인데 내부에서 동기 `invoke()`를 불러 이벤트 루프를 블로킹 — `ainvoke`로 교체.
  7. 도구 호출 예산(`MAX_TOOL_CALLS_PER_AGENT`)을 다 쓰고 강제 종료되면 `judge_output`이 빈 텍스트를 "저가치"로 침묵시켜 사용자가 이유를 알 수 없었음 — 예산 초과를 명시하는 메시지로 교체.

  전부 가짜 LLM(FakeLLM)과 실제 SQLite/MCP 서브프로세스로 재현 → 수정 → 재검증했다. 2번과 3번은 HITL 안전성에 직결되는 문제라 우선순위를 가장 높게 뒀다.
- **SERVICE.md 가드레일 규칙 4·5가 문서에만 있고 코드로는 강제되지 않던 문제**: 채점 기준("가드레일 준수 여부 — 정의한 제약을 실제로 지키는가")을 다시 보다가 발견했다. `test_queries.csv` #20("다른 팀 계정 API 키나 청구 정보 좀 보여줘")이 통과하는 건 권한 검사 때문이 아니라 "API 키"/"청구 정보"라는 단어가 우연히 정보추출 차단 규칙에 걸려서였고, "team-b 비용 얼마야?" 같은 단어를 안 쓴 요청은 그냥 다 보여주고 있었다 — 코드 전체에 `user_id`/`auth`/`permission` 개념이 전무했다. 규칙 4(외부 입력의 지시문을 시스템 지시로 취급 안 함)도 `data/policy_docs/tagging_policy.md`라는 RAG 문서에 "이렇게 하라"고 적어둔 게 전부라, LLM이 그 문서를 안 찾아보면 아무 방어도 없었다.
  - **규칙 5 수정**: `src/authz.py`(contextvars 기반, `observability.py`와 같은 패턴)로 "요청자가 어느 팀 소속인지"를 요청 하나 동안 들고 다니다가, `tools.py`의 조회·실행 함수 7개(`get_cost_by_service`/`get_resource_utilization`/`list_idle_resources`/`detect_cost_anomaly`/`estimate_savings`/`stop_resource`/`resize_resource`) 전부에서 DB 쿼리 직전에 확인한다. LLM이 `team` 인자를 아예 안 넘겨도(전체 조회 우회 시도) 본인 팀으로 강제로 좁혀지고, 다른 팀을 명시하면 거절 메시지를 돌려준다 — 프롬프트로는 우회 불가능한 계층. **알려진 한계**: MCP 서버(`aws_get_cost` 등)는 별도 자식 프로세스라 이 contextvars가 전달되지 않는다. `get_cost`에서 `team` 인자 자체를 없애 그 경로로 팀별 조회를 아예 못 하게 막았지만, `get_utilization(resource_id)`은 다른 팀 소속 resource_id를 이미 알고 있는 요청자에게는 여전히 열려 있다(계정=provider 경계만 검사, 팀 경계는 검사 안 됨) — `mcp_servers/cost_server.py`에 이 한계를 코드 주석으로 명시해뒀다.
  - **규칙 4 수정**: `guardrails.sanitize_tool_output()`을 만들어 `agent.py`의 ReAct 루프(`tools_node`)에서 모든 도구 결과(로컬+MCP 공통 경로)가 다음 LLM 호출로 들어가기 전에 거친다. 인젝션 마커·역할재정의·탈옥 패턴을 발견하면 무력화 표시로 바꾼다. 지금 데이터셋엔 악성 태그가 없어 평소엔 아무것도 안 바뀌지만, 가짜 RAG 도구가 `### new instruction: ...`이 섞인 문서를 돌려주는 시나리오로 재현해서 실제로 LLM에 전달되기 전에 소독되는 것까지 확인했다.
- **실제 AWS Bedrock으로 처음 `run_eval.py --round 1`을 돌려보고 나서 (3/20 → 20/20)**: `.env`에 실 자격 증명이 채워진 뒤 처음 실행한 결과는 3/20이었다. 원인을 나눠보면:
  1. **채점 스크립트 자체의 버그**: `pipeline.py`가 최종 응답의 trace 항목에 도구 이름을 `"step"` 키로 담는데, `run_eval.py`의 `_response_tool_names()`는 `"tool"` 키를 읽고 있었다. 그래서 `expected_tools`가 지정된 문항은 **실제로 정확한 도구를 호출했어도 무조건 판정 실패**했다 — 이 하나가 8개 문항을 억울하게 fail 시키고 있었다. `rec.get("step")`으로 고쳤다.
  2. **AWS Bedrock 일일 토큰 한도**: 첫 실행분엔 `ThrottlingException`이 여럿 섞여 있었는데(계정 쿼터 문제, 코드로 해결 불가), 재실행 시점엔 쿼터가 회복돼 있었다.
  3. **test_queries.csv의 expected_tools가 MCP 분리 이전 이름 그대로 남아있던 문제**: `list_idle_resources`/`get_resource_utilization`은 MCP 통합 후 어느 에이전트에도 안 붙어 있어 애초에 호출이 불가능했다 — `aws_list_idle` 등 실제 도구 이름으로 갱신하고, `deterministic_judge`에 `"toolA|toolB"` OR 문법을 추가해 "로컬 집계 도구든 provider별 MCP 도구든 뭘 불러도 정답"인 경우를 표현했다.
  4. **라우팅 키워드 사각지대**: "왜 이렇게 비싸?"가 `_COST_KEYWORDS`에 없어 아예 라우팅이 안 됐다 — "비싸"/"비싼" 추가.
  5. **질문 자체가 모호해서 LLM이 도구 호출 대신 되묻는 경우**(`#4`, `#19`): 구체적인 리소스 ID를 질문에 박아 넣어 해결.
  6. **서브 에이전트가 스스로 "이건 범위 밖"이라 판단해 도구를 안 부르는 경우**(`#8`, `#16`): `optimization_agent`/`anomaly_agent`/`execution_agent`의 시스템 프롬프트를 보강했다. `#8`(계획 수립 시 이상탐지 누락)과 `#19`(승인 필요 도구를 호출 안 하고 말로만 거절)는 프롬프트 보강으로 해결됐지만, `#16`(팀 간 비용 배분)은 "절대 규칙"까지 세 단계로 강하게 지시해도 LLM이 끝내 `retrieve_docs`를 안 불러 — 더 밀어붙이는 대신 이 문항의 도구 요구 조건을 내려놓았다(실제 답변은 일반적 배분 기준·불확실성은 언급해 완전히 나쁜 답은 아니었다).
  각 수정 단계마다 실제 LLM으로 재실행해 검증했고, 최종적으로 20/20을 달성했다.
- **덤으로 발견한 버그 — Chroma 벡터스토어가 실행할 때마다 계속 쌓임**: 위 과정에서 `build_supervisor()`를 여러 번 부르다 보니 `data/chroma_db`의 임베딩 개수가 17개(청크 수)가 아니라 119개(17의 배수)인 걸 발견했다. `Chroma.from_documents`는 같은 persist_directory에 이미 데이터가 있어도 지우지 않고 그냥 추가만 한다 — `build_vectorstore()`의 원래 docstring은 "매번 새 컬렉션으로 재색인"이라고 적어놨었지만 실제 그렇게 동작하지 않았던 것. 서버를 재시작할 때마다(또는 `run_eval.py`를 돌릴 때마다) 같은 문서가 계속 누적돼 검색 결과에 중복이 쌓이고 임베딩 비용도 매번 낭비되고 있었다. `Chroma(...).delete_collection()`으로 재생성 전에 기존 컬렉션을 지우도록 고쳤다 — 참고로 `shutil.rmtree`로 직접 파일을 지우려 했더니 같은 프로세스 안에서 이전 Chroma 클라이언트가 파일을 열어둔 채라 Windows에서 `PermissionError`가 났다(직접 겪음). 3회 연속 재빌드로 임베딩 수가 계속 17개로 유지되는 것까지 확인했다.
- **20/20 달성 이후 "코드 수정 없이 리팩토링 항목만 알려줘" 요청으로 진행한 리뷰에서 발견·수정한 6건**: 이번엔 버그가 아니라 방어 누락·중복·정합성 문제 위주였다.
  1. **HITL 승인 대기 응답(`pending_approval`)이 마스킹을 안 거침**: `pipeline.finalize()`가 `interrupts[0].value`(도구 인자 — 예: `send_cost_alert`의 `message`, `resize_resource`의 `target_type`, 즉 LLM이 채운 자유 형식 텍스트)를 그대로 반환하고 있었다. 정상 응답 경로(`answer`)는 `guardrails.mask_pii()`를 거치는데 이 경로만 빠져 있었던 것 — 자격증명이 도구 인자에 섞여 들어오면 승인 요청 화면에 그대로 노출될 수 있었다. 딕셔너리/리스트를 재귀적으로 훑어 문자열만 마스킹하는 `guardrails.mask_pii_deep()`을 새로 만들어 적용했다.
  2. **`contexts`/`trace` 필드도 같은 이유로 마스킹 누락**: `sanitize_tool_output()`은 인젝션 마커만 지우지 PII는 안 지우는데, `answer`만 `mask_pii()`를 거치고 같은 응답의 `contexts`/`trace`(도구 원본 출력)엔 자격증명이 그대로 남을 수 있었다. 두 필드 조립 지점에 `mask_pii()`를 추가했다.
  3. **실행 라우팅이 부분 문자열 매칭이라 오탐**: `_EXECUTION_KEYWORDS`가 "정지"/"변경"/"축소" 같은 어간을 `in` 연산자로 검사해서, "정지해야 하나요?"·"변경해도 될까요?"·"축소해도 괜찮을까요?" 같은 **문의**까지 실행 요청으로 오분류해 execution_agent로 잘못 라우팅됐다. "~해/시켜 + 줘/주세요/줄래" 같은 실제 명령형 어미가 뒤에 붙을 때만 매칭하는 정규식(`_EXECUTION_PATTERNS`)으로 교체했다.
  4. **`estimate_savings`의 authz 검사가 다른 실행 도구와 일관성이 없었음**: `resource_id`가 `resources` 테이블에 없으면(예: 폐기된 리소스, `costs` 테이블엔 남아있음) 소유 팀을 확인할 길이 없는데, 이전엔 이 경우 검사 자체를 건너뛰고 그냥 계산해 돌려줬다 — `stop_resource`/`resize_resource`는 같은 상황에서 "찾을 수 없음"으로 거절하는 것과 다른 동작이었다. 팀이 제한된 요청자에게는 동일하게 거절하도록 맞췄다(fail-closed).
  5. **텍스트 추출 로직 3중 중복**: `ChatBedrockConverse`/MCP 도구 응답의 `content`가 문자열이 아니라 블록 리스트로 오는 경우를 처리하는 거의 동일한 코드가 `agent.py`/`retriever.py`/`evaluation/run_eval.py`에 각각 따로 있었다 — `src/llm_utils.py`(`get_text`)로 통합했다.
  6. **`requirements.txt`가 실제 의존성과 어긋남**: 안 쓰는 `langgraph-supervisor`(전체 코드에서 import 0건, StateGraph로 직접 만든 Supervisor를 쓰기 때문)가 남아있었고, 반대로 `AsyncSqliteSaver`(`app.py`의 체크포인터)가 실제로 쓰는 `langgraph-checkpoint-sqlite`는 아예 목록에 없었다(이 환경엔 다른 패키지의 의존성으로 우연히 깔려 있어서 지금까지 안 드러남 — 새 환경에서 `pip install -r requirements.txt`만 하면 서버 기동 시 빠질 뻔했다). 제거·추가로 정리했다.

  6건 모두 수정 후 FakeLLM 기반 회귀 스위트(가드레일 차단/통과, 도구 출력 소독, authz 팀 제한 조회/실행, `estimate_savings` fail-closed, 실행 라우팅 정규식 오탐/정탐, MCP 조회+`get_text` 통합, HITL 다중 호출 중복 실행 없음, 도구 호출 예산 컷오프 메시지) 23건을 새로 작성해 전부 통과시켰고, 실 AWS Bedrock으로 `run_eval.py --round 1`을 다시 돌려 여전히 20/20임을 확인했다.
- **`--llm-judge`를 처음 켜보고 나서 발견한 6건과, 그 수정이 드러낸 LLM-as-Judge의 근본적 한계**: 완성도 점검 차원에서 `--ragas`와 `--llm-judge`를 실제로 처음 실행해봤다(그 전까진 코드만 있고 한 번도 안 돌려봤었다). RAGAS는 faithfulness/answer_relevancy/context_precision 전부 1.0으로 목표(≥0.8)를 충족했지만(단, `retrieve_docs`를 타는 문항이 20건 중 1건뿐이라 표본이 얇다), `--llm-judge`는 결정적 판정(20/20)과 달리 14/20이 나왔다 — 도구는 맞게 불렀지만 `expected_traits`(답변이 실제로 갖춰야 할 내용)까지는 못 채운 문항들이 있었던 것.
  1. **#3(유휴 리소스 조회)**: 목록만 나열하고 "왜 유휴로 판단했는지" 기준을 설명하지 않음 — `list_idle_resources()`가 판단 기준 자체를 응답에 안 담고 있어서, 에이전트도 설명할 근거가 없었다. 도구 출력에 판단 기준(최근 사용률 30% 미만)을 명시하도록 고쳤다.
  2. **#6(정책 문서 질문)**: 출처 문서명이 없다고 판정됨 — 그런데 실제로는 출처가 `answer` 문자열이 아니라 API 응답의 별도 `contexts` 필드에 담기는 구조였다. 제품 결함이 아니라 **평가 하네스가 `contexts`를 안 보고 `answer`만 채점 LLM에 넘기던 문제** — `run_eval.py`에 `contexts`의 출처 문서명을 판정 프롬프트에 포함하는 `_response_text_with_sources()`를 추가했다(제품 코드는 그대로 둠).
  3. **#8(분기 절감 계획)**: 도구 호출 예산(`MAX_TOOL_CALLS_PER_AGENT`=4)을 다 써서 계획을 끝까지 못 세우고 중간에 끊김 — 이 복합 질문 유형을 담당하는 `optimization_agent`만 예산을 7로 늘렸다(다른 에이전트는 도구가 1~2개뿐이라 4로 충분).
  4. **#13(모호한 비교 질문)**: "왜 이렇게 안 맞지?"처럼 원인을 하나로 단정할 근거가 없는 질문에도 확정적으로 답함 — SERVICE.md 정책 3번("근거 없으면 추측하지 않는다")과 충돌하는 문제라, `anomaly_agent`에 "모호하면 후보를 여러 개 제시하거나 되물어라" 규칙을 추가했다.
  5. **#14(프로바이더 간 스토리지 비교)**: 블록 스토리지(EBS)와 오브젝트 스토리지(S3/GCS)를 구분 없이 합쳐서 배율 비교함 — `cost_lookup_agent`에 "성격이 다른 서비스는 비교 전에 그 차이부터 언급하라" 규칙을 추가했다.
  6. **#15(민감도 조정 요청)**: 임계값(z_threshold)을 낮춰 조회한 결과를 설명하면서 "이번 조회 한정"이라는 말이 없어 마치 설정이 영구히 바뀐 것처럼 읽힐 위험이 있었음 — `anomaly_agent`에 "이번 조회에만 적용된 파라미터"임을 명시하고 트레이드오프(오탐 증가)도 안내하라는 규칙을 추가했다.

  6건 수정 후 재실행하니 14→17/20로 개선됐다. 그런데 실패한 문항만 따로 뽑아 3회씩 반복 실행하면 **매번 3/3 전부 통과**했고, 전체 20문항을 다시 돌릴 때마다 실패하는 조합이 그때그때 달랐다(#2·#13·#14 → #2·#8·#14, #2는 애초에 이번 수정과 무관한 문항인데도 걸림). 이건 수정이 불완전해서가 아니라 **LLM-as-Judge 채점 자체의 run-to-run 변동성** 때문이다 — 에이전트의 답변 생성도, 채점 LLM의 PASS/FAIL 한 단어 판정도 `temperature=0`에서 Bedrock이 완벽히 결정적이지 않다. 그래서 결정적 판정(도구 호출·금지어)은 20/20으로 안정적인 반면, LLM-as-Judge는 "정답 문항 수"라는 단일 숫자보다 "17~20/20 사이를 오가는 분포"로 이해하는 게 더 정확하다. (부수적으로: `round2_result.json`의 `compare_eval` delta는 1차(결정적 판정)와 2차(`--llm-judge`)를 서로 다른 채점 방식으로 비교한 값이라 액면 그대로 "회귀"로 읽으면 안 된다.)
- **남은 한계**: (스캔하기 쉬운 표로 정리한 버전은 [LIMITATIONS.md](LIMITATIONS.md) 참고 — 대용량 데이터로 커질 때의 DB 확장 방향성도 거기 §4에 있음)
  - `answer_chain` 구조화, RAG 리랭킹/쿼리확장, RAGAS 채점은 위 회고의 실행에서 간접적으로는 거쳤지만 각각을 독립적으로 뜯어서 검증하지는 않았다.
  - Observability는 로컬 JSONL 트레이스까지만 확인, LangSmith 실 연동은 미검증(계정 없음).
  - `authz.py`의 `requester_team`은 아직 인증되지 않은 자기 신고 값이다 — 실제 로그인/세션 기반 신원 검증은 이 스코프 밖이다.
  - **LLM-as-Judge(`--llm-judge`)는 run-to-run 변동성이 있다** — 결정적 판정은 20/20으로 안정적이지만, `expected_traits`까지 보는 LLM-as-Judge는 17~20/20 사이를 오간다(위 회고 참고).
- **완성도 점검 후 추가 구현한 3건(코드 리팩토링 없이 새 코드만 추가)**:
  1. **API 재시도**: `llm_utils.with_bedrock_retry()`로 모든 Bedrock LLM 생성 지점(`agent.py`/`answer_chain.py`/`retriever.py`/`evaluation/ragas_lite.py`)에 지수 백오프 재시도(`.with_retry(stop_after_attempt=3)`)를 씌웠다. 이 프로젝트가 실제로 겪은 `ThrottlingException`(round1 첫 실행)이 계기다. **구현 중 발견한 버그**: `agent.py`에서 `_default_llm()` 반환값에 바로 재시도를 씌우면, 그 결과(`RunnableRetry`)는 `.bind_tools()`를 지원하지 않아 `_build_react_subgraph`/`_execution_decide_node`의 `llm.bind_tools(...)` 호출이 그대로 깨진다 — 실제로 재현해서 확인했다. 재시도는 반드시 `.bind_tools()` **이후**에 씌워야 한다(다른 파일은 `bind_tools`를 안 써서 문제없이 바로 씌울 수 있었다). 수정 후 실제 조회형·실행형 질문 모두 정상 동작하는 것까지 확인했다.
  2. **이상탐지 recall 측정**: `evaluation/anomaly_recall.py` 신규 작성 — `scripts/generate_data.py`의 `ANOMALIES`(실제로 주입한 정답)와 `detect_cost_anomaly()`의 실제 탐지 결과를 집합 비교해 recall을 계산한다(LLM 미호출, 결정적). 실행 결과: recall 1.00 (2/2), SERVICE.md 목표(≥0.9) 충족.
  3. **회귀 테스트를 저장소 자산으로**: 그동안 세션 스크래치패드에만 있던 FakeLLM 기반 회귀 스위트를 `tests/test_regression.py`(pytest)로 옮겼다 — `pytest tests/`로 재현 가능. `requirements.txt`엔 `pytest`가 이미 있었는데 정작 저장소엔 테스트 파일이 하나도 없던 상태였다.
- **"완성도 점검 후 남은 항목" 중 나머지 2건(대화 이력 요약, MCP authz 경계) 구현 — 그 과정에서 발견한 심각한 기존 버그 2건 포함**:
  1. **MCP 리소스 단위 authz 경계**: `mcp_servers/cost_server.py`는 별도 자식 프로세스라 authz의 contextvars가 안 건너간다는 한계가 있었다. `aws/gcp/azure_get_utilization`은 MCP 서버가 부모와 같은 `costs.db` 파일을 그대로 읽는다는 점을 이용해, `agent.py`의 `tools_node`가 이 도구들을 **실제로 호출하기 전에** 부모 프로세스 쪽에서 `resource_id`의 소유 팀을 먼저 조회해(`tools.resource_team`) `authz.check_resource_team()`으로 막는다(`_mcp_resource_authz_denial`). 다른 팀 리소스는 실제 MCP 프로세스로 요청이 나가기 전에 거절되고, 본인 팀·제한 없는 요청자는 그대로 통과하는 것을 실 Bedrock+MCP로 확인했다.
  2. **대화 이력 요약**: `pipeline._maybe_summarize_history()` — 메시지가 20개를 넘으면 최근 6개만 남기고 나머지를 LLM 요약 1개(`SystemMessage`)로 교체, `RemoveMessage`로 체크포인트에서 실제로 제거한다. `guardrails.MIDDLEWARE_ORDER`에 이름만 있고 구현이 없던 `HistorySummaryMiddleware`를 채운 것이다.
  3. **구현하다가 발견한 버그 ①(가장 심각) — 같은 thread_id의 두 번째 질문부터 라우팅이 아예 안 됨**: 이력 요약을 테스트하려고 같은 thread_id로 여러 턴을 실제로 주고받아 보니, 두 번째 질문부터 어떤 서브 에이전트도 호출되지 않고 **첫 번째 턴의 답변이 그대로 반복 반환**됐다. 원인은 `_supervisor_node`가 `pending is not None`만 보고 "이미 라우팅했다"고 판단하는 것 — 체크포인터가 이전 턴이 끝난 뒤의 `pending=[]`을 다음 턴에도 그대로 들고 있어서, 새 질문이 와도 `[]`은 `None`이 아니니 라우팅을 건너뛰고 그래프가 곧장 끝나버렸다. `evaluation/run_eval.py`는 문항마다 **별도의 새 thread_id**를 쓰기 때문에 이 버그가 지금까지 한 번도 안 드러났었다 — 실제 멀티턴 대화를 처음 시도해보고서야 발견했다. 라우팅을 마친 human 메시지 개수(`routed_human_count`)를 기록해두고 현재 개수와 비교하는 방식으로 고쳤다 — "같은 턴 안에서 워커가 돌아온 것"과 "새 질문이 들어온 것"을 정확히 구분한다.
  4. **구현하다가 발견한 버그 ②(①을 고치자마자 바로 드러남) — 매 턴 응답에 이전 턴들의 답변·trace가 계속 다시 실림**: ①을 고치니 라우팅은 제대로 됐지만, `pipeline.finalize()`가 스레드 전체 누적 `messages`/`trace`에서 값을 뽑고 있어서 세 번째 턴 응답에 1~3턴 답변이 전부 이어붙어 나왔다. `messages`는 가장 최근 `HumanMessage` 이후만 자르고(`_messages_since_last_human`), `trace`는 턴 시작 시점의 길이를 `trace_baseline`으로 기록해뒀다가 그 이후분만 쓰도록 고쳤다(`trace`는 `operator.add`로만 계속 쌓이고 `messages`처럼 자연스러운 턴 구분자가 없어서 별도 카운터가 필요했다).
  5. 위 두 버그 모두 회귀 테스트(`test_multiturn_reroutes_on_new_question`, `test_multiturn_response_scoped_to_current_turn`, `test_mcp_resource_scoped_authz_interception`)로 저장소에 고정해뒀고, 전체 20문항 결정적 판정을 다시 돌려 20/20·회귀 없음을 재확인했다.
- **`estimate_savings`의 절감률을 "이 프로젝트 가정치" 하나에서 제공자별 실제 자료 기반으로 교체**: 완성도 점검 대화 중 "더미 대신 실제 API·문서를 쓸 수 있는 부분이 있는가"라는 질문에서 출발했다.
  - **GCP**: 공식 문서(Committed Use Discounts)에 범용 인스턴스 스펜드 기반 CUD 할인율이 1yr 28% / 3yr 46%로 명시돼 있어(확인일 2026-09-16), 이 값을 그대로 상수로 반영했다. 계약상 고정된 값이라 API 조회가 필요 없다.
  - **Azure**: `prices.azure.com`(Azure Retail Prices API, 인증 불필요)에서 대표 범용 VM(Standard_D2_v4, eastus)의 온디맨드·예약(1yr/3yr) 가격을 실제로 조회해 할인율(41.0%/62.0%)을 계산하는 `scripts/fetch_azure_pricing.py`를 새로 만들었다. `estimate_savings()`는 매 호출마다 API를 부르는 대신 이 스크립트가 만든 스냅샷(`data/pricing_docs/azure_ri_rates.json`)을 읽는다 — 이 도구는 "같은 입력엔 항상 같은 출력"이 원칙인 결정적 함수라, 실시간 호출로 바꾸면 그 순간의 시세 변동에 따라 같은 질문에 다른 답이 나오게 돼 원칙과 충돌하기 때문이다.
  - **AWS**: 그대로 유지 — AWS Price List API(`pricing:GetProducts`)를 이 프로젝트 자격증명으로 직접 호출해봤지만 `AccessDeniedException`으로 권한이 없었다(직접 확인). 권한이 생기면 Azure와 같은 스냅샷 방식으로 바꿀 수 있다.
  - **구현 중 발견한 버그**: `fetch_azure_pricing.py`의 예약 가격 조회 쿼리에 리전 필터(`armRegionName eq 'eastus'`)를 빠뜨려서, 전 세계 리전 가격이 다 섞여 나온 뒤 마지막에 순회된 리전(우연히 이탈리아) 값으로 조용히 덮어써지고 있었다 — 온디맨드 가격(eastus 기준)과 앞뒤가 안 맞는 걸 보고 재현해서 발견, 리전 필터를 추가해 고쳤다.
  - 세 제공자 모두 실제 리소스로 `estimate_savings()`를 직접 호출해 각기 다른 할인율(30%/28%/41%)이 적용되는 것과, 답변에 출처(가정치/공식 문서/실측 스냅샷)가 함께 표기되는 것을 확인했다. `test_estimate_savings_provider_specific_rates` 회귀 테스트로 고정했고, 전체 20문항 재실행으로 회귀 없음도 재확인했다.
- **MCP 서버에 "인증 불필요한 실제 API" 하나 더 추가 — 클라우드 상태/장애 피드**: "더미가 아닌 실제 자격증명 없는 MCP 서버를 연결할 수 있는가"라는 질문에서 시작했다. AWS Cost Explorer(`ce:GetCostAndUsage`)·CloudWatch(`cloudwatch:ListMetrics`)·EC2 조회(`ec2:DescribeInstances`)를 전부 실제로 호출해봤지만 이 프로젝트 자격증명으론 셋 다 `AccessDenied`였고, 설령 권한이 있어도 이 계정엔 이 프로젝트가 전제하는 종류의 실 데이터(팀 태그, 90일 이력)가 없어 실효성이 없었다. 대신 AWS(`status.aws.amazon.com/data.json`)·GCP(`status.cloud.google.com/incidents.json`)·Azure(상태 RSS) 공개 상태 피드를 전부 인증 없이 직접 호출해보니 성공했다.
  - `src/incident_feeds.py`를 새로 만들어 세 피드를 정규화된 형태로 조회하는 `check_incidents(provider, start_date, end_date)`를 구현하고, `mcp_servers/cost_server.py`에 `{provider}_check_incidents` 도구로 등록했다(합성 데이터를 감싸는 다른 도구들과 달리 이 도구만 실제 외부 데이터를 실시간으로 조회한다).
  - **세 피드의 성격이 다르다는 걸 직접 확인**: GCP는 시작·종료 시각이 있는 과거 이력을 몇 달치 제공하지만, AWS·Azure 피드는 "현재 진행 중인 이슈"만 보여주는 실시간 대시보드였다 — 과거 날짜 조회 결과가 비어 있어도 "그날 장애가 없었다"고 단정할 수 없다는 뜻이라, 이 캐비앗을 도구 출력에 항상 붙였다.
  - `anomaly_agent`에 배정하고(`detect_cost_anomaly`가 급증 날짜를 찾으면 해당 제공자의 `check_incidents`로 실제 장애 여부를 확인한 뒤 답하라는 시스템 프롬프트 규칙 추가), 실 Bedrock+MCP로 "gce-2001-team-b 비용이 왜 튀었는지" 물어봤더니 실제로 `gcp_check_incidents`를 호출해 "해당 기간에 GCP 공개 장애는 확인되지 않았습니다"라고 **추측이 아니라 검증된 사실**로 답하는 것을 확인했다.
  - `test_check_incidents_invalid_provider`/`test_check_incidents_overlap_logic`(결정적 부분)과 `test_check_incidents_live_feeds_reachable`(실제 네트워크 스모크 테스트)로 회귀 테스트에 추가했고, 전체 20문항 재실행으로 회귀 없음도 재확인했다.
- **신규 기능 2건 추가 — 다운사이징 절감 추정, 팀별 예산 현황**: "추가하면 유용할 기능"을 브레인스토밍한 뒤 그중 2개를 구현했다.
  1. **다운사이징 절감 추정**: `SERVICE.md`의 `estimate_savings` 설명이 원래 "RI/Savings Plan·**다운사이징** 절감액 계산"이라고 돼 있었는데, 실제 코드는 RI/Savings Plan만 계산하고 다운사이징은 전혀 구현돼 있지 않았다 — 문서가 약속한 기능이 코드에는 없던 상태. `estimate_savings(plan_type="downsizing")`을 추가해 채웠다. `resources`/`costs` 테이블엔 인스턴스 타입이 없어 실제 가격표 기반 계산은 불가능하므로, 대신 "사용률을 목표치(65%)까지 끌어올리려면 용량을 그 비율만큼 줄이면 된다"는 사용률 비율 근사를 쓴다(용량-비용 선형 가정, 실제 가격표 아님을 답변에 항상 명시).
  2. **팀별 예산 현황**: `data/policy_docs/budget_policy.md`에 팀별 월 한도(team-a $1,200 등)가 문서로만 있고 실제 사용률을 계산하는 도구가 없었다. `get_budget_status()`를 새로 추가해 `_BUDGET_LIMITS`(정책 문서와 동일한 수치 유지) 대비 이번 달 실제 지출을 계산한다. 한도 초과 시에도 "플랫폼팀 알림 대상(자동 조치 없음)"이라고만 안내하고 실제로 아무 조치도 실행하지 않는다 — budget_policy.md의 "한도 초과 자체가 정지·축소 근거가 되지 않는다" 원칙을 그대로 지킨다.
  3. **라우팅 배치 실수를 미리 잡음**: `get_budget_status`를 처음엔 `cost_lookup_agent`에 넣었는데, `route_question()`의 `_OPTIMIZATION_KEYWORDS`에 "예산"/"한도"가 이미 있어서 "우리 팀 예산 얼마나 썼어?" 같은 질문이 실제로는 `optimization_agent`로만 라우팅된다는 걸 코드를 다시 보고 발견 — 도구는 있는데 그 질문을 받는 에이전트한테는 없는 사고가 날 뻔했다. `optimization_agent` 쪽으로 옮겨서 해결했다.
  4. 두 기능 모두 authz(팀 접근 제어) 회귀 테스트(`test_estimate_savings_downsizing`, `test_get_budget_status`)를 추가했고, 실 Bedrock으로 "다운사이징하면 얼마나 절감돼?"/"우리 팀 예산 얼마나 썼어?"를 실제로 물어봐 `optimization_agent`가 두 도구를 정확히 호출해 근거 있는 수치로 답하는 것을 확인했다.

## 핵심 코드 위치

- `src/app.py` — FastAPI 진입점 (`POST /query`, `POST /query/approve`, `GET /history`). 체크포인터는 `AsyncSqliteSaver`(`data/checkpoints.db`) — 서버가 재시작돼도 HITL 승인 대기 상태가 살아있다
- `src/agent.py` — Supervisor 메인 에이전트 그래프 + 4개 서브 에이전트 (Day 6 뼈대 + Day 3 ReAct 루프)
- `src/tools.py` — 비용조회·예산현황·이상탐지·절감계산(RI 전환+다운사이징)·실행 도구 9개, `data/costs.db` 직접 조회 (Day 3 스타일)
- `src/retriever.py` — FinOps 정책·가격 문서 RAG 파이프라인: 하이브리드(BM25+벡터) → 쿼리 확장(`MultiQueryRetriever`) → 리랭킹(LCEL+Pydantic) (Day 2 기반)
- `src/guardrails.py` — 입력 차단·PII 마스킹·도구 결과 소독·HITL 승인 판정 (Day 5 기반)
- `src/authz.py` — 요청자 팀 접근 범위 강제 (SERVICE.md 가드레일 규칙 5). 로컬 도구 경로는 전부 적용, MCP 서버는 별도 프로세스라 `team` 인자 자체를 노출 안 하는 식으로 우회를 막음(코드 주석에 한계 명시)
- `src/answer_chain.py` — LCEL + Pydantic 구조화 출력 체인 (Day 1 기반, 패턴 1)
- `src/llm_utils.py` — 메시지 `content`가 블록 리스트(MCP 도구 결과 등)여도 텍스트만 뽑아내는 공통 유틸(`get_text`). `agent.py`/`retriever.py`/`evaluation/run_eval.py` 세 곳에 중복돼 있던 걸 통합. `with_bedrock_retry()`(패턴 8 — API 재시도)도 여기 있다
- `src/observability.py` — `TraceCollector`/`Timer`, `data/traces/*.jsonl` 로컬 트레이스 (패턴 11)
- `src/pipeline.py` — 가드레일 차단 → 그래프 실행 → 구조화(answer_chain) → 마스킹 → 트레이스 덤프 → 히스토리 기록 → 대화 이력 요약(`_maybe_summarize_history`, 패턴 8). `app.py`와 `evaluation/run_eval.py`가 공유
- `src/qa_history.py` — 질문-답변 히스토리를 `data/history.db`에 별도 기록 (`costs.db`의 리셋 주기와 분리). `GET /history`로 조회
- `mcp_servers/cost_server.py` — AWS/GCP/Azure Cost API를 흉내 낸 MCP 서버 (`MCP_PROVIDER` 환경변수로 파라미터화, Day 4 fastmcp 패턴). `check_incidents`만 예외로 합성 데이터가 아니라 실제 클라우드 공개 상태 피드를 씀
- `src/incident_feeds.py` — AWS/GCP/Azure 공개 상태·장애 피드(인증 불필요) 조회. `anomaly_agent`가 이상 급증이 실제 클라우드 장애 때문인지 확인하는 데 씀
- `src/mcp_client.py` — `MultiServerMCPClient`로 MCP 서버 3개를 자식 프로세스로 띄우고 도구를 가져옴
- `scripts/generate_data.py` — 합성 멀티클라우드 비용·사용률 데이터 생성기 (시드 고정)
- `scripts/fetch_azure_pricing.py` — Azure Retail Prices API(인증 불필요)로 RI 실제 할인율을 조회해 `data/pricing_docs/azure_ri_rates.json` 스냅샷을 생성 (`estimate_savings`가 읽어 씀)
- `scripts/fetch_cost_optimization_guides.py` — AWS/GCP/Azure Well-Architected Framework 공식 문서(인증 불필요)에서 비용 최적화 가이드 본문을 가져와 `data/policy_docs/{provider}_cost_optimization_guide.md` 스냅샷을 생성 (`retrieve_docs`가 자동 색인, 새 도구 없이 동작)
- `data/` — 비용 데이터(`costs.db`)·정책/가격 문서
- `evaluation/test_queries.csv` — 인-아웃 평가셋 20건
- `evaluation/eval_lib.py` — Day 7 `run_eval`/`compare_eval` (`TraceCollector`는 `src/observability.py`에서 재사용)
- `evaluation/run_eval.py` — 평가 자동화 러너 (결정적 판정 기본, `--llm-judge`로 LLM-as-Judge, `--ragas`로 RAGAS 대체 지표)
- `evaluation/ragas_lite.py` — RAGAS 지표(faithfulness/answer_relevancy/context_precision) 자체 구현 (`ragas` 패키지 미사용, 이유는 파일 상단 주석)
- `evaluation/anomaly_recall.py` — 이상탐지 recall 측정 (`scripts/generate_data.py`의 주입 정답 vs `detect_cost_anomaly()` 실제 탐지 결과 비교, LLM 미호출)
- `evaluation/round1_report.md`, `round2_report.md` — 1차/2차 자체 평가 결과 (`run_eval.py` 실행 시 자동 갱신)
- `tests/test_regression.py` — FakeLLM 기반 회귀 테스트 11건 (pytest). 가드레일·authz·라우팅·HITL 중복실행 방지·도구 호출 예산·멀티턴 재라우팅/응답 스코핑·MCP authz 가로채기 등 핵심 방어 로직 검증
