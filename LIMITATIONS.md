# LIMITATIONS · 한계·보안 모델 요약 + DB 확장 방향성

README.md의 "트라이앤에러 회고"에 사실들은 다 적혀 있지만 시간순 서술이라 "지금 이
프로젝트의 한계가 뭐야?"를 한 번에 훑어볼 수가 없다. 이 문서는 그걸 스캔하기 쉬운
표로 재정리하고, `ERD.md`가 미뤄뒀던 "대용량 데이터로 커지면 어떻게 바꿔야 하는가"에
대한 방향성을 덧붙인다. **여기 적힌 것 중 다수는 이미 README/SERVICE/ERD에 사실로
존재하던 내용이고, 일부(§1의 `aws_list_idle` 관련 항목)는 이 문서를 정리하며 새로
확인한 것이다** — 아래 각주에 구분해뒀다.

## 1. 보안 모델 요약

| 항목 | 실제 동작 | 한계 |
|---|---|---|
| `requester_team` | `POST /query`의 요청 필드 → `authz.set_requester_team()`으로 contextvar에 저장, 요청 하나(`pipeline.ask`/`resume` 한 번) 동안만 유지 | **인증이 아니라 자기 신고 값이다.** 로그인/세션 기반 신원 검증은 스코프 밖 — 클라이언트가 아무 팀이나 적어 보내면 그대로 믿는다 |
| 로컬 도구 경로 | `authz.resolve_team_filter()`(팀 필터 강제) / `authz.check_resource_team()`(리소스 소유 팀 확인)이 DB 쿼리 직전에 걸림 — 프롬프트로 "나는 team-a인데 team-b 것도 보여줘"라고 시켜도 서버 쪽에서 우회 불가 | 없음(설계상 완전 강제) |
| MCP 도구 중 리소스 단위 조회(`aws/gcp/azure_get_utilization`) | `agent.py`의 `_MCP_RESOURCE_SCOPED_TOOLS`가 실제 MCP 호출 **전에** 부모 프로세스에서 `tools.resource_team()`으로 소유 팀을 먼저 확인해 차단(`_mcp_resource_authz_denial`) | 이 3개 도구에만 적용된 개별 우회 장치 — 아래 항목 참고 |
| MCP `get_cost`류 | provider 계정 전체 합산만 제공, `team` 인자 자체가 없음 | 팀별로 나눠보는 경로 자체가 없어서 안전(우회할 인자가 없음) |
| **MCP `aws/gcp/azure_list_idle`** † | `mcp_servers/cost_server.py`의 `list_idle()`이 `tools.list_idle_resources.func(provider=...)`를 **team 인자 없이** 호출한다. 로컬 버전(`tools.list_idle_resources`)은 내부에서 `authz.resolve_team_filter(None)`을 불러 요청자가 제한돼 있으면 본인 팀으로 좁히지만, **이 resolve가 일어나는 곳이 MCP 자식 프로세스라 contextvar가 비어 있다**(항상 "제한 없음"으로 풀림) | **팀이 제한된 요청자가 "유휴 리소스 있어?"를 물으면 `optimization_agent`가 이 MCP 도구를 호출해 전 팀의 유휴 리소스를 그대로 보게 된다.** `aws/gcp/azure_get_utilization`과 같은 종류의 프로세스 경계 문제인데, 그 셋만 `_MCP_RESOURCE_SCOPED_TOOLS`로 막혀 있고 `list_idle`류는 안 걸려 있다 |
| `check_incidents` | 팀 개념이 없는 공개 상태 피드라 authz 대상 자체가 아님 | 해당 없음 |

† 이 행은 이 문서를 작성하며 코드를 다시 확인하다 새로 발견한 것이다 — 기존
문서(SERVICE.md §4 규칙 5)는 "MCP는 `get_utilization`만 부모 프로세스에서 가로챈다"고
정확히 적어뒀지만, `list_idle`도 같은 종류의 팀 데이터를 다루는데 같은 보호가 없다는
점까지는 명시돼 있지 않았다.

