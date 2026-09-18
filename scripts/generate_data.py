"""합성 멀티클라우드 비용·사용률 데이터 생성기.

표준 라이브러리만 사용한다 (pandas/numpy 미설치 환경에서도 재현 가능하도록).

기준일 처리 (구현 전 의사결정 A):
- DATA_END_DATE 를 데이터의 마지막 날짜로 고정한다.
- 에이전트는 실행 시각의 실제 wall-clock 대신 DATA_END_DATE + 1일을 "오늘"로 취급한다.
  (test_queries.csv 의 "어제", "이번 달" 같은 상대 표현이 항상 같은 정답을 가리키게 하기 위함)

이상치 주입 (구현 전 의사결정 A):
- ANOMALIES 리스트에 (resource_id, date, multiplier, 관련 test_queries id, 설명) 을 명시한다.
- 재실행해도 SEED 고정으로 동일한 데이터가 나온다.

실행:
    python scripts/generate_data.py
출력:
    data/raw/costs.csv
    data/raw/resource_utilization.csv
    data/raw/anomalies.md   (주입한 이상치 목록 — 평가셋과의 매핑 문서)
    data/costs.db           (SQLite, costs / resources / resource_utilization 테이블)
"""

from __future__ import annotations

import csv
import random
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

SEED = 42
random.seed(SEED)

DATA_END_DATE = date(2026, 9, 14)  # "어제" 기준
TODAY = DATA_END_DATE + timedelta(days=1)  # 시스템이 "오늘"로 취급할 날짜 (2026-09-15)
DATA_DAYS = 90
DATA_START_DATE = DATA_END_DATE - timedelta(days=DATA_DAYS - 1)

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
DB_PATH = BASE_DIR / "data" / "costs.db"


@dataclass
class Resource:
    provider: str
    resource_id: str
    service: str
    team: str
    base_daily_cost: float
    idle: bool  # True 면 list_idle_resources / #3 케이스의 정답 대상


RESOURCES: list[Resource] = [
    Resource("aws", "i-1001-ec2-team-a", "EC2", "team-a", 12.0, idle=False),
    Resource("aws", "i-1002-ec2-team-b", "EC2", "team-b", 8.0, idle=False),
    Resource("aws", "vol-1003-ebs-team-a", "EBS", "team-a", 1.5, idle=True),
    Resource("aws", "bucket-1004-s3-team-c", "S3", "team-c", 3.0, idle=False),
    Resource("gcp", "gce-2001-team-b", "Compute Engine", "team-b", 10.0, idle=False),
    Resource("gcp", "gcs-2002-team-c", "Cloud Storage", "team-c", 2.0, idle=False),
    Resource("gcp", "bq-2003-team-a", "BigQuery", "team-a", 4.0, idle=False),
    Resource("azure", "vm-3001-team-c", "Virtual Machines", "team-c", 9.0, idle=False),
    Resource("azure", "disk-3002-team-a", "Managed Disks", "team-a", 1.0, idle=True),
    Resource("azure", "sql-3003-team-b", "SQL Database", "team-b", 6.0, idle=False),
]

# (resource_id, date, cost 배율, 관련 test_queries id, 설명)
ANOMALIES: list[tuple[str, date, float, str, str]] = [
    (
        "i-1001-ec2-team-a",
        DATA_END_DATE,
        6.0,
        "5",
        "어제(DATA_END_DATE) EC2 비용 급증 — 명확한 이상 케이스",
    ),
    (
        "gce-2001-team-b",
        DATA_END_DATE - timedelta(days=7),
        2.2,
        "17",
        "휴일 가정 트래픽 증가 — 이상/정상 경계에 걸치도록 배율을 낮게 설정 (edge 케이스)",
    ),
]


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def anomaly_multiplier(resource_id: str, day: date) -> float:
    for r_id, a_date, mult, _, _ in ANOMALIES:
        if r_id == resource_id and a_date == day:
            return mult
    return 1.0


