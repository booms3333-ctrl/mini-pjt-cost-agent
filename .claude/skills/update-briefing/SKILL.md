---
name: update-briefing
description: 이 프로젝트(mini-pjt_이태준)의 5분 요약 아티팩트("FinOps 에이전트 브리핑")를 최신 코드·평가 결과에 맞춰 갱신한다. 에이전트 코드가 바뀌어 패턴 구현 상태·평가 지표·아키텍처·남은 과제가 실제로 달라졌을 때 사용. 사용자가 명시적으로 "코드 바뀌면 이 자료도 갱신해줘"라고 요청해서 만든 스킬이다.
allowed-tools: Read Bash Artifact
---

# 요약 아티팩트 갱신

아티팩트 URL: **https://claude.ai/artifact/Hj6scBEFwTocrz5Wb3SAJQ**
(메모리에도 저장돼 있음: `finops_agent_summary_artifact.md`)

사소한 변경(주석 수정, 리팩토링만)까지 매번 갱신하지 않는다. 아래 "사실"이 실제로
달라졌을 때만 진행한다:
- 12개 패턴 구현 상태 (완료/부분/미구현)
- 평가 지표 숫자 (결정적 판정 X/20, LLM-as-Judge 범위, RAGAS, 이상탐지 recall)
- 아키텍처 구조 (에이전트·도구 추가/제거)
- "남은 과제" 목록

## 1. 최신 사실 수집

```bash
cd mini-pjt_이태준
cat evaluation/round1_report.md
cat evaluation/round2_report.md
```
필요하면 `regression-check` 스킬로 최신 숫자를 직접 재확인한다. `src/agent.py`의
`AGENT_TOOLS`/`AGENT_NAMES`, `README.md`의 "구현 현황"·"남은 한계" 섹션도 대조해서
패턴 구현 상태와 남은 과제 목록이 여전히 맞는지 확인한다.

## 2. 현재 게시된 내용 읽기

```
Artifact(action: "read", url: "https://claude.ai/artifact/Hj6scBEFwTocrz5Wb3SAJQ")
```
원본 HTML 파일은 세션마다 바뀌는 스크래치패드 경로에 있었으므로 재사용할 수 없다 —
항상 이 read 결과를 기준으로 수정한다. 결과가 로컬 파일로 저장되면 그 파일을, 내용이
바로 오면 새 파일에 저장한 뒤 편집한다.

## 3. 바뀐 부분만 수정

- 스코어카드(`.scorecard` 안의 `.stat` 4개), 패턴 체크리스트(`.pattern-grid`),
  mermaid 아키텍처 다이어그램, "남은 과제"(`ul.tasks`) 중 실제로 바뀐 부분만 고친다.
- 톤·구조·팔레트(따뜻한 종이색 배경 + 원장부 그린 accent + 앰버 alert)는 그대로
  유지한다 — 이미 확정된 디자인이다.

## 4. 같은 URL로 재게시

```
Artifact(file_path: "<수정한 로컬 파일 경로>", url: "https://claude.ai/artifact/Hj6scBEFwTocrz5Wb3SAJQ")
```
`favicon`/`icon`은 넘기지 않는다(생략하면 기존 값 유지). **`url`을 반드시 넘겨야
한다** — 안 넘기면 별도의 새 아티팩트가 생성돼 링크가 끊긴다.

## 5. 사용자에게 보고

무엇이 바뀌었는지 1~2문장으로만 알린다 (예: "패턴 8 완료로 갱신, 평가 지표는 그대로").