## 2. 평가·품질 한계

| 항목 | 내용 |
|---|---|
| LLM-as-Judge 변동성 | `--llm-judge`는 결정적 판정(20/20 안정)과 달리 **17~20/20 사이에서 run마다 다르게 나온다** — 에이전트 답변 생성도 채점 LLM의 PASS/FAIL 판정도 `temperature=0`에서 Bedrock이 완벽히 결정적이지 않기 때문. 실패 문항만 다시 돌리면 대부분 통과한다(→ 채점 변동성, 회귀 아님) |
| RAGAS 표본 크기 | faithfulness/answer_relevancy/context_precision 전부 1.0이지만, `retrieve_docs`를 타는 문항이 20건 중 1건뿐이라 표본이 얇다 |
| 독립 검증 안 된 구성요소 | `answer_chain` 구조화, RAG 리랭킹/쿼리확장은 전체 파이프라인 실행에서 간접적으로만 거쳤고 각각 따로 뜯어서 검증하지는 않았다 |
| Observability | 로컬 JSONL 트레이스까지만 확인, LangSmith 실 연동은 미검증(계정 없음) |

## 3. 데이터·외부 연동 한계

| 항목 | 내용 |
|---|---|
| AWS 절감률 | GCP(공식 CUD 문서)·Azure(Retail Prices API 실측 스냅샷)는 실제 자료 기반인데, AWS는 Price List API가 `AccessDeniedException`으로 막혀 있어 이 프로젝트 가정치를 그대로 쓴다 — 권한이 생기면 Azure와 같은 스냅샷 방식으로 바꿀 수 있음 |
| 장애 피드 성격 차이 | GCP(`status.cloud.google.com`)는 과거 이력을 제공하지만 AWS·Azure 피드는 "현재 진행 중인 이슈"만 보여준다 — 과거 날짜 조회 결과가 비어 있어도 "그날 장애가 없었다"고 단정할 수 없다(도구 출력에 항상 이 캐비앗 포함) |
| 다중 통화 | `costs.currency` 컬럼은 있지만 실제 데이터는 전량 `'USD'` — 다중 통화가 들어오면 환율 처리가 새로 필요하다(4절 참고) |
| Chroma 재색인 스킵 | `retriever.py`가 코퍼스 해시로 재임베딩 여부를 판단한다 — 정책 문서를 수정했는데 해시 계산에 포함 안 되는 방식으로 바꾸면(예: 파일명만 바꾸고 내용 그대로) 스킵 로직이 이걸 "안 바뀜"으로 오판할 수 있음(현재는 `source + page_content`를 다 해싱해서 이 경우는 없음, 향후 코퍼스 구성 방식이 바뀌면 재확인 필요) |

## 4. 대용량 데이터 처리를 위한 DB 설계 방향성

지금 구조(`ERD.md` 참고)는 **합성 데이터·데모 규모**에 맞춘 것이라, 실 서비스로
키우면 아래 지점들을 순서대로 검토해야 한다. 전부 "지금 당장 필요"가 아니라
**어느 임계치를 넘으면 필요해지는지**를 같이 적었다.

### 4.1 인덱스·PK — 가장 먼저, 가장 저비용

`costs`/`resource_utilization`은 지금 **PK도 인덱스도 없다** — `resource_id`나
`usage_date`로 조회할 때마다 풀스캔한다. 합성 데이터(리소스 10여 개 × 90일)에서는
안 느껴지지만, 실 데이터로 리소스 수백~수천 개 × 수년치가 쌓이면(수백만~수억 행)
`detect_cost_anomaly`/`get_cost_by_service`/배치 스케줄러가 매번 전체 테이블을
읽게 된다.
- `costs(resource_id, usage_date)` 복합 인덱스 — 리소스별 시계열 조회(현재 가장 흔한 접근 패턴)
- `costs(tag_team, usage_date)` — authz로 팀 필터가 걸린 조회가 많아질수록 필요
- `resource_utilization(resource_id, usage_date)` — 같은 이유
- 자연키 기반 복합 PK(`resource_id, usage_date` 등) 또는 서러게이트 PK를 추가해서
  같은 날짜 데이터가 중복 삽입되는 걸 DB가 막게 한다(지금은 애플리케이션 코드가
  실수 안 하길 바라는 것뿐이다).

