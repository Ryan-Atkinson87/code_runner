from __future__ import annotations

import sqlite3
from enum import StrEnum


class WaveStep(StrEnum):
    """Wave-loop steps from Spec §4.2 (a–h)."""

    DEPENDENCY_CHECK = "dependency_check"
    BRANCH_CREATED = "branch_created"
    IMPLEMENTING = "implementing"
    TEST_GATE = "test_gate"
    CONTRACT_VERIFY = "contract_verify"
    INTERNAL_PR = "internal_pr"
    REVIEW = "review"
    MERGED = "merged"
    SYNCED = "synced"


# Steps where dying mid-step means the work is deterministic/idempotent
# and can be safely resumed by re-running the step (Spec §18.2).
_RESUMABLE_STEPS: frozenset[WaveStep] = frozenset(
    {
        WaveStep.DEPENDENCY_CHECK,
        WaveStep.BRANCH_CREATED,
        WaveStep.TEST_GATE,
        WaveStep.CONTRACT_VERIFY,
        WaveStep.INTERNAL_PR,
        WaveStep.REVIEW,
        WaveStep.MERGED,
        WaveStep.SYNCED,
    }
)

# Steps where dying mid-step means partial/untrusted state exists
# and the issue must be discarded and restarted (Spec §18.4).
_RESET_STEPS: frozenset[WaveStep] = frozenset(
    {
        WaveStep.IMPLEMENTING,
    }
)


class RecoveryAction(StrEnum):
    RESUME = "resume"
    RESET = "reset"
    SKIP = "skip"


def recovery_action_for(step: WaveStep) -> RecoveryAction:
    """Determine recovery action based on the last completed step."""
    if step in _RESET_STEPS:
        return RecoveryAction.RESET
    if step in _RESUMABLE_STEPS:
        return RecoveryAction.RESUME
    return RecoveryAction.RESET


class IssueMarker:
    """Read/write per-issue state markers in SQLite (Spec §18.3).

    Markers are hints only — if they disagree with git/GitHub, git wins.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def write(
        self,
        run_id: int,
        issue_number: int,
        step: WaveStep,
        *,
        checkpoint_count: int | None = None,
    ) -> None:
        if checkpoint_count is not None:
            self._conn.execute(
                """INSERT INTO issue_markers
                       (run_id, issue_number, last_step, checkpoint_count,
                        updated_at)
                   VALUES (?, ?, ?, ?, datetime('now'))
                   ON CONFLICT (run_id, issue_number)
                   DO UPDATE SET last_step = excluded.last_step,
                                checkpoint_count = excluded.checkpoint_count,
                                updated_at = datetime('now')
                """,
                (run_id, issue_number, step.value, checkpoint_count),
            )
        else:
            self._conn.execute(
                """INSERT INTO issue_markers
                       (run_id, issue_number, last_step, updated_at)
                   VALUES (?, ?, ?, datetime('now'))
                   ON CONFLICT (run_id, issue_number)
                   DO UPDATE SET last_step = excluded.last_step,
                                updated_at = datetime('now')
                """,
                (run_id, issue_number, step.value),
            )
        self._conn.commit()

    def read(
        self,
        run_id: int,
        issue_number: int,
    ) -> tuple[WaveStep, int] | None:
        """Return (last_step, checkpoint_count) or None if no marker."""
        row = self._conn.execute(
            """SELECT last_step, checkpoint_count
               FROM issue_markers
               WHERE run_id = ? AND issue_number = ?""",
            (run_id, issue_number),
        ).fetchone()
        if row is None:
            return None
        return WaveStep(row[0]), int(row[1])

    def read_all(self, run_id: int) -> dict[int, tuple[WaveStep, int]]:
        """Return all markers for a run, keyed by issue number."""
        rows = self._conn.execute(
            """SELECT issue_number, last_step, checkpoint_count
               FROM issue_markers
               WHERE run_id = ?""",
            (run_id,),
        ).fetchall()
        return {int(r[0]): (WaveStep(r[1]), int(r[2])) for r in rows}

    def clear(self, run_id: int, issue_number: int) -> None:
        self._conn.execute(
            "DELETE FROM issue_markers WHERE run_id = ? AND issue_number = ?",
            (run_id, issue_number),
        )
        self._conn.commit()

    def increment_checkpoint(self, run_id: int, issue_number: int) -> int:
        """Increment and return the new checkpoint count."""
        self._conn.execute(
            """UPDATE issue_markers
               SET checkpoint_count = checkpoint_count + 1,
                   updated_at = datetime('now')
               WHERE run_id = ? AND issue_number = ?""",
            (run_id, issue_number),
        )
        self._conn.commit()
        result = self.read(run_id, issue_number)
        return result[1] if result else 0
