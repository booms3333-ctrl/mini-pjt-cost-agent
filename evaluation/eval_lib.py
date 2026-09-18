"""평가 유틸 — Day 7(day07/practice/starter/submission.py)의 TraceCollector /
run_eval / compare_eval을 그대로 가져왔다. 이름·구조는 그대로지만, `run_eval`의
`answer_fn` 시그니처는 `Callable[[str], Any]`에서 `Callable[[dict], Any]`로
넓혔다(문항 하나 전체를 넘김) — authz/멀티턴 테스트 지원 이유는 `run_eval` 문서
참고.

TraceCollector 자체는 src/observability.py로 옮겼다 — 평가 스크립트뿐 아니라
실제 에이전트 실행 경로(패턴 11)도 같은 걸 쓰기 때문에, 여기서는 재노출만 한다.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from observability import TraceCollector  # noqa: E402,F401

PASS, FAIL, ERROR = "pass", "fail", "error"


def run_eval(
    answer_fn: Callable[[dict], Any],
    eval_set: list[dict],
    judge: Callable[[dict, Any], bool] | None = None,
) -> dict:
    """평가셋을 전부 돌려 유형별 통과율을 낸다.

    answer_fn이 예외를 던져도 전체 실행은 멈추지 않는다 — 그 문항만 ERROR로
    기록하고 계속 진행한다 (LLM 호출이 섞인 20문항 중 하나가 타임아웃 났다고
    나머지를 못 돌리면 평가 자체가 무용해지기 때문).

    Day 7 원본은 answer_fn이 질문 문자열 하나만 받았다(`answer_fn(item["question"])`).
    여기서 item 전체를 넘기도록 넓혔다 — authz(`requester_team`)·멀티턴(`thread_ref`)
    시나리오는 질문 문자열만으로 표현이 안 되고, run_eval.py의 answer_fn이 그
    필드들을 읽어야 하기 때문이다(그 전까지는 이 두 가드레일/버그 클래스가
    test_queries.csv로 재현 불가능했다).
    """
    passed = 0
    by_type: dict[str, dict[str, int]] = {}
    failures: list[dict] = []

    for item in eval_set:
        item_id = item.get("id")
        item_type = item.get("type", "unknown")
        bucket = by_type.setdefault(item_type, {"total": 0, "passed": 0})
        bucket["total"] += 1

        try:
            answer = answer_fn(item)
        except Exception as exc:  # noqa: BLE001
            failures.append(
                {"id": item_id, "type": item_type, "status": ERROR, "detail": f"{type(exc).__name__}: {exc}"}
            )
            continue

        ok = bool(judge(item, answer)) if judge is not None else bool(str(answer or "").strip())

        if ok:
            passed += 1
            bucket["passed"] += 1
        else:
            failures.append({"id": item_id, "type": item_type, "status": FAIL, "detail": f"판정 실패. 답: {answer!r}"})

    return {"total": len(eval_set), "passed": passed, "by_type": by_type, "failures": failures}


def compare_eval(before: dict, after: dict) -> dict:
    """개선 전후를 비교한다. 통과율 총합만 보면 무엇이 좋아지고 무엇이 깨졌는지 알 수 없다."""

    def _failed_ids(result: dict) -> set[str]:
        return {f["id"] for f in result.get("failures", []) if f.get("id") is not None}

    before_failed = _failed_ids(before)
    after_failed = _failed_ids(after)
    candidates = before_failed | after_failed
    fixed = sorted(i for i in candidates if i in before_failed and i not in after_failed)
    regressed = sorted(i for i in candidates if i not in before_failed and i in after_failed)

    return {
        "fixed": fixed,
        "regressed": regressed,
        "delta": after.get("passed", 0) - before.get("passed", 0),
        "safe": len(regressed) == 0,
    }
