import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "provenance.db"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_id TEXT NOT NULL UNIQUE,
                creator_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                attribution TEXT NOT NULL,
                confidence REAL NOT NULL,
                llm_score REAL,
                stylometric_score REAL,
                burstiness_score REAL,
                status TEXT NOT NULL,
                appeal_reasoning TEXT,
                appeal_timestamp TEXT,
                content_type TEXT DEFAULT 'text',
                label TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS verified_creators (
                creator_id TEXT PRIMARY KEY,
                verified_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def write_audit_entry(entry: dict):
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO audit_log (
                content_id, creator_id, timestamp, attribution, confidence,
                llm_score, stylometric_score, burstiness_score, status,
                appeal_reasoning, appeal_timestamp, content_type, label
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(content_id) DO UPDATE SET
                status = excluded.status,
                appeal_reasoning = excluded.appeal_reasoning,
                appeal_timestamp = excluded.appeal_timestamp
            """,
            (
                entry["content_id"],
                entry["creator_id"],
                entry["timestamp"],
                entry["attribution"],
                entry["confidence"],
                entry.get("llm_score"),
                entry.get("stylometric_score"),
                entry.get("burstiness_score"),
                entry["status"],
                entry.get("appeal_reasoning"),
                entry.get("appeal_timestamp"),
                entry.get("content_type", "text"),
                entry.get("label"),
            ),
        )
        conn.commit()


def get_submission(content_id: str) -> dict | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM audit_log WHERE content_id = ?", (content_id,)
        ).fetchone()
        return dict(row) if row else None


def update_appeal(content_id: str, appeal_reasoning: str):
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE audit_log
            SET status = 'under_review',
                appeal_reasoning = ?,
                appeal_timestamp = ?
            WHERE content_id = ?
            """,
            (
                appeal_reasoning,
                datetime.now(timezone.utc).isoformat(),
                content_id,
            ),
        )
        conn.commit()


def get_log_entries(limit: int = 50) -> list[dict]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT content_id, creator_id, timestamp, attribution, confidence,
                   llm_score, stylometric_score, burstiness_score, status,
                   appeal_reasoning, appeal_timestamp, content_type, label
            FROM audit_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def is_verified_creator(creator_id: str) -> bool:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM verified_creators WHERE creator_id = ?",
            (creator_id,),
        ).fetchone()
        return row is not None


def set_verified_creator(creator_id: str):
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO verified_creators (creator_id, verified_at)
            VALUES (?, ?)
            """,
            (creator_id, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def get_dashboard_stats() -> dict:
    init_db()
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        if total == 0:
            return {
                "total_submissions": 0,
                "likely_ai_pct": 0,
                "likely_human_pct": 0,
                "uncertain_pct": 0,
                "appeal_rate_pct": 0,
                "avg_confidence": 0,
            }

        counts = conn.execute(
            """
            SELECT attribution, COUNT(*) as count
            FROM audit_log
            GROUP BY attribution
            """
        ).fetchall()
        breakdown = {row["attribution"]: row["count"] for row in counts}
        appealed = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE appeal_reasoning IS NOT NULL"
        ).fetchone()[0]
        avg_conf = conn.execute(
            "SELECT AVG(confidence) FROM audit_log"
        ).fetchone()[0]

        return {
            "total_submissions": total,
            "likely_ai_pct": round(
                breakdown.get("likely_ai", 0) / total * 100, 1
            ),
            "likely_human_pct": round(
                breakdown.get("likely_human", 0) / total * 100, 1
            ),
            "uncertain_pct": round(breakdown.get("uncertain", 0) / total * 100, 1),
            "appeal_rate_pct": round(appealed / total * 100, 1),
            "avg_confidence": round(avg_conf or 0, 3),
        }
