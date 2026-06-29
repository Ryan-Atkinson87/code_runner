from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from app.config.schema import RepoCommands
from app.engine.markers import IssueMarker, WaveStep
from app.gates.runner import GateRunResult, run_gates
from app.git.repo import GitRepo
from app.observability.capture import CaptureError, EventCaptureWriter
from app.observability.langfuse_emitter import LangfuseEmitter
from app.observability.models import SessionCapture
from app.providers.adapter import ProviderAdapter
from app.providers.types import SessionResult, SessionRole, UsageReport
from app.renderer.base import RenderedOutput

logger = logging.getLogger(__name__)


class ImplementOutcome(StrEnum):
    GATES_PASSED = "gates_passed"
    PARKED_FIX_BOUND = "parked_fix_bound"
    PARKED_STUCK = "parked_stuck"
    ERROR = "error"


@dataclass
class BlockerRecord:
    issue_number: int
    reason: str
    last_gate_result: GateRunResult | None = None


@dataclass
class ImplementResult:
    outcome: ImplementOutcome
    gate_result: GateRunResult | None = None
    sessions: list[SessionResult] = field(default_factory=list)
    blocker: BlockerRecord | None = None


_CHECKPOINT_TIMEOUT_SECONDS = 1800.0
_MAX_CHECKPOINTS = 3


async def implement_and_gate(
    issue_number: int,
    issue_body: str,
    repo: GitRepo,
    repo_name: str,
    repo_path: Path,
    adapter: ProviderAdapter,
    gate_commands: RepoCommands,
    rendered_output: RenderedOutput,
    marker_store: IssueMarker,
    run_id: int,
    model: str,
    allowed_tools: list[str],
    wave_name: str = "",
    capture_writer: EventCaptureWriter | None = None,
    langfuse_emitter: LangfuseEmitter | None = None,
    test_fix_attempts: int = 3,
    checkpoint_timeout: float = _CHECKPOINT_TIMEOUT_SECONDS,
    max_checkpoints: int = _MAX_CHECKPOINTS,
) -> ImplementResult:
    """Run the implement -> gate -> fix inner loop for a single issue.

    Returns when gates pass, a blocker is recorded, or an error occurs.
    State markers are updated at each step boundary for crash recovery.
    """
    rendered_output.write_to(repo_path)

    marker = marker_store.read(run_id, issue_number)
    checkpoint_count = marker[1] if marker else 0

    sessions: list[SessionResult] = []
    fix_attempts_remaining = test_fix_attempts
    last_gate_result: GateRunResult | None = None
    is_continuation = checkpoint_count > 0

    marker_store.write(
        run_id,
        issue_number,
        WaveStep.IMPLEMENTING,
        checkpoint_count=checkpoint_count,
    )

    while True:
        if last_gate_result is not None and not last_gate_result.all_passed:
            prompt = _build_fix_prompt(issue_body, last_gate_result)
            skill = "implement_fix"
        else:
            prompt = _build_implement_prompt(issue_body, is_continuation)
            skill = "implement"

        started_at = datetime.now(UTC)
        session = await adapter.run_session(
            workdir=repo_path,
            role=SessionRole.IMPLEMENTOR,
            model=model,
            allowed_tools=allowed_tools,
            prompt=prompt,
            context_files=[],
        )
        finished_at = datetime.now(UTC)
        sessions.append(session)

        _record_session(
            session=session,
            session_id=uuid.uuid4().hex,
            run_id=run_id,
            wave=wave_name,
            issue_number=issue_number,
            role=SessionRole.IMPLEMENTOR,
            skill=skill,
            model=model,
            started_at=started_at,
            finished_at=finished_at,
            capture_writer=capture_writer,
            langfuse_emitter=langfuse_emitter,
        )

        if session.usage.duration_seconds >= checkpoint_timeout:
            _commit_wip(repo, issue_number)
            checkpoint_count += 1
            marker_store.write(
                run_id,
                issue_number,
                WaveStep.IMPLEMENTING,
                checkpoint_count=checkpoint_count,
            )

            if checkpoint_count >= max_checkpoints:
                return ImplementResult(
                    outcome=ImplementOutcome.PARKED_STUCK,
                    sessions=sessions,
                    blocker=BlockerRecord(
                        issue_number=issue_number,
                        reason=f"Stuck: {max_checkpoints} checkpoints without producing a PR",
                    ),
                )

            is_continuation = True
            last_gate_result = None
            continue

        marker_store.write(run_id, issue_number, WaveStep.TEST_GATE)
        last_gate_result = run_gates(
            repo_name=repo_name,
            repo_path=repo_path,
            commands=gate_commands,
        )

        if last_gate_result.all_passed:
            return ImplementResult(
                outcome=ImplementOutcome.GATES_PASSED,
                gate_result=last_gate_result,
                sessions=sessions,
            )

        fix_attempts_remaining -= 1
        if fix_attempts_remaining <= 0:
            return ImplementResult(
                outcome=ImplementOutcome.PARKED_FIX_BOUND,
                gate_result=last_gate_result,
                sessions=sessions,
                blocker=BlockerRecord(
                    issue_number=issue_number,
                    reason=f"Gate failures after {test_fix_attempts} fix attempts",
                    last_gate_result=last_gate_result,
                ),
            )

        marker_store.write(
            run_id,
            issue_number,
            WaveStep.IMPLEMENTING,
            checkpoint_count=checkpoint_count,
        )
        is_continuation = False


