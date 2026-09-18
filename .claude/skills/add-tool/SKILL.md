---
name: add-tool
description: 이 프로젝트(mini-pjt_이태준)에 새 도구(로컬 또는 MCP)를 추가할 때 빠뜨리기 쉬운 등록 지점을 순서대로 챙긴다. "새 도구 추가해줘", "MCP 도구 하나 더 만들어줘" 같은 요청에 사용.
allowed-tools: Read Edit Write Bash
---

# 새 도구 추가 체크리스트

`aws/gcp/azure_check_incidents`를 추가할 때 테스트의 가짜 MCP 스텁 목록을 안 갱신해서
`RuntimeError`가 나고, `agent.py`에 `import authz`를 빠뜨려 `NameError`가 났던 실수를
겪은 뒤 정리한 체크리스트다. 순서대로 진행한다.

## 1. 도구 구현

- **합성 데이터를 다루는 로컬 도구**라면 `src/tools.py`에 `@tool` 함수로 추가한다
  (Pydantic `args_schema`, 결정적 동작, "언제 써야 하는지" docstring — 기존 도구들과
  같은 스타일).
- **실제 외부 데이터(API)를 다루는 도구**라면 `src/incident_feeds.py` 같은 별도 모듈로
  분리한다 — 합성 데이터 도구와 섞으면 "이게 진짜 데이터인지 합성인지" 구분이 안 된다.
  실패 시 예외를 삼키고 "조회 불가"로 답하는 방어적 처리를 반드시 넣는다(외부 API 실패가
  도구 실패로 번지면 안 된다).

## 2. MCP로 노출해야 하면 `mcp_servers/cost_server.py`에 등록

- provider별 래퍼 함수 추가 (`def check_incidents(...): return incident_feeds.check_incidents(PROVIDER, ...)`)
- `TOOL_SPECS`에 `f"{PROVIDER}_도구이름"` 형태로 항목 추가 (이름 충돌 방지 — provider
  접두어 필수)
- `TOOLS_IMPL` 딕셔너리에도 같은 키로 등록

## 3. `src/agent.py`에 배정

- `AGENT_TOOLS[에이전트이름]` 리스트에 도구 이름 추가
- LLM이 스스로 "이건 내 역할이 아니다"라고 판단해 도구를 안 부르는 경우가 많았다
  (이 프로젝트에서 반복된 문제) — 필요하면 `_system_prompt_for()`에 "이런 상황이면
  반드시 이 도구를 호출하라"는 명시적 규칙을 추가한다.
- 새로 만든 함수/모듈을 쓴다면 상단 `import`도 빠뜨리지 않는다 (`import authz` 빠뜨려서
  `NameError`가 난 적이 있다 — 컴파일 체크(`py_compile`)로는 안 잡히고 실제 호출
  시점에야 드러나는 실수다).

## 4. `tests/test_regression.py`의 가짜 MCP 스텁 갱신 (MCP 도구인 경우 필수)

`_fake_mcp_stub_tools()`의 `names` 리스트에 새 도구 이름을 추가한다. **이걸 빠뜨리면
`anomaly_agent`/`optimization_agent` 등을 실제로 라우팅하는 기존 테스트가 전부
`_tool_fns_for()`의 `RuntimeError`("도구를 찾을 수 없습니다")로 깨진다** — 실제로
겪은 실수다.

## 5. 컴파일 + pytest

```bash
cd mini-pjt_이태준
python -m py_compile src/*.py mcp_servers/*.py tests/*.py
python -m pytest tests/ -q
```

## 6. 실제 스모크 테스트

MCP 도구라면 반드시 진짜 MCP 서브프로세스를 띄워서 확인한다 — FakeLLM 테스트만으로는
provider 파라미터 전달, stdio 통신, 실제 API 응답 형식 문제를 못 잡는다. 스크래치패드에
임시 스크립트를 만들어 `mcp_client.load_mcp_tools()` → `agent.build_supervisor()` →
`pipeline.ask()`로 실제 질문을 넣고 `trace`에 새 도구 호출이 찍히는지 확인한다.

## 7. 회귀 검증 + 문서 갱신

- `regression-check` 스킬로 전체 재확인 (특히 `run_eval.py --round 1`이 20/20을
  유지하는지)
- `README.md`의 "핵심 코드 위치"·"트라이앤에러 회고", 필요하면 `SERVICE.md`의 도구 표에
  새 도구를 반영
- 패턴 구현 상태나 도구 개수처럼 `update-briefing` 스킬이 다루는 사실이 바뀌었다면 그
  스킬로 요약 아티팩트도 갱신한다
