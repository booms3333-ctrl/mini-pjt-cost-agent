"""질문-답변 히스토리 기록 — data/history.db에 별도로 관리한다.

costs.db와 분리한 이유: costs.db는 scripts/generate_data.py가 실행될 때마다 통째로
지우고 새로 만드는 합성 데이터셋이라, 대화 히스토리를 거기 같이 두면 데이터를
리셋할 때마다 히스토리까지 같이 날아간다. history.db는 그 생명주기와 무관하게
독립적으로 쌓인다.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "history.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS qa_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT,
            requester_team TEXT,
            question TEXT,
            answer TEXT,
            status TEXT,
            created_at TEXT
        )
        """
    )
    return conn


def record(
    thread_id: str,
    question: str,
    answer: str,
    requester_team: str | None = None,
    status: str = "answered",
) -> None:
    """질문-답변 한 쌍을 기록한다. pipeline.ask()/resume()이 끝날 때마다 호출된다.

    status: "answered" | "pending_approval" | "blocked" 중 하나. HITL 승인 대기나
    가드레일 차단도 "무슨 일이 있었는지"의 일부라 같이 남긴다.
    """
    conn = _connect()
    conn.execute(
        "INSERT INTO qa_history (thread_id, requester_team, question, answer, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (thread_id, requester_team, question, answer, status, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def list_history(thread_id: str | None = None, limit: int = 50) -> list[dict]:
    """최근 히스토리를 최신순으로 조회한다. thread_id를 주면 그 대화만 본다."""
    conn = _connect()
    query = "SELECT id, thread_id, requester_team, question, answer, status, created_at FROM qa_history"
    params: list = []
    if thread_id:
        query += " WHERE thread_id = ?"
        params.append(thread_id)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()

    cols = ["id", "thread_id", "requester_team", "question", "answer", "status", "created_at"]
    return [dict(zip(cols, row)) for row in rows]
