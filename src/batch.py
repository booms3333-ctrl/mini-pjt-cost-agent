"""이상 비용 탐지 배치 — app.py가 떠 있는 동안 주기적으로 detect_cost_anomaly를
돌려 결과를 data/batch_log.db에 남기고, 이상이 발견되면 이메일로 알린다.

OS 스케줄러(Windows 작업 스케줄러 등) 대신 asyncio 백그라운드 태스크로 구현한 이유:
이 프로젝트는 app.py가 FastAPI로 이미 상시 실행되는 프로세스라, 별도 프로세스나
외부 스케줄러 없이 그 안에서 주기적으로 깨어나는 루프 하나만 있으면 충분하다.
서버가 상시 떠 있지 않은 배포(서버리스 등)로 바뀌면 이 방식은 안 맞고 외부
스케줄러가 다시 필요해진다 — SERVICE.md/README.md에 이 전제를 명시해뒀다.

batch_log.db를 costs.db와 분리한 이유는 qa_history.py의 history.db와 같다:
costs.db는 scripts/generate_data.py가 실행될 때마다 통째로 지우고 새로 만드는
합성 데이터셋이라, 배치 실행 이력을 거기 같이 두면 데이터를 리셋할 때마다
이력까지 같이 날아간다.

이메일 발송은 선택 사항이다 — SMTP_* 환경변수(.env)가 전부 채워져 있을 때만
실제로 보내고, 비어 있으면 탐지·기록까지만 하고 발송은 건너뛴다(로그만 남김).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import smtplib
import sqlite3
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

import tools

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "batch_log.db"
PROVIDERS = ("aws", "gcp", "azure")

# 데모/평가 환경에서 너무 자주 돌면 로그가 지저분해지고, 너무 뜸하면 검증하기
# 어려우니 기본값은 24시간이되 .env로 조절 가능하게 뒀다.
DEFAULT_INTERVAL_SECONDS = 24 * 60 * 60


def _interval_seconds() -> int:
    return int(os.getenv("ANOMALY_BATCH_INTERVAL_SECONDS", str(DEFAULT_INTERVAL_SECONDS)))


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS anomaly_batch_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT,
            finished_at TEXT,
            provider TEXT,
            findings_count INTEGER,
            detail TEXT,
            notified INTEGER
        )
        """
    )
    return conn


def _send_email(subject: str, body: str) -> bool:
    """SMTP_HOST/PORT/USERNAME/PASSWORD/NOTIFY_EMAIL_TO가 전부 있을 때만 발송한다.

    하나라도 비어 있으면 배치 자체는 계속 동작해야 하므로(탐지+기록은 이메일
    설정과 무관하게 항상 되어야 함) 조용히 건너뛰고 False를 돌려준다.
    """
    host = os.getenv("SMTP_HOST")
    port = os.getenv("SMTP_PORT")
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    to_addr = os.getenv("NOTIFY_EMAIL_TO")
    if not all([host, port, username, password, to_addr]):
        logger.info("[anomaly-batch] SMTP 환경변수 미설정 — 이메일 발송 건너뜀 (로그만 기록)")
        return False

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = username
    msg["To"] = to_addr

    with smtplib.SMTP(host, int(port)) as server:
        server.starttls()
        server.login(username, password)
        server.sendmail(username, [to_addr], msg.as_string())
    return True


def run_anomaly_batch_once() -> list[dict]:
    """provider별로 detect_cost_anomaly를 한 번씩 돌리고 결과를 기록한다.

    provider 하나가 예외를 던져도 나머지 provider는 계속 검사한다 — 배치 전체가
    한 provider의 일시적 오류 때문에 멈추면 안 되기 때문이다.
    """
    results = []
    for provider in PROVIDERS:
        started = datetime.now(timezone.utc)
        try:
            output = tools.detect_cost_anomaly.invoke({"provider": provider})
        except Exception as exc:
            output = f"오류: {exc}"
        finished = datetime.now(timezone.utc)

        m = re.search(r"이상 급증 탐지 (\d+)건", output)
        findings_count = int(m.group(1)) if m else 0

        notified = False
        if findings_count > 0:
            logger.warning("[anomaly-batch] %s: %s", provider, output)
            notified = _send_email(
                subject=f"[비용 이상탐지] {provider.upper()} {findings_count}건 발견",
                body=output,
            )

        conn = _connect()
        conn.execute(
            "INSERT INTO anomaly_batch_runs "
            "(started_at, finished_at, provider, findings_count, detail, notified) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (started.isoformat(), finished.isoformat(), provider, findings_count, output, int(notified)),
        )
        conn.commit()
        conn.close()

        results.append({"provider": provider, "findings_count": findings_count, "notified": notified})
    return results


def list_batch_runs(limit: int = 50) -> list[dict]:
    """최근 배치 실행 이력을 최신순으로 돌려준다."""
    conn = _connect()
    rows = conn.execute(
        "SELECT id, started_at, finished_at, provider, findings_count, detail, notified "
        "FROM anomaly_batch_runs ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    cols = ["id", "started_at", "finished_at", "provider", "findings_count", "detail", "notified"]
    return [dict(zip(cols, row)) for row in rows]


async def scheduler_loop() -> None:
    """app.py의 lifespan에서 asyncio.create_task로 띄우는 무한 루프.

    서버 기동 직후 한 번 실행하고, 이후 _interval_seconds() 간격으로 반복한다.
    detect_cost_anomaly가 동기 함수(sqlite3 블로킹 호출 포함)라 asyncio.to_thread로
    돌려 이벤트 루프를 막지 않는다 — agent.py 서브그래프가 동기 invoke()를 async
    이벤트 루프에서 직접 부르다 블로킹된 버그(README 트라이앤에러 회고 #6)와
    같은 실수를 여기서도 피하기 위함이다.
    """
    while True:
        try:
            await asyncio.to_thread(run_anomaly_batch_once)
        except Exception:
            logger.exception("[anomaly-batch] 배치 실행 중 오류")
        await asyncio.sleep(_interval_seconds())


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    logging.basicConfig(level=logging.INFO)
    print(run_anomaly_batch_once())
