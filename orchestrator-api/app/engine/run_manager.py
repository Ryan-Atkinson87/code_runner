from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.github.client import GitHubClient

logger = logging.getLogger(__name__)


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"


class RunControlError(Exception):
    pass


class RunNotFoundError(RunControlError):
    pass


@dataclass
class RunState:
    run_id: int
    project: str
    wave: str
    provider: str
    status: RunStatus


class RunController:
    """Lightweight controller for run lifecycle (Spec §12 run control).

    Coordinates start/stop/pause/resume by delegating to existing engine
    levers: the wave-loop driver and the pause/resume mechanism. The
    controller itself is deterministic (Principle 1).
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        github_client: GitHubClient | None = None,
        project_name: str = "",
        repo_name: str = "",
    ) -> None:
        self._conn = conn
        self._github_client = github_client
        self._project_name = project_name
        self._repo_name = repo_name
        self._active_task: asyncio.Task[None] | None = None
        self._active_run_id: int | None = None

    @property
    def project_name(self) -> str:
        return self._project_name

    def start_run(
        self,
        project: str,
        wave: str,
        provider: str,
    ) -> RunState:
        if self._active_run_id is not None:
            current = self.get_status(self._active_run_id)
            if current is not None and current.status in (RunStatus.RUNNING, RunStatus.PAUSED):
                raise RunControlError(
                    f"Run {self._active_run_id} is already {current.status}; stop it first"
                )

        cursor = self._conn.execute(
            """INSERT INTO runs (project, milestone, status, provider, started_at)
               VALUES (?, ?, ?, ?, datetime('now'))""",
            (project, wave, RunStatus.RUNNING, provider),
        )
        self._conn.commit()
        run_id = cursor.lastrowid
        assert run_id is not None
        self._active_run_id = run_id

        logger.info(
            "Run %d started: project=%s wave=%s provider=%s",
            run_id, project, wave, provider,
        )

        return RunState(
            run_id=run_id,
            project=project,
            wave=wave,
            provider=provider,
            status=RunStatus.RUNNING,
        )

    def stop_run(self, run_id: int) -> RunState:
        state = self._require_run(run_id)

        if state.status not in (RunStatus.RUNNING, RunStatus.PAUSED):
            raise RunControlError(f"Cannot stop run {run_id}: status is {state.status}")

        if self._active_task is not None and not self._active_task.done():
            self._active_task.cancel()
            self._active_task = None

        self._update_status(run_id, RunStatus.STOPPED)
        self._active_run_id = None

        logger.info("Run %d stopped", run_id)
        return self._require_run(run_id)

    def pause_run(self, run_id: int) -> RunState:
        state = self._require_run(run_id)

        if state.status != RunStatus.RUNNING:
            raise RunControlError(f"Cannot pause run {run_id}: status is {state.status}")

        self._update_status(run_id, RunStatus.PAUSED)

        logger.info("Run %d paused", run_id)
        return self._require_run(run_id)

    def resume_run(self, run_id: int) -> RunState:
        state = self._require_run(run_id)

        if state.status != RunStatus.PAUSED:
            raise RunControlError(f"Cannot resume run {run_id}: status is {state.status}")

        self._update_status(run_id, RunStatus.RUNNING)

        logger.info("Run %d resumed", run_id)
        return self._require_run(run_id)

    def complete_run(self, run_id: int) -> None:
        self._update_status(run_id, RunStatus.COMPLETED)
        if self._active_run_id == run_id:
            self._active_run_id = None
        logger.info("Run %d completed", run_id)

    def fail_run(self, run_id: int) -> None:
        self._update_status(run_id, RunStatus.FAILED)
        if self._active_run_id == run_id:
            self._active_run_id = None
        logger.info("Run %d failed", run_id)

    def get_status(self, run_id: int) -> RunState | None:
        row = self._conn.execute(
            "SELECT id, project, milestone, status, provider FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return RunState(
            run_id=row[0],
            project=row[1],
            wave=row[2],
            provider=row[4],
            status=RunStatus(row[3]),
        )

    def get_active_run(self) -> RunState | None:
        if self._active_run_id is None:
            return None
        return self.get_status(self._active_run_id)

    def set_active_task(self, task: asyncio.Task[None]) -> None:
        self._active_task = task

    def list_waves(self) -> list[dict[str, Any]]:
        if self._github_client is None or not self._repo_name:
            return []
        milestones = self._github_client.list_milestones(self._repo_name, state="all")
        return [
            {
                "name": m.title,
                "milestone_number": m.number,
                "state": m.state,
            }
            for m in milestones
        ]

    def _require_run(self, run_id: int) -> RunState:
        state = self.get_status(run_id)
        if state is None:
            raise RunNotFoundError(f"Run {run_id} not found")
        return state

    def _update_status(self, run_id: int, status: RunStatus) -> None:
        finished = status in (RunStatus.STOPPED, RunStatus.COMPLETED, RunStatus.FAILED)
        if finished:
            self._conn.execute(
                "UPDATE runs SET status = ?, finished_at = datetime('now') WHERE id = ?",
                (status, run_id),
            )
        else:
            self._conn.execute(
                "UPDATE runs SET status = ? WHERE id = ?",
                (status, run_id),
            )
        self._conn.commit()
