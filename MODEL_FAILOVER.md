# MODEL_FAILOVER · Bedrock 모델 우선순위·페일오버

## 배경

Bedrock 모델 하나가 스로틀링/일시 장애로 막히면 그 순간 서비스 전체가 막힌다.
"질문마다 여러 모델을 미리 다 찔러보고 살아있는 걸 고르는" 방식(프리체크)은 LLM
호출 지점마다 매번 추가 왕복이 붙어 지연시간이 크게 늘어난다 — 이 프로젝트는 질문
하나에 순차 LLM 호출이 3~6번 걸리므로, 사전 체크를 붙이면 질문당 수~십 초가 그냥
더 붙는다. 그래서 **"기본 모델을 그냥 쓰다가, 재시도까지 다 실패했을 때만 다음
우선순위 모델로 넘어가는" 리액티브 페일오버**를 쓴다 — 정상 상황(대부분)엔 추가
호출이 0번이고, 장애 상황에서만 비용이 든다(그 대안이 "에러 응답"이었던 걸 감안하면
순이익).

## 우선순위 목록

`src/llm_utils.py`의 `MODEL_PRIORITY`가 유일한 원본이다. 순위를 바꾸거나 모델을
추가/제거하면 **이 표와 `MODEL_PRIORITY`를 같이 갱신한다.**

**속도 우선으로 재배치됨(2026-09-18)** — 처음엔 "가장 강력한 모델부터"(Claude
Sonnet 4.5가 1순위) 순서였는데, `evaluation/run_eval.py --round 1`로 실제로
돌려보니 문항당 소요 시간이 (Nova 2 Lite 단독이던 이전 대비) 5~15초 →
70초·143초·163초·215초로 **문항이 진행될수록 계속 늘어났다**(스로틀링
재시도가 누적되는 패턴으로 추정). 이 프로젝트는 질문 하나에 순차 LLM 호출이
3~6번 걸려서, 무거운 모델을 1순위에 두면 그 지연이 곱해진다는 걸 실측으로
확인한 것 — "가장 좋은 모델"과 "1순위(=거의 항상 실제로 쓰이는 모델)"는 다른
기준으로 골라야 한다. 그래서 이 프로젝트에서 이미 속도·프롬프트 호환성 둘 다
검증된 Nova 2 Lite를 1순위로 올리고, Claude 계열은 "Nova가 전부 막혔을 때만
쓰는" 뒷순위 페일오버로 내렸다.

| 순위 | 모델 ID | 계열 |
|---|---|---|
| 1 | `global.amazon.nova-2-lite-v1:0` | Amazon Nova 2 Lite (글로벌 추론 프로필, 이전까지 이 프로젝트의 고정 `MODEL_ID` — 속도·프롬프트 호환성 검증됨) |
| 2 | `us.amazon.nova-2-lite-v1:0` | Amazon Nova 2 Lite (us 리전 프로필) |
| 3 | `us.amazon.nova-lite-v1:0` | Amazon Nova Lite |
| 4 | `us.amazon.nova-pro-v1:0` | Amazon Nova Pro |
| 5 | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Claude Haiku 4.5 (us 리전 프로필) |
| 6 | `global.anthropic.claude-haiku-4-5-20251001-v1:0` | Claude Haiku 4.5 (글로벌 추론 프로필) |
| 7 | `us.anthropic.claude-sonnet-4-6` | Claude Sonnet 4.6 (us 리전 프로필) |
| 8 | `global.anthropic.claude-sonnet-4-6` | Claude Sonnet 4.6 (글로벌 추론 프로필) |
| 9 | `global.anthropic.claude-sonnet-4-5-20250929-v1:0` | Claude Sonnet 4.5 (글로벌 추론 프로필) — 나머지 8개가 전부 막혔을 때만 쓰는 최후 폴백 |

9개 전부 `us-east-1` 리전에서 실제 `converse()` 호출로 살아있음을 직접 확인했다
(2026-09-18, 이 세션에서 두 후보를 직접 호출해 정상 응답 받음 — 나머지는 계정에
모델 액세스가 있다는 전제).

## 동작 방식

1. 각 후보 모델은 `llm_utils.with_bedrock_retry()`로 감싼다 — **페일오버 체인 안에서는
   재시도를 1회로 줄인다**(기본값 3회가 아니라 `stop_after_attempt=1`). 처음엔 3회
   그대로 썼는데, Sonnet을 1순위로 뒀을 때 문항당 지연이 70→143→163→215초로
   계속 악화되는 걸 실측했다 — 모델 하나를 3번씩 두드리며 시간을 쓰는 대신, 9개
   후보가 있으니 한 번만 시도하고 빨리 다음으로 넘어가는 쪽이 낫다.
