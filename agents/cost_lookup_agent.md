# cost_lookup_agent

멀티클라우드 비용·사용률 조회 담당 서브 에이전트. [SERVICE.md](../SERVICE.md) §3의
"멀티 에이전트 구성"에서 링크됨 — 전체 아키텍처는 그 문서, 실행 흐름은
[PROCESS_SPEC.md](../PROCESS_SPEC.md) §1 참고.

## 담당 도구

| 도구 | 실행 위치 | 기능 |
|---|---|---|
| `get_cost_by_service` | 로컬 (`src/tools.py`) | 기간·서비스·태그별 비용 조회, **멀티클라우드 합산** |
| `aws_get_cost` / `gcp_get_cost` / `azure_get_cost` | MCP (`mcp_servers/cost_server.py`) | provider별 비용 조회 |
| `aws_get_utilization` / `gcp_get_utilization` / `azure_get_utilization` | MCP | provider별 인스턴스·볼륨 사용률 조회 |

(`AGENT_TOOLS["cost_lookup_agent"]`, [agent.py:98-102](../src/agent.py#L98-L102))

`get_cost_by_service`만 로컬에 남은 이유: 멀티클라우드 합산이 필요한데 어느 한 계정
API도 다른 계정 비용은 모르기 때문에, 그 합산은 오케스트레이션 계층(이 에이전트)의
몫이다. 나머지는 provider별 MCP 서버(`MCP_PROVIDER` 환경변수로 파라미터화된 자식
프로세스 3개)가 각자의 계정 경계 안에서만 응답한다.

## 위험도 / 승인

전부 읽기 전용. `guardrails.RISK_LEVELS`엔 `get_cost_by_service`/`get_resource_utilization`이
`"read"`로 등록돼 있지만, **실제로 이 값이 조회되는 경로가 없다** —
`guardrails.needs_approval()`은 코드 전체에서 [agent.py:612](../src/agent.py#L612)
(`_execution_approve_node`) 한 곳에서만 호출되고, 이 에이전트의 ReAct 루프는
`ToolNode`로 도구를 바로 실행할 뿐 승인 게이트를 거치지 않는다. 승인 게이트가 실제로
작동하는 건 [execution_agent.md](execution_agent.md)뿐이다.

## 라우팅

`route_question()`([agent.py:147-174](../src/agent.py#L147-L174))이 질문에 다음
키워드가 있으면 이 에이전트를 후보에 넣는다(LLM 미호출, 결정적):

```
비용, 얼마, 총액, 청구, 요금, cost, spend, billing, 사용률, 가동, 비싸, 비싼
```
(`_COST_KEYWORDS`, [agent.py:114-117](../src/agent.py#L114-L117))

`"비싸"`/`"비싼"`은 "왜 이렇게 비싸?"처럼 '비용'이라는 단어 없이 묻는 질문도 잡으려고
별도로 추가됐다. 이상탐지 키워드와 동시에 매칭되면 `anomaly_agent`와 함께(각자 독립
실행) 라우팅될 수 있다 — 실행 동사가 있으면 그건 예외적으로 `execution_agent` 단독
라우팅이 된다([execution_agent.md](execution_agent.md) 참고).

## 핵심 행동 규칙

시스템 프롬프트([agent.py:218-227](../src/agent.py#L218-L227))에 강제된 규칙:

- **다른 프로바이더 서비스를 비교할 때, 성격이 다르면(예: 블록 스토리지 vs 오브젝트
  스토리지) 합산하거나 배율로 직접 비교하기 전에 그 차이를 먼저 언급한다.** 성격이
  같은 항목끼리만 직접 비교한다.
  - 배경: LLM-as-Judge 평가에서 "GCP랑 AWS 스토리지 비용을 비교해줘"에 S3(오브젝트
    스토리지)+EBS(블록 스토리지)를 그냥 합쳐 "AWS 스토리지"로 묶고 GCP Cloud
    Storage와 직접 비교한 사례가 발견됐다 — 성격이 다른 항목을 동일시하면 왜곡된
    결론이 된다(`evaluation/test_queries.csv`의 forbidden: "비교 불가능한 항목을 동일시").