def _record_session(
    *,
    session: SessionResult,
    session_id: str,
    run_id: int,
    wave: str,
    issue_number: int,
    role: SessionRole,
    skill: str,
    model: str,
    started_at: datetime,
    finished_at: datetime,
    capture_writer: EventCaptureWriter | None,
    langfuse_emitter: LangfuseEmitter | None,
) -> None:
    if capture_writer is None and langfuse_emitter is None:
        return

    capture = SessionCapture(
        session_id=session_id,
        run_id=run_id,
        wave=wave,
        issue_number=issue_number,
        role=role,
        skill=skill,
        model=model,
        started_at=started_at,
        finished_at=finished_at,
        events=session.events,
        usage=session.usage if isinstance(session.usage, UsageReport) else UsageReport(),
        audit_log=session.audit_log,
        outcome=session.outcome,
        artifacts=session.artifacts,
    )

    if capture_writer is not None:
        try:
            capture_writer.write(capture)
        except CaptureError as exc:
            logger.warning("Layer 1 capture write failed for session %s: %s", session_id, exc)

    if langfuse_emitter is not None:
        langfuse_emitter.emit(capture)


def _commit_wip(repo: GitRepo, issue_number: int) -> str | None:
    if not repo.is_dirty():
        return None
    repo.stage_all()
    return repo.commit(f"WIP: checkpoint for issue #{issue_number}")


def _build_implement_prompt(issue_body: str, is_continuation: bool = False) -> str:
    if is_continuation:
        return (
            "Continue implementing the following issue. "
            "Your previous session was checkpointed. "
            "Read the current state on the branch and continue.\n\n"
            f"{issue_body}"
        )
    return f"Implement the following issue. Write code and new tests as needed.\n\n{issue_body}"


def _build_fix_prompt(issue_body: str, gate_result: GateRunResult) -> str:
    parts = ["The implementation has gate failures. Fix them.\n"]
    parts.append("## Gate failures\n")
    for result in gate_result.results:
        if result.status.value == "failed":
            parts.append(f"### {result.name} (exit code {result.exit_code})\n")
            if result.stdout:
                parts.append(f"stdout:\n```\n{result.stdout[:2000]}\n```\n")
            if result.stderr:
                parts.append(f"stderr:\n```\n{result.stderr[:2000]}\n```\n")
        elif result.status.value == "timed_out":
            parts.append(f"### {result.name} — timed out\n")
    parts.append(f"\n## Issue (for reference)\n\n{issue_body}")
    return "\n".join(parts)