2. **서킷 브레이커** — 1순위가 방금 실패했으면, 그 사실을 잊지 않고 30초
   (`llm_utils._CIRCUIT_COOLDOWN_SECONDS`) 동안은 시도 자체를 건너뛰고 곧바로
   다음 순위로 간다. 처음엔 LangChain `Runnable.with_fallbacks()`만 썼는데, 이건
   "기억이 없어서" 호출마다 매번 1순위부터 다시 시도했다 — 1순위가 일시적 blip이
   아니라 지속적으로 막혀 있으면(스로틀링 등) 매 호출이 똑같이 그 비용을 반복해서
   물게 되고, 재시도 자체가 스로틀링을 더 악화시키는 악순환이 될 수 있다. 그래서
   `.with_fallbacks()` 대신 `with_circuit_breaker_failover()`라는 자체 구현으로
   바꿨다 — 실패하면 `trip_circuit()`으로 그 모델을 쉬게 하고, 성공하면
   `reset_circuit()`으로 즉시 복귀시킨다. 이 모듈에서 부수효과가 있는 건 이
   쿨다운 상태(`_circuit_trip_until`, mutable global) 하나뿐이고, 조회
   (`is_circuit_open`)는 상태를 안 바꾸는 순수 함수다.
3. `.bind_tools()`가 필요한 호출(서브 에이전트 ReAct 루프)은 **9개 모델 각각에
   개별적으로 bind_tools를 먼저 건 다음** 서킷 브레이커로 엮는다 — `RunnableRetry`
   류는 `.bind_tools()`를 못 가지므로(README 트라이앤에러 회고에서 이미 겪은 것과
   같은 제약) 반드시 이 순서로 감싸야 한다.
3-1. `with_circuit_breaker_failover()`가 반환하는 `RunnableLambda`는 **동기
   `.invoke()`와 비동기 `.ainvoke()`를 둘 다 진짜로 구현**한다(`func=`와 `afunc=`
   둘 다 준다). 처음엔 `afunc`만 구현했는데, `retriever.py`의 RAG 체인(`retrieve_docs`
   도구는 동기 함수라 LangGraph의 ToolNode가 스레드 풀에서 동기로 실행)이
   `llm.invoke(messages)`로 동기 호출하다가 "코루틴을 동기로 못 부른다"는
   `TypeError`로 실제로 깨지는 걸 안전장치 4(SAFEGUARDS.md) 검증 중 E2E로 발견해
   고쳤다 — 두 경로 모두 서킷 브레이커 스킵 로직을 완전히 대칭으로 구현해뒀다.
4. 실제로 응답한 모델은 `ChatBedrockConverse` 응답의
   `response_metadata["model_name"]`(직접 호출해 실측 확인한 필드)에서 그대로
   읽힌다 — 별도 계측 없이 "이 응답을 만든 모델이 무엇인지"를 정확히 안다.
5. 이 값은 **LangGraph 상태(`SupervisorState.active_model`)로 들고 나온다** —
   처음엔 `authz.py`의 `requester_team`처럼 contextvar로 구현했다가, 실제로
   돌려보니 항상 비어 있었다. LangGraph가 노드를 asyncio 태스크로 실행해서, 노드
   안에서 `contextvar.set()`해도 그 값이 호출부(부모 컨텍스트)까지 안 건너갔다
   (직접 겪음 — contextvar는 부모→자식 방향으로만 안전하게 전파되고, 자식이 설정한
   값이 부모로 다시 올라오는 건 보장되지 않는다). `trace`가 이미 쓰던 것과 같은
   "노드가 반환한 dict를 그래프가 병합해준다" 경로로 바꿔서 고쳤다 — 실제 프로덕션
   경로(`llm=None`)로 진짜 질문을 던져 `active_model`이 정확히 채워지는 것까지
   확인했다.

   반면 서킷 브레이커의 쿨다운 상태는 **의도적으로 contextvar가 아니라 진짜 전역
   변수**다 — `active_model`은 "이번 요청 하나에만 갇힌 값"이라 contextvar가 맞는
   자리였지만(다만 실제로는 그래프 상태로 옮겨야 했다), 서킷 브레이커는 정반대로
   "여러 요청에 걸쳐 계속 기억해야 하는 값"이라 프로세스 전역 상태가 맞는 선택이다.

## 구현 위치

