from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.observability.capture import CaptureError, EventCaptureReader
from app.observability.models import SessionCapture
from app.providers.types import SessionOutcome


@dataclass
class RollupRow:
    wave: str
    issue_number: int
    role: str
    skill: str
    model: str
    month: str
    session_count: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    duration_seconds: float
    retry_count: int
    completed_count: int
    blocked_count: int
    error_count: int


class RollupStore:
    """Idempotent efficiency rollup aggregator backed by SQLite (Spec §11.1, §11.2, §11.3).

    Rollups survive raw-data pruning and are megabyte-scale. Each
    unique (wave, issue, role, skill, model, month) tuple has one row;
    re-aggregating the same session is a no-op, never a double-count.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def aggregate_session(self, capture: SessionCapture) -> bool:
        """Idempotently aggregate one session into rollups.

        Returns True if newly aggregated, False if already done.
        """
        existing = self._conn.execute(
            "SELECT 1 FROM aggregated_sessions WHERE session_id = ?",
            (capture.session_id,),
        ).fetchone()
        if existing:
            return False

        month = capture.started_at.strftime("%Y-%m")
        completed = 1 if capture.outcome == SessionOutcome.COMPLETED else 0
        blocked = 1 if capture.outcome == SessionOutcome.BLOCKED else 0
        error = 1 if capture.outcome == SessionOutcome.ERROR else 0

        self._conn.execute(
            """
            INSERT INTO session_rollups (
                wave, issue_number, role, skill, model, month,
                session_count, tokens_in, tokens_out, cost_usd, duration_seconds,
                retry_count, completed_count, blocked_count, error_count
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (wave, issue_number, role, skill, model, month)
            DO UPDATE SET
                session_count    = session_count    + 1,
                tokens_in        = tokens_in        + excluded.tokens_in,
                tokens_out       = tokens_out       + excluded.tokens_out,
                cost_usd         = cost_usd         + excluded.cost_usd,
                duration_seconds = duration_seconds + excluded.duration_seconds,
                retry_count      = retry_count      + excluded.retry_count,
                completed_count  = completed_count  + excluded.completed_count,
                blocked_count    = blocked_count    + excluded.blocked_count,
                error_count      = error_count      + excluded.error_count,
                updated_at       = datetime('now')
            """,
            (
                capture.wave,
                capture.issue_number,
                str(capture.role),
                str(capture.skill),
                capture.model,
                month,
                capture.usage.tokens_in,
                capture.usage.tokens_out,
                capture.usage.cost_usd,
                capture.usage.duration_seconds,
                capture.retry_count,
                completed,
                blocked,
                error,
            ),
        )
        self._conn.execute(
            "INSERT INTO aggregated_sessions (session_id) VALUES (?)",
            (capture.session_id,),
        )
        self._conn.commit()
        return True

    def aggregate_from_reader(self, reader: EventCaptureReader, month: str) -> int:
        """Idempotently aggregate all sessions from a month's Layer 1 captures.

        Skips sessions already aggregated. Returns count of newly aggregated sessions.
        Capture read errors are skipped with no side effects on the rollup state.
        """
        count = 0
        for session_id in reader.list_sessions(month):
            try:
                capture = reader.read(session_id, month)
            except CaptureError:
                continue
            if self.aggregate_session(capture):
                count += 1
        return count

    def query(
        self,
        *,
        wave: str | None = None,
        issue_number: int | None = None,
        role: str | None = None,
        skill: str | None = None,
        month: str | None = None,
    ) -> list[RollupRow]:
        """Return rollup rows matching all supplied dimension filters."""
        conditions: list[str] = []
        params: list[object] = []

        if wave is not None:
            conditions.append("wave = ?")
            params.append(wave)
        if issue_number is not None:
            conditions.append("issue_number = ?")
            params.append(issue_number)
        if role is not None:
            conditions.append("role = ?")
            params.append(role)
        if skill is not None:
            conditions.append("skill = ?")
            params.append(skill)
        if month is not None:
            conditions.append("month = ?")
            params.append(month)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""
            SELECT wave, issue_number, role, skill, model, month,
                   session_count, tokens_in, tokens_out, cost_usd, duration_seconds,
                   retry_count, completed_count, blocked_count, error_count
            FROM session_rollups
            {where}
            ORDER BY month, wave, issue_number, role, skill
        """
        rows = self._conn.execute(sql, params).fetchall()
        return [
            RollupRow(
                wave=row[0],
                issue_number=row[1],
                role=row[2],
                skill=row[3],
                model=row[4],
                month=row[5],
                session_count=row[6],
                tokens_in=row[7],
                tokens_out=row[8],
                cost_usd=row[9],
                duration_seconds=row[10],
                retry_count=row[11],
                completed_count=row[12],
                blocked_count=row[13],
                error_count=row[14],
            )
            for row in rows
        ]
