from __future__ import annotations

import sqlite3

from app.blockers.models import Blocker, BlockerStatus, BlockerType


class BlockerStoreError(Exception):
    pass


class BlockerStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def record(self, blocker: Blocker) -> Blocker:
        existing = self._find_parked(blocker.run_id, blocker.issue_number)
        if existing is not None:
            return existing
        cursor = self._conn.execute(
            """
            INSERT INTO blockers
                (run_id, issue_number, blocker_type, reason, needed_to_unblock, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                blocker.run_id,
                blocker.issue_number,
                blocker.blocker_type.value,
                blocker.reason,
                blocker.needed_to_unblock,
                BlockerStatus.PARKED.value,
            ),
        )
        self._conn.commit()
        return self._get_by_id(cursor.lastrowid)  # type: ignore[arg-type]

    def list_parked(self, run_id: int) -> list[Blocker]:
        rows = self._conn.execute(
            "SELECT * FROM blockers WHERE run_id = ? AND status = ?",
            (run_id, BlockerStatus.PARKED.value),
        ).fetchall()
        return [self._row_to_blocker(row) for row in rows]

    def list_all(self, run_id: int) -> list[Blocker]:
        rows = self._conn.execute(
            "SELECT * FROM blockers WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        return [self._row_to_blocker(row) for row in rows]

    def resolve(
        self, run_id: int, issue_number: int, resolution_response: str | None = None
    ) -> Blocker:
        existing = self._find_parked(run_id, issue_number)
        if existing is None:
            raise BlockerStoreError(
                f"No parked blocker found for run {run_id}, issue #{issue_number}"
            )
        self._conn.execute(
            """
            UPDATE blockers
            SET status = ?, resolved_at = datetime('now'), resolution_response = ?
            WHERE id = ?
            """,
            (BlockerStatus.RESOLVED.value, resolution_response, existing.id),
        )
        self._conn.commit()
        return self._get_by_id(existing.id)  # type: ignore[arg-type]

    def _find_parked(self, run_id: int, issue_number: int) -> Blocker | None:
        row = self._conn.execute(
            "SELECT * FROM blockers WHERE run_id = ? AND issue_number = ? AND status = ?",
            (run_id, issue_number, BlockerStatus.PARKED.value),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_blocker(row)

    def _get_by_id(self, blocker_id: int) -> Blocker:
        row = self._conn.execute(
            "SELECT * FROM blockers WHERE id = ?", (blocker_id,)
        ).fetchone()
        if row is None:
            raise BlockerStoreError(f"Blocker {blocker_id} not found")
        return self._row_to_blocker(row)

    @staticmethod
    def _row_to_blocker(row: sqlite3.Row) -> Blocker:
        return Blocker(
            id=row["id"],
            run_id=row["run_id"],
            issue_number=row["issue_number"],
            blocker_type=BlockerType(row["blocker_type"]),
            reason=row["reason"],
            needed_to_unblock=row["needed_to_unblock"],
            status=BlockerStatus(row["status"]),
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
            resolution_response=row["resolution_response"],
        )