### 4.2 무한정 누적되는 테이블 — 보존/파티션 정책

`history.db`/`batch_log.db`는 **절대 안 지워진다**(costs.db와 다른 설계 의도 —
ERD.md 참고). 의도는 맞지만, 실 서비스로 몇 년 돌면 두 테이블은 계속 커지기만
하고 지금은 그걸 관리할 방법이 코드에 없다.
- 시간 기준 파티션(월별 테이블 또는 Postgres 선언적 파티셔닝)으로 바꾸면, 오래된
  구간을 `DELETE`(느림, 인덱스 재정렬 유발) 대신 파티션 단위로 `DROP`할 수 있다.
- "몇 개월 지난 대화 이력은 콜드 스토리지로 내보내고 DB에선 지운다" 같은 보존
  정책이 필요해지는 시점 — 지금은 조회 API(`GET /history`)가 항상 라이브 테이블만
  본다는 전제라, 아카이빙을 넣으려면 조회 경로도 "최근/과거" 분기가 필요해진다.

### 4.3 정규화 vs 비정규화 — 지금의 선택은 "일단 유효"

`costs.service`/`costs.tag_team`은 `resources`에서 매일 그대로 복사된
비정규화 컬럼이다(생성 스크립트가 리소스 속성을 매일 복사). 지금 규모에서는
문제없지만:
- **장점 유지 조건**: 리소스의 team/service가 사실상 안 바뀐다는 전제가 깨지면(예:
  리소스를 다른 팀으로 재배정하는 기능이 생기면), 과거 행에 남은 옛 팀 값과
  `resources`의 현재 팀 값이 달라지는 시점부터 이 비정규화가 "이력을 보존한다"는
  의미로 바뀐다 — 이게 의도인지 버그인지 코드가 지금은 구분하지 않는다.
- 대규모에서 `resources`를 조인하는 대신 매일 복사하는 지금 방식은 조회 성능은
  유리하지만 저장 비용이 시계열 길이만큼 커진다 — 리소스 속성 변경이 드물다면
  지금처럼 비정규화 유지가 맞고, 자주 바뀐다면 조인 + 캐시(머티리얼라이즈드 뷰)로
  바꾸는 게 나을 수 있다. 어느 쪽이든 **실제 변경 빈도를 재본 뒤에** 결정할 문제다.

### 4.4 자유 텍스트 → 구조화 컬럼

`actions_log.detail`, `anomaly_batch_runs.detail`은 사람이 읽을 문장 그대로 저장된
자유 텍스트다(리소스ID·비용·z-score가 텍스트 안에 섞여 있음). 지금은 화면에
그대로 보여주면 되니 문제없지만, "지난 6개월 이상탐지를 리소스별로 다시 집계해줘"
같은 분석 질의가 생기면 텍스트를 매번 파싱해야 한다. 데이터가 커질수록 이 파싱
비용이 누적되므로, 분석 수요가 실제로 생기면 `resource_id`/`cost_amount`/`z_score`를
별도 컬럼으로 두는 구조로 바꾸는 게 맞다(원문 텍스트는 `detail`에 그대로 유지해서
화면 표시용으로 계속 쓸 수 있다).

### 4.5 집계 전용 뷰/사전계산 테이블

대시보드성 조회(이번 달 총액, provider별 합계)는 지금 매번 `costs`의 일별 원본
행을 그때그때 집계한다. 데이터가 커지면(수년치 일별 데이터) 이 집계 자체가
느려진다 — 월별/일별 롤업을 미리 계산해두는 요약 테이블이나(배치가 계산해서
채움) DB 쪽 머티리얼라이즈드 뷰를 검토할 시점이 온다. 원본 일별 데이터는 그대로
두고 롤업은 "다시 계산 가능한 캐시"로 취급하는 게 안전하다(원본을 지우지 않음).

