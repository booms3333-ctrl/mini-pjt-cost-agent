---
name: llm-judge-verify
description: run_eval.py --llm-judge 실행에서 일부 문항이 실패했을 때, 진짜 회귀인지 LLM 출력 변동성(노이즈)인지 구분한다. "LLM-as-Judge 결과가 흔들린다", "이 실패가 진짜야?" 같은 요청에 사용. mini-pjt_이태준 프로젝트 전용.
allowed-tools: Read Bash Write
---

# LLM-as-Judge 변동성 확인

이 프로젝트에서 `--llm-judge`를 켜면 같은 20문항인데도 실행마다 17~20/20 사이로
흔들리는 게 확인된 적이 있다(에이전트 답변 생성도, 채점 LLM의 PASS/FAIL 판정도
`temperature=0`에서 Bedrock이 완벽히 결정적이지 않기 때문). 실패 문항이 나왔을 때
"수정이 불완전해서"가 아니라 "우연히 이번 실행에서 걸린 것"인지 구분하는 절차다.

## 1. 실패 문항 목록 확보

```bash
cd mini-pjt_이태준
python evaluation/run_eval.py --round 2 --llm-judge
cat evaluation/round2_result.json  # "failures" 배열의 id들 확인
```

## 2. 각 실패 문항을 3회씩 반복 실행하는 스크립트 작성

`evaluation/test_queries.csv`에서 실패한 id의 `question`/`expected_traits`/
`forbidden`/`expected_tools`를 그대로 가져와 아래 형태로 스크래치패드에 스크립트를
만든다 (전체 20문항을 매번 다시 돌리면 비용·시간이 크므로 실패한 것만 골라 반복):

```python
import asyncio, sys
from pathlib import Path
ROOT = Path(r"<repo>\mini-pjt_이태준")
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "evaluation"))
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")
import agent, pipeline, mcp_client, run_eval
from langgraph.checkpoint.memory import MemorySaver

async def main():
    mcp_tools = await mcp_client.load_mcp_tools()  # await 필수 — load_mcp_tools_sync()는
                                                     # 이미 실행 중인 이벤트 루프 안에서 못 씀
    graph = agent.build_supervisor(mcp_tools=mcp_tools, checkpointer=MemorySaver())
    judge = run_eval.make_llm_judge(agent._default_llm())
    for item in ITEMS:  # 실패했던 문항들
        for i in range(3):
            config = {"configurable": {"thread_id": f"verify-{item['id']}-{i}"}}
            response = await pipeline.ask(graph, item["question"], config)
            print(item["id"], i, judge(item, response))

asyncio.run(main())
```

## 3. 판정

- **3/3 통과** → 노이즈. 수정이 불완전한 게 아니다. 원래 20/20이던 결정적 판정은
  건드리지 않았을 가능성이 높으니, 그 사실만 사용자에게 보고한다.
- **반복적으로 실패(0~1/3)** → 진짜 회귀. `test_queries.csv`의 해당 문항
  `expected_traits`/`forbidden`을 다시 읽고, 관련 서브 에이전트의 시스템 프롬프트를
  보강할지 검토한다. 이때 **테스트 문항의 문구를 프롬프트에 그대로 인용하지 않는다**
  (CLAUDE.md의 "하지 말 것" 규칙 — 일반적인 지시로 해결이 안 되면 프롬프트를 더
  밀어붙이는 대신 기대값을 현실적으로 낮춘다).

## 4. 최종 확인

전체 20문항을 `--llm-judge` 없이(결정적 판정) 한 번 더 돌려 20/20이 유지되는지
확인한다 — `regression-check` 스킬 참고. 결정적 판정과 LLM-as-Judge 결과는 서로 다른
채점 방식이므로 절대 같은 숫자로 비교해서 "회귀"라고 결론 내리지 않는다.