| 함수/상수 | 파일 | 역할 |
|---|---|---|
| `MODEL_PRIORITY` | `src/llm_utils.py` | 우선순위 목록 (이 문서의 원본) |
| `build_llm_with_failover(tool_fns=None)` | `src/llm_utils.py` | 도구 바인딩이 필요 없는 호출(구조화, RAG 리랭킹/쿼리확장, 대화 이력 요약, 평가용 judge/RAGAS)용 — 9개 전체로 서킷 브레이커 체인을 바로 만든다 |
| `build_fallback_candidates(tool_fns, model_ids)` | `src/llm_utils.py` | `(model_id, runnable)` 쌍의 리스트를 만든다(재시도 1회) — "주어진 `llm`을 1순위로 쓰고 나머지만 후보로 만들어달라"는 요청에 맞춰 나머지 모델만 만들어준다(아래 "테스트 격리" 참고) |
| `with_circuit_breaker_failover(candidates)` | `src/llm_utils.py` | `(model_id, runnable)` 리스트를 순서대로 시도하는 Runnable(`RunnableLambda`)로 엮는다 — 쿨다운 중인 모델은 건너뛰고, 실패하면 트립, 성공하면 즉시 리셋 |
| `is_circuit_open` / `trip_circuit` / `reset_circuit` | `src/llm_utils.py` | 서킷 브레이커 상태 조회/기록 — `is_circuit_open`만 순수 조회, 나머지 둘이 유일한 부수효과 지점 |
| `extract_active_model(response)` | `src/llm_utils.py` | 부수효과 없음 — 응답 하나에서 모델 ID만 뽑아 돌려준다. 호출부(agent.py)가 이 값을 그래프 상태(`SupervisorState.active_model`)에 담아 병합·전달한다 |

### 적용 범위

- **적용됨**(전부 실제 서비스 경로): `agent.py`의 서브 에이전트 ReAct 루프
  (`_build_react_subgraph`)와 `execution_agent` 결정 노드(`_execution_decide_node`),
  `answer_chain.py`(구조화), `retriever.py`(쿼리 확장·리랭킹·retrieve_docs 자체
  답변 합성), `pipeline.py`(대화 이력 요약), `evaluation/run_eval.py`(`--llm-judge`/
  `--ragas`).
- **적용 안 됨(의도적)**: `tests/test_regression.py`가 `build_supervisor(llm=fake_llm, ...)`로
  FakeLLM을 주입하는 경로. `llm`을 명시적으로 넘기면 그 인스턴스를 1순위로 그대로
  쓰고 페일오버를 안 건다(`build_supervisor`가 `llm is None`일 때만 나머지 8개를
  후보로 추가) — 테스트가 항상 같은 가짜 응답을 받아야 결정적이기 때문이다. 실
  Bedrock을 부르는 기본 경로(`llm=None`)에서만 9개 전체가 활성화된다.

## UI에 "현재 사용 모델" 표시

`agent.py`의 서브 에이전트 노드(`_make_agent_node`)와 `execution_agent` 결정
노드(`_execution_decide_node`)가 응답마다 `llm_utils.extract_active_model()`로
모델 ID를 뽑아 `SupervisorState.active_model`에 담아 반환한다(값이 없으면 그
턴엔 아예 키를 안 돌려줘서, LangGraph의 부분 업데이트 규칙상 이전 값을 안
덮어쓴다). `pipeline.finalize()`가 그래프 최종 상태(`result.get("active_model")`)
에서 이 값을 읽어 `response["active_model"]`에 담는다. `POST /query` 응답에
`active_model` 키로 그대로 노출되고, `ui/streamlit_app.py`의 질의응답 화면이 각
답변 턴에 이 값을 캡션으로 보여준다.

**한계**: 여러 서브 에이전트가 한 턴에 같이 도는 복합 질문(Plan-Execute)이면
`active_model`은 "그중 가장 마지막에 응답한 모델"이다 — 정확한 호출별 이력이
아니라 UI 배지용 근사치다. `answer_chain`/`retriever` 단계가 실제로 어느 모델로
답했는지는 이 필드에 안 반영된다(LCEL 체인 중간에서 원본 메시지의
`response_metadata`가 파서 단계에 먹혀 버려서, 반영하려면 체인 구조를 더 크게
바꿔야 한다 — 지금은 "서브 에이전트가 실제로 추론한 모델"만 보여주는 것으로 범위를
좁혔다).

## 갱신 시 체크리스트

- 새 모델을 추가/제거하거나 순위를 바꾸면: 이 문서의 표 + `llm_utils.MODEL_PRIORITY`
  둘 다 갱신.
- 추가하는 모델이 실제로 이 계정·리전에서 쓸 수 있는지 실제 `converse()` 호출로
  먼저 확인한다(가정하지 않는다).
- `tests/test_regression.py`는 그대로 통과해야 한다 — FakeLLM 주입 경로는 이 변경과
  무관해야 한다.
