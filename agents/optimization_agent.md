# optimization_agent

절감 시뮬레이션·유휴 리소스 조회·예산 현황·FinOps 정책 문서 검색(RAG)을 담당하는 서브
에이전트. [SERVICE.md](../SERVICE.md) §3에서 링크됨.

## 담당 도구

| 도구 | 실행 위치 | 기능 |
|---|---|---|
| `estimate_savings` | 로컬 (`src/tools.py`) | RI/Savings Plan·다운사이징 절감액 계산(provider별 실제 할인율 반영) |
| `retrieve_docs` | 로컬 (`src/retriever.py`) | FinOps 정책·가격 정책 문서 + AWS/GCP/Azure 공식 비용 최적화 가이드(`scripts/fetch_cost_optimization_guides.py` 스냅샷) 검색 — 하이브리드(BM25+벡터) + 쿼리 확장 + 리랭킹 |
| `get_budget_status` | 로컬 (`src/tools.py`) | 팀별 월간 예산 한도 대비 이번 달 사용률 계산 |
| `aws_list_idle` / `gcp_list_idle` / `azure_list_idle` | MCP | provider별 유휴 리소스 목록화 |

(`AGENT_TOOLS["optimization_agent"]`, [agent.py:116-119](../src/agent.py#L116-L119))

## 위험도 / 승인

읽기/계산 전용. [cost_lookup_agent.md](cost_lookup_agent.md)와 같은 이유로
`guardrails.needs_approval()` 경로를 거치지 않는다(승인 게이트는
[execution_agent.md](execution_agent.md)에만 작동).

## 라우팅

`route_question()`이 다음 키워드에 매칭하면 이 에이전트를 후보에 넣는다:

```
절감, 유휴, idle, savings, reserved, 예약, 다운사이징, downsizing, 최적화, 정책, 한도,
배분, 예산, 조건
```
(`_OPTIMIZATION_KEYWORDS`, [agent.py:128-131](../src/agent.py#L128-L131))

**"계획"류 복합 질의**는 [anomaly_agent.md](anomaly_agent.md)와 함께 자동 라우팅된다
(Plan-Execute 2단계 분해, [agent.py:176-177](../src/agent.py#L176-L177)).

## 핵심 행동 규칙

시스템 프롬프트([agent.py:237-259](../src/agent.py#L237-L259))에 강제된 **절대 규칙**:

- **답을 하기 전에 `retrieve_docs`를 반드시 최소 한 번 호출한다.** 질문이 도구
  범위 밖처럼 보여도 예외가 아니다 — 범위 밖인지 아닌지는 `retrieve_docs` 결과를
  보고 "문서에 근거가 없다"고 확인한 **뒤에만** 판단한다. 호출 없이 "범위
  밖이다/모른다"라고 답하는 것은 금지된다.
  - 배경: "이건 도구 범위 밖입니다"라고 LLM이 스스로 판단해 `retrieve_docs`를
    아예 안 부르고 넘어가는 문제가 여러 차례 다른 문구로도 재현됐다 — "~인 것
    같으면" 식의 조건부 지시는 LLM이 스스로 예외 처리할 여지가 있어서, 조건 없이
    예외 없는 절대 규칙으로 못박았다.
- **질문에 리소스 ID가 이미 특정돼 있으면(다운사이징·RI 전환 등 무엇이든) 다른
  조회 없이 곧바로 `estimate_savings(resource_id, plan_type)`를 그 ID로 호출한다.**
  이 도구는 `resource_id`와 `plan_type`만 받고 크기·유형 등 나머지 정보는 내부에서
  스스로 조회하므로, "리소스 사양 정보가 더 필요하다"는 이유로 호출을 미루거나
  거절하는 것은 금지된다.
- **리소스 ID 없이 일반적인 절감 계획·절감 방안을 묻는 질문이면, 답하기 전에
  `aws_list_idle`/`gcp_list_idle`/`azure_list_idle` 중 최소 하나를 반드시 먼저
  호출해 유휴 리소스 현황을 확인한다.** 유휴 리소스가 없다는 결과가 나와도 그
  자체가 근거이므로 호출 없이 넘어가면 안 된다.
- **절감 계획을 세울 때, 유휴 리소스를 찾았다면 `estimate_savings`로 그 중 하나
  이상의 절감액을 실제로 계산해 구체적인 수치를 제시한다** — 일반론만 말하고 실제
  계산을 생략하지 않는다. 도구 결과 없이 절감률·절감액 수치를 스스로 추정해
  지어내는 것도 금지된다.