### 4.6 엔진 교체 — 무엇을, 어떤 순서로, 어떻게

SQLite는 파일 하나 + 단일 writer 락이라, 지금처럼 "요청마다 짧게 읽고 배치가 가끔
쓰는" 패턴에서는 충분하다. 하지만 **테이블마다 성격이 달라서 교체 대상도 하나가
아니다** — `costs.db`(분석 위주)와 `history.db`/`batch_log.db`/`checkpoints.db`
(트랜잭션 위주)는 애초에 다른 종류의 엔진이 필요하다. 아래는 후보(DuckDB/
PostgreSQL/ClickHouse)를 어떤 순서로, 어느 테이블에 적용할지와, 각각 실제로
바꿀 때 해야 할 작업·리스크다.

#### 교체 우선순위

| 순위 | 후보 | 대상 | 트리거(언제 필요해지는가) |
|---|---|---|---|
| 1 | **DuckDB** | `costs.db`(`resources`/`costs`/`resource_utilization`/`actions_log`) | 4.1(인덱스)만으로 감당 안 되는 스캔·집계 속도 저하 — 가장 먼저, 가장 저risk로 시도할 후보 |
| 2 | **PostgreSQL** | `history.db`, `batch_log.db`, `checkpoints.db` | `app.py`를 여러 인스턴스로 수평 확장하거나, HITL 재개 상태를 인스턴스 간 공유해야 할 때 |
| 3 | **ClickHouse** | (조건부) `costs.db` 재이전 | DuckDB 단일 노드로도 감당 안 되는 규모(수억~수십억 행) 또는 초당 다중 동시 쓰기가 실제로 필요해질 때 — **지금 이 프로젝트 규모에서는 권장하지 않음**, 아래 3항 참고 |

우선순위가 이 순서인 이유: `costs.db`는 지금 병목이 실제로 문서화돼 있는 쪽이고
(4.1의 "인덱스 없음"), DuckDB는 **서버 없이(임베디드) 파일 하나로 SQLite를 그대로
대체**할 수 있어 교체 리스크가 가장 작다. PostgreSQL은 `costs.db`엔 과할 수 있지만
`history.db`류(트랜잭션·FK가 실제로 의미 있는 데이터)엔 꼭 필요해지는 지점이 온다.
ClickHouse는 셋 중 유일하게 **새 서버 인프라**가 필요하고 진짜 대규모(단일 회사의
멀티클라우드 비용이 아니라 다수 고객사를 SaaS로 서비스하는 규모)에서나 의미가 있다.

#### ① DuckDB — `costs.db` (1순위)

**왜**: 임베디드(SQLite처럼 서버 없이 파일 하나)라 운영 부담이 거의 늘지 않는데,
컬럼 저장 + 벡터화 실행이라 지금 4.1에서 지적한 "인덱스 없이 매번 풀스캔"하는
집계·시계열 쿼리(`detect_cost_anomaly`, `get_cost_by_service`, 대시보드 롤업)에서
SQLite보다 훨씬 빠르다. SQL 방언이 표준 SQL에 가까워 `src/tools.py`의 쿼리 대부분을
거의 그대로 옮길 수 있다.

**해야 할 작업**:
1. `requirements.txt`에 `duckdb` 추가.
2. 1회성 이전 스크립트 작성 — DuckDB의 `sqlite_scanner`(`ATTACH 'costs.db' AS s (TYPE sqlite)`)로 기존 SQLite 파일을 직접 읽어 새 DuckDB 파일로 복제(별도 ETL 파이프라인 없이 SQL 한 번으로 가능).
3. `src/tools.py`의 `_connect()`를 `sqlite3.connect(...)` → `duckdb.connect(...)`로 교체. 쿼리 파라미터 바인딩(`?`)은 DuckDB도 지원하지만, `actions_log.id`처럼 `AUTOINCREMENT`를 쓰던 PK는 DuckDB의 `SEQUENCE`/`GENERATED ALWAYS AS IDENTITY`로 다시 선언해야 한다.
4. `scripts/generate_data.py`(재생성 스크립트)가 SQLite 파일을 지우고 다시 만드는 부분을 DuckDB 파일 기준으로 수정.
5. `tests/test_regression.py`의 authz/도구 회귀 테스트를 그대로 재실행해 SQL 동작 차이(문자열 함수, 날짜 비교 등 방언 차이)가 없는지 확인.

