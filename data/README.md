# data/

사용한 문서·데이터를 담는 폴더. (SERVICE.md 3절 "데이터" 표 참고)

- `raw/` — `../scripts/generate_data.py` 실행 결과 원본
  - `costs.csv` — 일별·리소스별 합성 비용 (AWS/GCP/Azure, 90일치)
  - `resource_utilization.csv` — 일별 리소스 사용률 (유휴 리소스 판정용)
  - `anomalies.md` — 주입된 이상치 목록과 test_queries.csv 매핑
- `costs.db` — 위 raw 데이터를 정규화해 적재한 SQLite (`costs`, `resource_utilization`, `resources` 테이블). `tools.py`가 조회하는 실제 데이터 소스
- `policy_docs/` — 사내 비용 정책 문서 (RAG 인덱싱 대상: 예산 한도, 배분 기준, 태깅 규칙, 이상 대응 원칙)
- `pricing_docs/` — RI/Savings Plan 절감 조건 (RAG 인덱싱 대상)

## 재생성 방법

```bash
python scripts/generate_data.py
```

시드(42)가 고정되어 있어 재실행해도 동일한 데이터가 나온다. `costs.db`는 매 실행마다 새로 만들어진다.

## 기준일

데이터는 2026-09-14 까지이며, 에이전트는 2026-09-15를 "오늘"로 취급한다 (`scripts/generate_data.py`의 `TODAY` 상수).
`test_queries.csv`의 "어제", "이번 달" 같은 상대 표현은 이 기준일에 맞춰 설계되어 있다.
