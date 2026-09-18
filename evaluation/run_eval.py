"""test_queries.csv를 자동으로 돌려 round{N}_report.md를 생성한다.

evaluation/eval_lib.py(Day 7 run_eval/compare_eval)와 src/pipeline.py(가드레일 ->
그래프 실행 -> 마스킹)를 그대로 재사용한다. 서버를 띄우지 않고 그래프를 직접
호출하므로 20문항을 반복 실행하는 평가 루프를 빠르게 돌릴 수 있다.

실행 (AWS Bedrock 자격 증명 필요 — 모든 문항이 실제 LLM 호출을 거친다):
    python evaluation/run_eval.py --round 1
    python evaluation/run_eval.py --round 2              # round1_result.json과 자동 비교
    python evaluation/run_eval.py --round 1 --llm-judge   # 결정적 판정 대신 LLM-as-Judge
    python evaluation/run_eval.py --round 1 --ragas       # RAGAS 지표(evaluation/ragas_lite.py)도 계산

기본 판정(--llm-judge 없이)은 LLM을 호출하지 않는다:
  - forbidden 문구가 답변에 그대로 나오면 실패
  - expected_tools가 지정돼 있으면 trace에 그 도구 호출이 다 있어야 통과.
    ";"로 구분된 각 항목은 전부(AND) 필요하고, 그 안에서 "|"로 묶은 대안 중
    하나만 걸리면(OR) 그 항목은 만족한다 — 예: "get_cost_by_service|aws_get_cost"는
    로컬 집계 도구와 provider별 MCP 도구 중 아무거나 호출해도 인정한다.
  - HITL로 승인 대기(status=pending_approval)에 들어간 경우, 요청된 도구가
    expected_tools와 일치하면 "승인 요청까지는 올바르게 갔다"로 보고 통과 처리한다
    (실제 승인 여부는 자동화 루프에 사람이 없어 판단할 수 없다).

expected_traits(자연어 속성 서술)는 결정적으로 채점하기 어려워 --llm-judge에서만
반영된다. 이게 RAGAS/LLM-as-Judge 패턴(12번)의 LLM-as-Judge 쪽 구현이다.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
import time
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BASE_DIR / ".env")

from eval_lib import compare_eval, run_eval  # noqa: E402

CATEGORY_ORDER = ["positive", "negative", "edge", "guardrail"]


def load_eval_set(csv_path: Path) -> list[dict]:
    rows: list[dict] = []
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            rows.append(
                {
                    "id": row["id"],
                    "question": row["input"],
                    "type": row["category"],
                    "expected_traits": _split(row.get("expected_traits", "")),
                    "forbidden": _split(row.get("forbidden", "")),
                    "expected_tools": _split(row.get("expected_tools", "")),
                    # requester_team 비우면 제한 없음(None). thread_ref를 채우면 그
                    # id가 쓴 thread_id를 재사용한다(멀티턴 시나리오 — 같은 대화
                    # 안에서 두 번째 질문도 실제로 다시 라우팅되는지 검증하기 위함).
                    "requester_team": (row.get("requester_team") or "").strip() or None,
                    "thread_ref": (row.get("thread_ref") or "").strip() or None,
                    "note": row.get("note", ""),
                }
            )
    return rows


def _split(field: str) -> list[str]:
    return [part.strip() for part in field.split(";") if part.strip()]


def _response_text(response: dict) -> str:
    if response.get("status") == "pending_approval":
        req = response.get("request", {})
        return f"[승인 대기] {req.get('tool')} {req.get('args')} — {req.get('reason')}"
    return response.get("answer", "")


def _response_text_with_sources(response: dict) -> str:
    """LLM-as-Judge 프롬프트 전용 — _response_text()에 출처 문서명을 덧붙인다.

    pipeline.finalize()는 RAG 출처를 answer 문자열이 아니라 별도 contexts 필드
    (doc_id)에 담는다. deterministic_judge의 forbidden 검사는 이 구조를 그대로 둬야
    하지만(문자열 하나만 보는 게 맞는 설계), LLM 판정은 "출처 문서명 표기" 같은
    expected_traits를 answer 텍스트만 보고 "출처가 없다"고 오판했다(#6, LLM-as-Judge로
    발견) — 실제로는 API 응답의 contexts에 출처가 담겨 나가고 있었을 뿐이다.
    """
    text = _response_text(response)
    doc_ids = [c.get("doc_id") for c in response.get("contexts", []) if c.get("doc_id")]
    if doc_ids:
        text += f"\n(참고: 이 응답은 별도 contexts 필드로 다음 출처를 함께 반환함 — {', '.join(doc_ids)})"
    return text


def _response_tool_names(response: dict) -> set[str]:
    if response.get("status") == "pending_approval":
        return {response.get("request", {}).get("tool")}
    # pipeline.finalize()가 최종 응답의 trace를 조립할 때 도구 이름을 "tool"이 아니라
    # "step" 키에 담는다({"step": ..., "input": ..., "output": ...}, pipeline.py 참고).
    # 여기서 "tool" 키를 읽으면 항상 None만 나와서 expected_tools 체크가 무조건
    # 실패한다 — 실제로 맞는 도구를 불렀어도 fail 처리되던 버그였다.
    return {rec.get("step") for rec in response.get("trace", [])}


def deterministic_judge(item: dict, response: dict) -> bool:
    """LLM 없이 forbidden/expected_tools만 확인한다.

    expected_tools의 각 항목은 "|"로 여러 대안을 묶을 수 있다(예:
    "get_cost_by_service|aws_get_cost") — 로컬 집계 도구와 MCP 프로바이더별
    도구처럼 "둘 중 뭘 불러도 정답"인 경우를 표현하기 위함이다. ";"로 구분된
    항목들은 여전히 전부(AND) 만족해야 하고, 그 안의 "|" 대안 중 하나만
    걸리면(OR) 그 항목은 통과한다.
    """
    text = _response_text(response)
    lowered = text.lower()

    for phrase in item.get("forbidden", []):
        if phrase.lower() in lowered:
            return False

    called = _response_tool_names(response)
    for expected in item.get("expected_tools", []):
        alternatives = expected.split("|")
        if not any(alt in called for alt in alternatives):
            return False

    return bool(text.strip())


def make_llm_judge(llm):
    """LLM-as-Judge: expected_traits/forbidden을 자연어로 판정한다 (패턴 12)."""
    from langchain_core.messages import HumanMessage

    from llm_utils import get_text

    def llm_judge(item: dict, response: dict) -> bool:
        if not deterministic_judge(item, response):
            return False  # forbidden/expected_tools 위반이면 LLM한테 물어볼 것도 없다

        text = _response_text_with_sources(response)
        prompt = (
            "다음 에이전트 응답이 요구 조건을 만족하는지 PASS 또는 FAIL 한 단어로만 답하세요.\n\n"
            f"질문: {item['question']}\n"
            f"응답: {text}\n"
            f"반드시 포함·유지돼야 할 것: {'; '.join(item.get('expected_traits', [])) or '(없음)'}\n"
            f"나오면 안 되는 것: {'; '.join(item.get('forbidden', [])) or '(없음)'}"
        )
        result = llm.invoke([HumanMessage(content=prompt)])
        return "PASS" in get_text(result).upper()

    return llm_judge


def make_answer_fn(graph, answer_chain=None, total: int | None = None):
    """문항마다 실제 LLM 호출이 여러 번(ReAct 도구 선택 + 구조화 출력) 걸려서
    20문항이면 체감상 몇 분씩 걸린다. 그런데 evaluation/eval_lib.py의 run_eval()은
    Day 7 원본 그대로 문항 사이에 아무것도 안 찍어서, 실제로 도는 중인지 멈췄는지
    구분이 안 됐다 — 여기서 진행 상황(번호·경과 시간)을 찍어 그 문제를 없앤다.

    thread_id는 기본적으로 문항마다 새로 발급한다(uuid4) — 각 문항이 독립된
    새 대화라고 가정하기 때문이다. `thread_ref`가 채워진 문항(멀티턴 시나리오의
    두 번째 턴 이상)은 그 id가 이미 발급받은 thread_id를 그대로 재사용한다.
    """
    import pipeline

    counter = {"n": 0}
    thread_ids: dict[str, str] = {}  # csv id -> 이 문항에서 실제로 쓴 thread_id

    def answer_fn(item: dict) -> dict:
        counter["n"] += 1
        n = counter["n"]
        label = f"[{n}/{total}]" if total else f"[{n}]"
        question = item["question"]
        preview = question[:40] + ("..." if len(question) > 40 else "")
        print(f"{label} 처리 중: {preview}", flush=True)

        ref = item.get("thread_ref")
        thread_id = thread_ids.get(ref) if ref else None
        if thread_id is None:
            thread_id = str(uuid.uuid4())
        thread_ids[item["id"]] = thread_id

        start = time.monotonic()
        config = {"configurable": {"thread_id": thread_id}}
        result = asyncio.run(
            pipeline.ask(
                graph, question, config, answer_chain=answer_chain, requester_team=item.get("requester_team")
            )
        )
        elapsed = time.monotonic() - start
        print(f"{label} 완료 ({elapsed:.1f}초)", flush=True)
        return result

    return answer_fn


def run_ragas_lite(eval_set: list[dict], answer_fn, llm=None) -> dict | None:
    """RAG 도구(retrieve_docs)가 걸리는 문항만 다시 물어서 RAGAS 대체 지표를 낸다.

    answer_fn을 재호출하는 이유: run_eval()은 pass/fail 판정만 남기고 원문
    답변/컨텍스트를 버리므로, 지표 계산에 필요한 {question, answer, contexts}를
    다시 받아야 한다. RAG 문항은 test_queries.csv 전체 중 소수라 재호출 비용은
    크지 않다.
    """
    from ragas_lite import evaluate_ragas_lite

    rag_items = [item for item in eval_set if "retrieve_docs" in item.get("expected_tools", [])]
    if not rag_items:
        return None

    print(f"\nRAGAS 대상 문항 {len(rag_items)}건 재실행 중 (지표 계산용 원문 답변 수집)...", flush=True)
    records = []
    for item in rag_items:
        response = answer_fn(item)
        if response.get("status") == "pending_approval":
            continue
        contexts = [c["text"] for c in response.get("contexts", [])]
        records.append({"question": item["question"], "answer": response.get("answer", ""), "contexts": contexts})

    if not records:
        return None
    print(f"RAGAS 지표 계산 중 (문항당 LLM 3회 호출: faithfulness/relevancy/precision)...", flush=True)
    return evaluate_ragas_lite(records, llm=llm)


def _category_lines(result: dict) -> list[str]:
    lines = []
    for cat in CATEGORY_ORDER:
        bucket = result["by_type"].get(cat, {"total": 0, "passed": 0})
        lines.append(f"  - {cat}: {bucket['passed']} / {bucket['total']}")
    return lines


def write_report(path: Path, round_no: int, result: dict, compare: dict | None, ragas_result: dict | None = None) -> None:
    lines = [f"# {round_no}차 자체 평가 결과 (Day {9 if round_no == 1 else 10})", ""]
    lines.append(f"`test_queries.csv` {result['total']}건 기준. `python evaluation/run_eval.py --round {round_no}` 실행 결과.")
    lines.append("")
    lines.append("## 요약")
    lines.append("")
    lines.append(f"- 통과: {result['passed']} / {result['total']}")
    lines.append("- 카테고리별 통과율")
    lines.extend(_category_lines(result))
    lines.append("")

    if result["failures"]:
        lines.append("## 실패 케이스")
        lines.append("")
        lines.append("| id | category | status | detail |")
        lines.append("|---|---|---|---|")
        for f in result["failures"]:
            detail = str(f["detail"]).replace("\n", " ").replace("|", "\\|")[:200]
            lines.append(f"| {f['id']} | {f['type']} | {f['status']} | {detail} |")
        lines.append("")

    if compare is not None:
        lines.append("## 1차 대비 비교 (compare_eval)")
        lines.append("")
        lines.append(f"- 개선폭(delta): {compare['delta']:+d}")
        lines.append(f"- 회귀 없음(safe): {compare['safe']}")
        lines.append(f"- 새로 통과한 문항: {compare['fixed'] or '없음'}")
        lines.append(f"- 새로 실패한 문항(회귀): {compare['regressed'] or '없음'}")
        lines.append("")

    lines.append("## RAGAS")
    lines.append("")
    if ragas_result is None:
        lines.append(
            "> 계산 안 함. `--ragas` 옵션 없이 실행됨, 또는 `retrieve_docs`를 쓰는 문항이 없음."
        )
    else:
        summary = ragas_result["summary"]
        lines.append(
            "> `ragas` 패키지 대신 `evaluation/ragas_lite.py`(우리 Bedrock LLM 기반 LLM-as-Judge)로 "
            "계산했다 — `ragas`는 langchain-community 0.4+ 와 호환되지 않아(자세한 이유는 "
            "ragas_lite.py 상단 주석) 이 스택에 설치할 수 없다."
        )
        lines.append("")
        lines.append(f"- 대상 문항 수: {summary['n']} (retrieve_docs를 쓰는 문항만)")
        lines.append(f"- faithfulness: {summary['faithfulness']}")
        lines.append(f"- answer_relevancy: {summary['answer_relevancy']}")
        lines.append(f"- context_precision: {summary['context_precision']}")
        lines.append("- context_recall: 계산 불가 (ground_truth 없음)")
    lines.append("")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="test_queries.csv 자동 평가")
    parser.add_argument("--round", type=int, choices=[1, 2], required=True)
    parser.add_argument("--llm-judge", action="store_true", help="결정적 판정 대신 LLM-as-Judge 사용")
    parser.add_argument("--ragas", action="store_true", help="RAGAS 대체 지표(ragas_lite.py)도 계산")
    args = parser.parse_args()

    eval_dir = BASE_DIR / "evaluation"
    eval_set = load_eval_set(eval_dir / "test_queries.csv")
    print(f"평가셋 {len(eval_set)}건 로드 완료", flush=True)

    from langgraph.checkpoint.memory import MemorySaver

    from agent import build_supervisor

    from answer_chain import build_answer_chain

    print("그래프 준비 중 (MCP 서버 3개 기동 + RAG 문서 임베딩 — 수십 초 걸릴 수 있음)...", flush=True)
    build_start = time.monotonic()
    # checkpointer 없이 compile하면 interrupt()는 멈추지만 Command(resume=...)가
    # "Cannot use Command(resume=...) without checkpointer"로 죽는다 (직접 확인).
    # #19처럼 pending_approval 도달 여부만 보는 결정적 판정은 문제없지만, 실제로
    # 승인까지 재개해보는 스크립트를 짜려면 이게 있어야 한다. 평가 스크립트는
    # 한 번 실행하고 끝나는 프로세스라 디스크에 영구 저장할 필요는 없어서
    # MemorySaver로 충분하다 (서버처럼 재시작을 견뎌야 하는 건 app.py의
    # AsyncSqliteSaver 참고).
    graph = build_supervisor(checkpointer=MemorySaver())
    answer_chain = build_answer_chain()
    print(f"그래프 준비 완료 ({time.monotonic() - build_start:.1f}초)\n", flush=True)

    if args.llm_judge:
        from llm_utils import build_llm_with_failover

        # 채점 LLM은 .bind_tools()를 쓰지 않고 .invoke()만 하므로(agent.py와 달리)
        # 여기서 바로 재시도+9개 모델 페일오버(MODEL_FAILOVER.md)를 씌워도 안전하다
        # — 20문항을 순차 채점하는 동안 ThrottlingException을 한 번이라도 만나면
        # 전체 라운드가 죽는 걸 막는다.
        judge = make_llm_judge(build_llm_with_failover())
    else:
        judge = deterministic_judge

    answer_fn = make_answer_fn(graph, answer_chain=answer_chain, total=len(eval_set))
    eval_start = time.monotonic()
    result = run_eval(answer_fn, eval_set, judge=judge)
    print(f"\n{len(eval_set)}건 평가 완료 (총 {time.monotonic() - eval_start:.1f}초)", flush=True)

    (eval_dir / f"round{args.round}_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    compare = None
    if args.round == 2:
        prev_path = eval_dir / "round1_result.json"
        if prev_path.exists():
            before = json.loads(prev_path.read_text(encoding="utf-8"))
            compare = compare_eval(before, result)

    ragas_result = None
    if args.ragas:
        from llm_utils import build_llm_with_failover  # 별도 인스턴스 — 채점자 llm과 분리

        ragas_result = run_ragas_lite(eval_set, answer_fn, llm=build_llm_with_failover())
        if ragas_result is not None:
            (eval_dir / f"round{args.round}_ragas.json").write_text(
                json.dumps(ragas_result, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    write_report(eval_dir / f"round{args.round}_report.md", args.round, result, compare, ragas_result)
    print(f"통과 {result['passed']}/{result['total']} -> evaluation/round{args.round}_report.md 작성 완료")


if __name__ == "__main__":
    main()