**리스크**:
- **동시 쓰기 모델이 SQLite와 비슷하다** — 한 번에 하나의 writer 연결만 쓸 수 있어, 이 자체로는 "여러 `app.py` 인스턴스가 동시에 쓰는" 문제를 풀지 못한다(지금처럼 배치가 유일한 writer인 구조에서는 문제없음).
- DuckDB는 SQLite보다 상대적으로 신생 프로젝트라 프로덕션 장기 운영 사례가 더 적다(다만 분석 워크로드 채택은 빠르게 늘고 있음).
- DB 레벨 접근 제어가 SQLite와 마찬가지로 없다 — `authz.py`의 애플리케이션 레벨 강제는 그대로 필요(퇴보 아님, 현재와 동일).

#### ② PostgreSQL — `history.db` / `batch_log.db` / `checkpoints.db` (2순위)

**왜**: 이 셋은 분석용이 아니라 "정확히 하나의 기록이 정확히 한 번 남아야 하는"
트랜잭션성 데이터다. 다중 `app.py` 인스턴스를 운영하려면 `checkpoints.db`를
프로세스 간에 공유해야 하는데, SQLite 파일로는 안전하게 공유할 방법이 없다.

**해야 할 작업**:
1. Postgres 인스턴스 준비(관리형 서비스 또는 자체 호스팅) — `.env.example`에 `DATABASE_URL` 추가.
2. `checkpoints.db`: `AsyncSqliteSaver` → `langgraph-checkpoint-postgres`의 `AsyncPgSaver`로 교체. LangGraph 체크포인터 인터페이스는 동일해서(`.setup()` 등) 코드 변경 자체는 작지만, 이 프로젝트가 고정한 LangChain/LangGraph 1.x 버전과의 호환 여부를 먼저 확인해야 한다([CLAUDE.md](CLAUDE.md)가 이미 겪은 `langchain_classic` 이동 같은 버전 호환 문제가 재발할 수 있는 지점).
3. `qa_history.py`/`batch.py`: `sqlite3` 호출부를 `psycopg`(또는 `asyncpg`)로 교체, 타임스탬프를 지금의 ISO 텍스트 문자열 대신 실제 `TIMESTAMPTZ` 컬럼으로 바꿀 좋은 기회(현재 한계 하나를 같이 해소).
4. 기존 `history.db`/`batch_log.db`의 행을 Postgres로 옮기는 1회성 이전 스크립트 — `id`/`thread_id` 값을 그대로 보존해야 한다(`thread_id`는 `checkpoints.db`와 애플리케이션 레벨로 상관관계가 있으므로).
5. `requirements.txt`/README 실행 절차 갱신(로컬 실행에 Postgres가 새로 필요해짐 — 지금의 "설치 없이 바로 실행" 경험이 깨진다는 걸 문서에 명시).

**리스크**:
- 지금까지 없던 **운영 대상 외부 서비스**가 생긴다(백업, 커넥션 풀, 자격증명 관리) — 데모/단일 사용자 규모에는 과한 복잡도일 수 있다.
- `AsyncPgSaver`와 이 프로젝트 LangGraph 버전의 호환성 미확인.
- 비동기 드라이버 선택(`asyncpg` vs `psycopg` async 모드)이 `app.py`의 FastAPI 비동기 흐름과 안 맞으면 이 프로젝트가 이미 한 번 겪은 것과 같은 종류의 동시성 버그(MCP 도구가 비동기 전용이라 `ainvoke`를 써야 했던 것과 같은 계열)가 재발할 수 있다 — 전환 후 회귀 스위트 재실행이 필수.
- 이전 중 다운타임/정합성 — 행 수 검증 후 전환하는 절차가 필요.

