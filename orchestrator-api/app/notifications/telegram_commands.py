from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from enum import StrEnum

from app.blockers.store import BlockerStore, BlockerStoreError
from app.usage.pause import UsagePauseManager
from app.usage.policy import UsagePolicy

logger = logging.getLogger(__name__)


class CommandKind(StrEnum):
    STATUS = "status"
    PAUSE = "pause"
    RESUME = "resume"
    OVERRIDE_USAGE = "override usage"
    BLOCKER_RESPONSE = "blocker_response"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CommandResult:
    command: CommandKind
    reply: str
    success: bool


class CommandRouter:
    def __init__(
        self,
        conn: sqlite3.Connection,
        pause_manager: UsagePauseManager,
        usage_policy: UsagePolicy,
        blocker_store: BlockerStore,
    ) -> None:
        self._conn = conn
        self._pause = pause_manager
        self._policy = usage_policy
        self._blockers = blocker_store

    def handle(self, text: str, run_id: int | None) -> CommandResult:
        normalized = text.strip().lower()

        if normalized == "status":
            return self._handle_status(run_id)
        if normalized == "pause":
            return self._handle_pause(run_id)
        if normalized == "resume":
            return self._handle_resume(run_id)
        if normalized == "override usage":
            return self._handle_override(run_id)
        if normalized.startswith("resolve #"):
            return self._handle_blocker_response(text, run_id)

        return CommandResult(
            command=CommandKind.UNKNOWN,
            reply=(
                "Unknown command. Available commands:\n"
                "- status\n"
                "- pause\n"
                "- resume\n"
                "- override usage\n"
                "- resolve #<issue> <response>"
            ),
            success=True,
        )

    def _handle_status(self, run_id: int | None) -> CommandResult:
        if run_id is None:
            return CommandResult(
                command=CommandKind.STATUS,
                reply="No active run.",
                success=True,
            )
        row = self._conn.execute(
            "SELECT project, milestone, status FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return CommandResult(
                command=CommandKind.STATUS,
                reply=f"Run {run_id} not found.",
                success=False,
            )

        paused = self._pause.is_paused(run_id)
        override = self._policy.override_active
        blockers = self._blockers.list_parked(run_id)

        lines = [
            f"Run #{run_id}: {row['status']}",
            f"Project: {row['project']}",
            f"Milestone: {row['milestone']}",
            f"Paused: {'yes' if paused else 'no'}",
            f"Override: {'active' if override else 'off'}",
            f"Parked blockers: {len(blockers)}",
        ]
        if blockers:
            for b in blockers:
                lines.append(f"  - #{b.issue_number}: {b.reason}")

        return CommandResult(
            command=CommandKind.STATUS,
            reply="\n".join(lines),
            success=True,
        )

    def _handle_pause(self, run_id: int | None) -> CommandResult:
        if run_id is None:
            return CommandResult(
                command=CommandKind.PAUSE,
                reply="No active run to pause.",
                success=False,
            )
        if self._pause.is_paused(run_id):
            return CommandResult(
                command=CommandKind.PAUSE,
                reply=f"Run #{run_id} is already paused.",
                success=True,
            )
        from app.usage.models import Meter

        self._pause.set_paused(
            run_id,
            Meter(kind="manual", utilisation=0.0, resets_at=None),
        )
        return CommandResult(
            command=CommandKind.PAUSE,
            reply=f"Run #{run_id} paused.",
            success=True,
        )

    def _handle_resume(self, run_id: int | None) -> CommandResult:
        if run_id is None:
            return CommandResult(
                command=CommandKind.RESUME,
                reply="No active run to resume.",
                success=False,
            )
        if not self._pause.is_paused(run_id):
            return CommandResult(
                command=CommandKind.RESUME,
                reply=f"Run #{run_id} is not paused.",
                success=True,
            )
        self._pause.set_resumed(run_id)
        return CommandResult(
            command=CommandKind.RESUME,
            reply=f"Run #{run_id} resumed.",
            success=True,
        )

    def _handle_override(self, run_id: int | None) -> CommandResult:
        new_state = not self._policy.override_active
        self._policy.set_override(new_state)
        label = "activated" if new_state else "deactivated"
        context = f" for run #{run_id}" if run_id else ""
        return CommandResult(
            command=CommandKind.OVERRIDE_USAGE,
            reply=f"Usage override {label}{context}.",
            success=True,
        )

    def _handle_blocker_response(
        self, text: str, run_id: int | None
    ) -> CommandResult:
        if run_id is None:
            return CommandResult(
                command=CommandKind.BLOCKER_RESPONSE,
                reply="No active run.",
                success=False,
            )
        parts = text.strip().split(maxsplit=2)
        if len(parts) < 3:
            return CommandResult(
                command=CommandKind.BLOCKER_RESPONSE,
                reply="Usage: resolve #<issue> <response>",
                success=False,
            )
        try:
            issue_number = int(parts[1].lstrip("#"))
        except ValueError:
            return CommandResult(
                command=CommandKind.BLOCKER_RESPONSE,
                reply=f"Invalid issue number: {parts[1]}",
                success=False,
            )
        response_text = parts[2]

        try:
            self._blockers.resolve(
                run_id, issue_number, resolution_response=response_text
            )
        except BlockerStoreError:
            return CommandResult(
                command=CommandKind.BLOCKER_RESPONSE,
                reply=f"No parked blocker for issue #{issue_number} in run #{run_id}.",
                success=False,
            )

        return CommandResult(
            command=CommandKind.BLOCKER_RESPONSE,
            reply=(
                f"Blocker for #{issue_number} resolved.\n"
                f"Response recorded: {response_text}"
            ),
            success=True,
        )