def generate_costs() -> list[dict]:
    rows = []
    for resource in RESOURCES:
        for day in daterange(DATA_START_DATE, DATA_END_DATE):
            noise = random.uniform(0.9, 1.1)
            mult = anomaly_multiplier(resource.resource_id, day)
            cost = round(resource.base_daily_cost * noise * mult, 2)
            rows.append(
                {
                    "provider": resource.provider,
                    "account_id": f"{resource.provider}-account-01",
                    "service": resource.service,
                    "resource_id": resource.resource_id,
                    "tag_team": resource.team,
                    "usage_date": day.isoformat(),
                    "cost_amount": cost,
                    "currency": "USD",
                }
            )
    return rows


def generate_utilization() -> list[dict]:
    rows = []
    for resource in RESOURCES:
        for day in daterange(DATA_START_DATE, DATA_END_DATE):
            if resource.idle:
                pct = round(random.uniform(0.0, 3.0), 1)
                status = "idle"
            else:
                pct = round(random.uniform(30.0, 80.0), 1)
                status = "running"
            rows.append(
                {
                    "resource_id": resource.resource_id,
                    "usage_date": day.isoformat(),
                    "utilization_pct": pct,
                    "status": status,
                }
            )
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_anomalies_doc(path: Path) -> None:
    lines = [
        "# 주입된 이상치 목록",
        "",
        f"- SEED: {SEED}",
        f"- 데이터 기간: {DATA_START_DATE.isoformat()} ~ {DATA_END_DATE.isoformat()}",
        f"- 시스템 기준 '오늘': {TODAY.isoformat()}",
        "",
        "| resource_id | date | 배율 | 관련 test_queries id | 설명 |",
        "|---|---|---|---|---|",
    ]
    for r_id, a_date, mult, qid, desc in ANOMALIES:
        lines.append(f"| {r_id} | {a_date.isoformat()} | {mult}x | #{qid} | {desc} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_sqlite(cost_rows: list[dict], util_rows: list[dict]) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE costs (
            provider TEXT, account_id TEXT, service TEXT, resource_id TEXT,
            tag_team TEXT, usage_date TEXT, cost_amount REAL, currency TEXT
        )
        """
    )
    cur.executemany(
        """INSERT INTO costs
           (provider, account_id, service, resource_id, tag_team, usage_date, cost_amount, currency)
           VALUES (:provider, :account_id, :service, :resource_id, :tag_team, :usage_date, :cost_amount, :currency)""",
        cost_rows,
    )

    cur.execute(
        """
        CREATE TABLE resource_utilization (
            resource_id TEXT, usage_date TEXT, utilization_pct REAL, status TEXT
        )
        """
    )
    cur.executemany(
        """INSERT INTO resource_utilization
           (resource_id, usage_date, utilization_pct, status)
           VALUES (:resource_id, :usage_date, :utilization_pct, :status)""",
        util_rows,
    )

    cur.execute(
        """
        CREATE TABLE resources (
            resource_id TEXT PRIMARY KEY, provider TEXT, service TEXT, team TEXT, is_idle INTEGER
        )
        """
    )
    cur.executemany(
        """INSERT INTO resources (resource_id, provider, service, team, is_idle)
           VALUES (?, ?, ?, ?, ?)""",
        [
            (r.resource_id, r.provider, r.service, r.team, int(r.idle))
            for r in RESOURCES
        ],
    )

    # stop_resource / resize_resource / send_cost_alert 실행 이력 (tools.py가 기록)
    cur.execute(
        """
        CREATE TABLE actions_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resource_id TEXT,
            action TEXT,
            detail TEXT,
            executed_at TEXT
        )
        """
    )

    conn.commit()
    conn.close()


def main() -> None:
    cost_rows = generate_costs()
    util_rows = generate_utilization()

    write_csv(RAW_DIR / "costs.csv", cost_rows)
    write_csv(RAW_DIR / "resource_utilization.csv", util_rows)
    write_anomalies_doc(RAW_DIR / "anomalies.md")
    load_sqlite(cost_rows, util_rows)

    print(f"costs: {len(cost_rows)}행, utilization: {len(util_rows)}행 생성")
    print(f"SQLite: {DB_PATH}")
    print(f"기준 '오늘': {TODAY.isoformat()}")


if __name__ == "__main__":
    main()
