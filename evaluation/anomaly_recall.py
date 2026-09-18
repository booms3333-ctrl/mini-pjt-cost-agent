"""이상탐지 recall 측정 — SERVICE.md 5절 성공 기준("이상탐지 recall >= 0.9") 검증 (패턴 12).

scripts/generate_data.py의 ANOMALIES 리스트가 실제로 주입한 이상치 정답이다
(data/raw/anomalies.md는 이 리스트를 사람이 읽기 좋게 렌더링해 놓은 것뿐, 정답
자체는 코드에 있다). 지금까지 이 정답과 detect_cost_anomaly()의 실제 탐지
결과를 비교하는 코드가 없어서, SERVICE.md가 스스로 정한 recall 기준을 검증할
방법 자체가 없었다 — 이 스크립트가 그 공백을 메운다.

LLM을 호출하지 않는 결정적 계산이다 — detect_cost_anomaly는 z-score 기반 규칙
이라 같은 인자엔 항상 같은 결과를 낸다(tools.py의 "같은 입력엔 항상 같은 출력"
원칙과 동일).

실행:
    python evaluation/anomaly_recall.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))
sys.path.insert(0, str(BASE_DIR))

import tools  # noqa: E402
from scripts.generate_data import ANOMALIES  # noqa: E402

_DETECTED_ROW = re.compile(r"^-\s*([\w-]+)\s*\([^)]*?(\d{4}-\d{2}-\d{2})\)")
# 괄호 안이 "(YYYY-MM-DD)" 하나였다가 tools.detect_cost_anomaly()가 계정 정보
# ("계정: aws-account-01, YYYY-MM-DD")까지 추가하면서 날짜 앞에 다른 텍스트가
# 낄 수 있게 됐다 — 날짜만 비탐욕적으로 찾도록 완화했다.

RECALL_TARGET = 0.9  # SERVICE.md 5절


def ground_truth_pairs() -> set[tuple[str, str]]:
    """scripts/generate_data.py가 실제로 주입한 (resource_id, date) 정답 집합."""
    return {(resource_id, day.isoformat()) for resource_id, day, *_ in ANOMALIES}


def detected_pairs(**kwargs) -> set[tuple[str, str]]:
    """detect_cost_anomaly()를 실제로 호출해 (resource_id, date) 탐지 결과 집합을 만든다.

    kwargs 없이 부르면 도구의 기본값(lookback_days=14, window_days=7,
    z_threshold=2.0)을 그대로 쓴다 — anomaly_agent가 provider 필터 없이 부르는
    가장 흔한 호출과 같은 조건이다.
    """
    output = tools.detect_cost_anomaly.invoke(kwargs)
    pairs = set()
    for line in output.splitlines():
        m = _DETECTED_ROW.match(line.strip())
        if m:
            pairs.add((m.group(1), m.group(2)))
    return pairs


def compute_recall(ground_truth: set[tuple[str, str]], detected: set[tuple[str, str]]) -> dict:
    """recall = 정답 중 실제로 탐지된 비율."""
    matched = ground_truth & detected
    missed = ground_truth - detected
    recall = len(matched) / len(ground_truth) if ground_truth else float("nan")
    return {
        "recall": recall,
        "ground_truth_count": len(ground_truth),
        "matched": sorted(matched),
        "missed": sorted(missed),
    }


def main() -> None:
    ground_truth = ground_truth_pairs()
    detected = detected_pairs()
    result = compute_recall(ground_truth, detected)

    verdict = "충족" if result["recall"] >= RECALL_TARGET else "미충족"
    print(f"이상탐지 recall: {result['recall']:.2f} ({len(result['matched'])}/{result['ground_truth_count']})")
    print(f"목표(SERVICE.md 5절, recall >= {RECALL_TARGET}): {verdict}")

    if result["missed"]:
        print("놓친 케이스:")
        for resource_id, day in result["missed"]:
            print(f"  - {resource_id} ({day})")
    else:
        print("놓친 케이스 없음.")


if __name__ == "__main__":
    main()