#### ③ ClickHouse — 조건부, 지금은 권장하지 않음 (3순위)

**언제 실제로 필요해지는가**: `costs`/`resource_utilization`이 DuckDB 단일 노드
용량을 넘어서거나(대략 수억~수십억 행, 또는 디스크/메모리가 한 대에 안 들어가는
규모), 초당 다중 동시 삽입이 필요한 실시간 스트리밍 수집으로 바뀌거나, 여러
고객사(SaaS화) 데이터를 한 클러스터에서 다뤄야 할 때다. **지금 이 프로젝트가
가정하는 규모(회사 하나, 리소스 수백~수천 개, 일별 데이터 수년치)는 이 조건에
해당하지 않는다** — DuckDB로 충분할 가능성이 크다.

**해야 할 작업(실제로 필요해졌을 때)**:
1. ClickHouse 서버 운영(자체 호스팅 또는 ClickHouse Cloud) — 완전히 새로운 운영 축.
2. 테이블 엔진(`MergeTree` 계열) 선택과 `ORDER BY`/`PARTITION BY` 키 설계 — 이건 나중에 바꾸기 어려운 결정이라 처음부터 실제 조회 패턴(리소스 단위 시계열 스캔)에 맞게 잡아야 한다.
3. DuckDB/Postgres에서 데이터를 옮기는 ETL(Parquet 내보내기 → ClickHouse 임포트, 또는 ClickHouse의 외부 DB 엔진으로 직접 읽기).
4. 쿼리 계층 재작성 — 표준 SQL과 다른 부분(비동기 "mutation"으로 처리되는 UPDATE/DELETE, `FINAL` 키워드로의 중복 제거 등)이 있어 `src/tools.py`를 다시 손봐야 한다.

**리스크**:
- 세 후보 중 **운영 복잡도가 가장 높다** — 분산 시스템을 새로 운영하는 부담.
- **진짜 트랜잭션 보장이 없다**(업데이트/삭제가 비동기 mutation) — 그래서 `history.db`/`checkpoints.db`류로는 절대 옮기면 안 된다. `costs.db`(주로 append, 드문 수정)에만 후보가 된다.
- **조기 최적화 위험**: 실제 병목을 실측하기 전에 먼저 들이면, 이 프로젝트 규모에서는 얻는 이득보다 운영·전환 비용이 더 클 가능성이 높다.
- 대안으로 **TimescaleDB**(PostgreSQL 확장)를 검토할 수 있다 — 새 엔진을 안 늘리고 ②의 PostgreSQL 안에서 시계열 파티셔닝·압축·보존 정책(TTL과 유사한 `drop_chunks`)까지 얻을 수 있어서, "두 번째 전용 엔진"보다 운영 부담이 작다. ClickHouse는 TimescaleDB로도 부족한 게 실측으로 확인된 뒤에만 고려한다.

### 우선순위 제안 (전체 §4 기준)

임계치가 언제 오는지는 실제 트래픽을 재봐야 정확하지만, **비용 대비 효과** 기준으로
순서를 매기면: 4.1(인덱스, 코드 변경 없이 스키마만 추가) → **4.6① DuckDB**(가장 저risk 엔진 교체) → 4.4(구조화 컬럼, 분석 수요가 생기면) → 4.2(보존 정책, 데이터가 실제로
오래 쌓이기 시작하면) → 4.5(집계 캐시, 대시보드가 느려지면) → **4.6② PostgreSQL**
(동시 쓰기·다중 인스턴스가 실제로 필요해지면). 4.3(정규화 방향)은 별도 트리거(리소스
재배정 같은 새 기능)가 있을 때만 재검토하고, **4.6③ ClickHouse는 위 조건이 실측으로
확인되기 전까지는 시작하지 않는다.**
