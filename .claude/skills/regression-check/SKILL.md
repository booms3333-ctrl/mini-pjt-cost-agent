---
name: regression-check
description: 이 프로젝트(mini-pjt_이태준)의 소스를 고친 뒤 전체 회귀를 검증한다 — 컴파일 체크, pytest, 트레이스 정리, run_eval.py 실행까지 한 번에 돌린다. "회귀 확인해줘", "전체 검증해줘", src/agent.py나 tools.py 등을 고친 뒤에 사용.
allowed-tools: Bash Read
---

# 회귀 검증

이 세션(=이 프로젝트를 만든 대화)에서 코드를 고칠 때마다 반복한 4단계 절차다. 실
Bedrock/MCP를 부르는 4단계는 5~6분·실제 비용이 들어가므로, 되도록 소스를 다 고친
뒤 한 번만 돌린다.

## 1. 컴파일 체크

```bash
cd mini-pjt_이태준
python -m py_compile src/*.py evaluation/*.py mcp_servers/*.py scripts/*.py tests/*.py
```
하나라도 실패하면 여기서 멈추고 원인부터 고친다.

## 2. pytest (FakeLLM, 비용 없음)

```bash
python -m pytest tests/ -q
```
전부 통과해야 한다. 실패하면 어떤 테스트가 왜 깨졌는지 먼저 설명하고, 의도된 동작
변경이면 테스트를 같이 고치고, 아니면 소스의 회귀다.

## 3. 트레이스 정리

```bash
rm -f data/traces/*.jsonl
```
누적된 디버그 트레이스를 지운다 — 지우지 않아도 동작엔 문제 없지만 다음 실행 결과를
읽기 좋게 하기 위함이다.

## 4. 실제 평가 20문항 (Bedrock + MCP 3서버 필요)

```bash
python evaluation/run_eval.py --round 1
```
`.env`에 AWS 자격증명이 있어야 한다. 20/20이 나와야 회귀 없음으로 본다. 20 미만이면
`evaluation/round1_result.json`의 `failures`를 읽어 어떤 문항이 왜 실패했는지 확인한다
— 단, LLM-as-Judge(`--llm-judge`)를 쓰지 않는 결정적 판정이라면 단일 실행에서도
안정적으로 20/20이 나와야 정상이다(변동이 있다면 `llm-judge-verify` 스킬 참고).

## 결과 보고 형식

사용자에게는 "컴파일 OK / pytest N passed / eval X/20, 회귀 없음(또는 실패 목록)"
형태로 짧게 보고한다. 각 단계 원문 로그를 그대로 붙여넣지 않는다.
