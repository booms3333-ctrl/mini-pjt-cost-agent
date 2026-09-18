# 2차 자체 평가 결과 (Day 10)

`test_queries.csv` 20건 기준. `python evaluation/run_eval.py --round 2` 실행 결과.

## 요약

- 통과: 20 / 20
- 카테고리별 통과율
  - positive: 10 / 10
  - negative: 3 / 3
  - edge: 3 / 3
  - guardrail: 4 / 4

## 1차 대비 비교 (compare_eval)

- 개선폭(delta): +0
- 회귀 없음(safe): True
- 새로 통과한 문항: 없음
- 새로 실패한 문항(회귀): 없음

## RAGAS

> 계산 안 함. `--ragas` 옵션 없이 실행됨, 또는 `retrieve_docs`를 쓰는 문항이 없음.

