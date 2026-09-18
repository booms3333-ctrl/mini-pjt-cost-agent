# anomaly_agent

이동평균 대비 이상 비용 급증을 탐지하고, 실제 클라우드 장애 이력과 대조해 검증하는
서브 에이전트. [SERVICE.md](../SERVICE.md) §3에서 링크됨. `src/batch.py`의 자동
이상탐지 배치([PROCESS_SPEC.md](../PROCESS_SPEC.md) §3)도 이 에이전트가 아니라
`detect_cost_anomaly` 도구를 직접 호출한다 — 배치는 사용자 질의 경로를 안 거친다.

## 담당 도구

| 도구 | 실행 위치 | 기능 |
|---|---|---|
| `detect_cost_anomaly` | 로컬 (`src/tools.py`) | 직전 `window_days` 이동평균 대비 z-score 급증 탐지 |
| `aws_check_incidents` / `gcp_check_incidents` / `azure_check_incidents` | MCP | 클라우드 공개 상태 피드에서 **실제 장애 이력** 조회(합성 데이터 아님, 인증 불필요) |

(`AGENT_TOOLS["anomaly_agent"]`, [agent.py:103-106](../src/agent.py#L103-L106))

`check_incidents`는 AWS(`status.aws.amazon.com`)/GCP(`status.cloud.google.com`)/Azure
(상태 RSS)를 실시간 조회한다(`src/incident_feeds.py`). **AWS·Azure는 현재 진행 중인
이슈만 제공하고 GCP만 과거 이력을 제공**한다는 비대칭이 있다 — 아래 규칙 참고.

## 위험도 / 승인

읽기/계산 전용. [cost_lookup_agent.md](cost_lookup_agent.md)와 같은 이유로
`guardrails.needs_approval()` 경로를 거치지 않는다(승인 게이트는
[execution_agent.md](execution_agent.md)에만 작동).

## 라우팅

`route_question()`이 다음 키워드에 매칭하면 이 에이전트를 후보에 넣는다:

```
이상, 급증, 급등, 튀었, 이상한, anomaly, spike
```
(`_ANOMALY_KEYWORDS`, [agent.py:118](../src/agent.py#L118))

**"계획"류 복합 질의**(`_PLAN_KEYWORDS`: "계획"/"plan")는 이 에이전트와
`optimization_agent`를 **함께** 라우팅한다([agent.py:167-168](../src/agent.py#L167-L168))
— 절감 계획은 이상탐지 결과와 최적화 후보를 함께 봐야 한다는 Plan-Execute 2단계
분해로 취급하기 때문이다.

## 핵심 행동 규칙

시스템 프롬프트([agent.py:242-279](../src/agent.py#L242-L279))에 강제된 4가지 규칙:

1. **복합 질문이어도 이상 급증 여부가 답변에 관련 있으면 `detect_cost_anomaly`를
   반드시 호출한다.** "이건 내 역할이 아니다"라고 판단해 도구를 안 부르는 경우가
   있어서(예: 절감 계획 질문에서 이상탐지를 생략) 예외 없이 명시했다.
2. **원인을 하나로 단정할 근거가 부족하면 단정하지 말고 후보를 여러 개 제시하거나
   되묻는다.** "이번 달이랑 지난달이랑 비교가 안 맞는데 왜 그래?"처럼 모호한 질문에
   `detect_cost_anomaly` 결과만으로 확정적 원인을 답해버리는 문제가 있었다 —
   [SERVICE.md](../SERVICE.md) 정책 3번("근거 없으면 추측하지 않는다")과 직결.
3. **급증을 찾으면 해당 클라우드의 `check_incidents`로 실제 공개 장애 이력을 확인한
   뒤 답한다** (추측 금지). 단, AWS/Azure 피드는 진행 중인 이슈만 주므로 결과가
   비어 있어도 "장애가 없었다"가 아니라 **"과거 이력은 이 피드로 확인할 수 없다"**고
   정확히 표현해야 한다 — 이 구분을 안 하면 실제로 장애가 있었어도 없었다고 잘못
   단정하게 된다.
4. **`z_threshold` 같은 민감도 조정은 이번 조회에만 적용되는 파라미터이지 영구
   설정이 아님을 답변에서 분명히 밝히고, 임계값을 낮추면 오탐(false positive)이
   늘어날 수 있다는 트레이드오프도 안내한다.**
