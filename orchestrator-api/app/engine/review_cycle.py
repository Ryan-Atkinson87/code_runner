from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from app.engine.implement_loop import _record_session
from app.engine.markers import IssueMarker, WaveStep
from app.git.feature_branch import FeatureBranch
from app.git.merge_queue import MergeQueue
from app.observability.capture import EventCaptureWriter
from app.observability.langfuse_emitter import LangfuseEmitter
from app.providers.adapter import ProviderAdapter
from app.providers.types import SessionResult, SessionRole
from app.renderer.base import RenderedOutput


class ReviewOutcome(StrEnum):
    APPROVED_AND_MERGED = "approved_and_merged"
    PARKED_REVIEW_BOUND = "parked_review_bound"
    ERROR = "error"


@dataclass
class ReviewResult:
    outcome: ReviewOutcome
    merge_sha: str = ""
    sessions: list[SessionResult] = field(default_factory=list)
    blocker_reason: str = ""


async def review_and_merge(
    issue_number: int,
    issue_body: str,
    feature_branch: FeatureBranch,
    repo_path: Path,
    adapter: ProviderAdapter,
    impl_rendered: RenderedOutput,
    review_rendered: RenderedOutput,
    marker_store: IssueMarker,
    merge_queue: MergeQueue,
    run_id: int,
    model: str,
    allowed_tools: list[str],
    wave_name: str = "",
    capture_writer: EventCaptureWriter | None = None,
    langfuse_emitter: LangfuseEmitter | None = None,
    review_cycles: int = 2,
) -> ReviewResult:
    """Run the bounded internal-review cycle for a single issue.

    The AI implementor fills the PR body, the AI reviewer judges the
    diff, and on request-changes the implementor addresses feedback
    up to ``review_cycles`` times before parking as a blocker.
    """
    sessions: list[SessionResult] = []

    diff = feature_branch.diff()
    diff_stat = feature_branch.diff_stat()

    marker_store.write(run_id, issue_number, WaveStep.INTERNAL_PR)

    body_started = datetime.now(UTC)
    body_session = await adapter.run_session(
        workdir=repo_path,
        role=SessionRole.IMPLEMENTOR,
        model=model,
        allowed_tools=[],
        prompt=_build_body_prompt(issue_body, diff_stat),
        context_files=[],
    )
    sessions.append(body_session)
    _record_session(
        session=body_session,
        session_id=uuid.uuid4().hex,
        run_id=run_id,
        wave=wave_name,
        issue_number=issue_number,
        role=SessionRole.IMPLEMENTOR,
        skill="body_generation",
        model=model,
        started_at=body_started,
        finished_at=datetime.now(UTC),
        capture_writer=capture_writer,
        langfuse_emitter=langfuse_emitter,
    )

    pr_body = _extract_text(body_session)

    cycles_remaining = review_cycles

    while True:
        marker_store.write(run_id, issue_number, WaveStep.REVIEW)

        review_started = datetime.now(UTC)
        review_session = await adapter.run_session(
            workdir=repo_path,
            role=SessionRole.ORCHESTRATOR,
            model=model,
            allowed_tools=[],
            prompt=_build_review_prompt(issue_body, diff, pr_body),
            context_files=[],
        )
        sessions.append(review_session)
        _record_session(
            session=review_session,
            session_id=uuid.uuid4().hex,
            run_id=run_id,
            wave=wave_name,
            issue_number=issue_number,
            role=SessionRole.ORCHESTRATOR,
            skill="review",
            model=model,
            started_at=review_started,
            finished_at=datetime.now(UTC),
            capture_writer=capture_writer,
            langfuse_emitter=langfuse_emitter,
        )

        review_text = _extract_text(review_session)

        if _is_approval(review_text):
            async with merge_queue.serialise(repo_path):
                merge_sha = feature_branch.merge_into_agent()

            marker_store.write(run_id, issue_number, WaveStep.MERGED)
            return ReviewResult(
                outcome=ReviewOutcome.APPROVED_AND_MERGED,
                merge_sha=merge_sha,
                sessions=sessions,
            )

        cycles_remaining -= 1
        if cycles_remaining <= 0:
            return ReviewResult(
                outcome=ReviewOutcome.PARKED_REVIEW_BOUND,
                sessions=sessions,
                blocker_reason=(
                    f"Review not approved after {review_cycles} cycles for issue #{issue_number}"
                ),
            )

        marker_store.write(run_id, issue_number, WaveStep.IMPLEMENTING)

        feedback_started = datetime.now(UTC)
        feedback_session = await adapter.run_session(
            workdir=repo_path,
            role=SessionRole.IMPLEMENTOR,
            model=model,
            allowed_tools=allowed_tools,
            prompt=_build_feedback_prompt(issue_body, review_text),
            context_files=[],
        )
        sessions.append(feedback_session)
        _record_session(
            session=feedback_session,
            session_id=uuid.uuid4().hex,
            run_id=run_id,
            wave=wave_name,
            issue_number=issue_number,
            role=SessionRole.IMPLEMENTOR,
            skill="implement_feedback",
            model=model,
            started_at=feedback_started,
            finished_at=datetime.now(UTC),
            capture_writer=capture_writer,
            langfuse_emitter=langfuse_emitter,
        )

        diff = feature_branch.diff()
        diff_stat = feature_branch.diff_stat()


def _build_body_prompt(issue_body: str, diff_stat: str) -> str:
    return (
        "Write a concise PR body for the following changes. "
        "Summarise what was changed and why.\n\n"
        f"## Issue\n\n{issue_body}\n\n"
        f"## Diff stat\n\n```\n{diff_stat}\n```"
    )


def _build_review_prompt(issue_body: str, diff: str, pr_body: str) -> str:
    return (
        "Review the following diff against the issue's acceptance criteria "
        "and the project's architecture rules. "
        "Reply with APPROVED if the changes are correct and complete, "
        "or REQUEST_CHANGES followed by specific feedback.\n\n"
        f"## Issue\n\n{issue_body}\n\n"
        f"## PR body\n\n{pr_body}\n\n"
        f"## Diff\n\n```diff\n{diff[:8000]}\n```"
    )


def _build_feedback_prompt(issue_body: str, review_feedback: str) -> str:
    return (
        "The reviewer has requested changes. Address the feedback below.\n\n"
        f"## Review feedback\n\n{review_feedback}\n\n"
        f"## Issue (for reference)\n\n{issue_body}"
    )


def _extract_text(session: SessionResult) -> str:
    from app.providers.types import EventKind

    parts = [e.content for e in session.events if e.kind == EventKind.OUTPUT and e.content]
    return "\n".join(parts)


def _is_approval(review_text: str) -> bool:
    upper = review_text.upper()
    return "APPROVED" in upper and "REQUEST_CHANGES" not in upper
