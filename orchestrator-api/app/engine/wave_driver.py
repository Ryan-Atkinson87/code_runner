from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from app.blockers.models import BlockerType
from app.blockers.store import BlockerStore
from app.config.schema import ProjectConfig
from app.engine.escalation import EscalationResult, blocker_type_for_outcome, escalate
from app.engine.implement_loop import (
    BlockerRecord,
    ImplementOutcome,
    implement_and_gate,
)
from app.engine.markers import IssueMarker
from app.engine.review_cycle import ReviewOutcome, review_and_merge
from app.engine.scheduler import IssueTask, WaveScheduler
from app.git.agent_branch import AgentBranch
from app.git.feature_branch import FeatureBranch
from app.git.merge_queue import MergeQueue
from app.git.repo import GitRepo
from app.github.models import PullRequest
from app.handoff.engine import HandoffEngine
from app.handoff.models import HandoffInput, IssueNote, ParkedBlocker
from app.notifications.dispatcher import Dispatcher
from app.observability.capture import EventCaptureWriter
from app.observability.langfuse_emitter import LangfuseEmitter
from app.personas.models import Overlay, PersonaType
from app.profile.schema import ExecutionProfile
from app.providers.adapter import ProviderAdapter
from app.providers.hooks import CODING_TOOLS
from app.renderer.base import RenderedOutput
from app.renderer.pipeline import compose_and_render
from app.skills.models import Skill
from app.sync.social_context import SocialContextUpdater
from app.wave.assembly import WaveAssemblyResult

logger = logging.getLogger(__name__)


class WaveError(Exception):
    pass


@dataclass
class IssueOutcome:
    issue_number: int
    completed: bool
    blocker: BlockerRecord | None = None


@dataclass
class WaveResult:
    issue_outcomes: list[IssueOutcome] = field(default_factory=list)
    prs: list[PullRequest] = field(default_factory=list)
    parked_blockers: list[BlockerRecord] = field(default_factory=list)
    escalation_results: list[EscalationResult] = field(default_factory=list)


async def run_wave(
    wave: WaveAssemblyResult,
    project_config: ProjectConfig,
    profile: ExecutionProfile,
    adapter: ProviderAdapter,
    handoff_engine: HandoffEngine,
    db_conn: sqlite3.Connection,
    repo_paths: dict[str, Path],
    skills: list[Skill],
    base_prompts: dict[PersonaType, str],
    overlays: list[Overlay],
    model: str,
    wave_name: str,
    run_id: int,
    cap: int | None = None,
    blocker_store: BlockerStore | None = None,
    dispatcher: Dispatcher | None = None,
    social_context_updater: SocialContextUpdater | None = None,
    capture_writer: EventCaptureWriter | None = None,
    langfuse_emitter: LangfuseEmitter | None = None,
) -> WaveResult:
    """Drive the full wave loop (Spec §4.2).

    Assembles every Phase-1/2/3 primitive into the end-to-end run.
    AI is invoked only for plan/implement/review judgement; all
    sequencing, git, gating, and PR mechanics are plain Python.
    """
    if wave.unplanned:
        raise WaveError("Unplanned wave: planner session required but not yet triggered")

    marker_store = IssueMarker(db_conn)
    merge_queue = MergeQueue()
    scheduler = WaveScheduler(cap=cap)
    _blocker_store = blocker_store or BlockerStore(db_conn)
    escalation_results: list[EscalationResult] = []

    repos: dict[str, GitRepo] = {}
    agent_branches: dict[str, AgentBranch] = {}
    for repo_entry in project_config.repos:
        if repo_entry.name not in repo_paths:
            continue
        path = repo_paths[repo_entry.name]
        repo = GitRepo(path)
        ab = AgentBranch(repo, project_config.branches, wave_name)
        ab.create_or_reuse()
        repos[repo_entry.name] = repo
        agent_branches[repo_entry.name] = ab

    provider = project_config.provider.default
    rendered_per_persona = compose_and_render(
        profile=profile,
        skills=skills,
        base_prompts=base_prompts,
        overlays=overlays,
        provider=provider,
    )

    impl_key = _find_persona_key(rendered_per_persona, "implementor")
    review_key = _find_persona_key(rendered_per_persona, "reviewer")
    impl_rendered = rendered_per_persona.get(impl_key, RenderedOutput())
    review_rendered = rendered_per_persona.get(review_key, RenderedOutput())

    repo_entries_by_name = {r.name: r for r in project_config.repos}
    allowed_tools = list(CODING_TOOLS)

    issue_bodies = {i.number: i.title for i in wave.ordered_issues}

    all_outcomes: list[IssueOutcome] = []
    parked: list[BlockerRecord] = []

    tasks = [
        IssueTask(
            issue_number=i.number,
            repo_name=i.repo,
            depends_on=[d for d in i.depends_on if d in {w.number for w in wave.ordered_issues}],
        )
        for i in wave.ordered_issues
    ]

    async def execute_issue(task: IssueTask) -> IssueOutcome:
        repo = repos[task.repo_name]
        repo_path = repo_paths[task.repo_name]
        ab = agent_branches[task.repo_name]
        repo_entry = repo_entries_by_name[task.repo_name]

        fb = FeatureBranch(repo, ab.name, task.issue_number)
        fb.create()

        impl_result = await implement_and_gate(
            issue_number=task.issue_number,
            issue_body=issue_bodies.get(task.issue_number, ""),
            repo=repo,
            repo_name=task.repo_name,
            repo_path=repo_path,
            adapter=adapter,
            gate_commands=repo_entry.commands,
            rendered_output=impl_rendered,
            marker_store=marker_store,
            run_id=run_id,
            model=model,
            allowed_tools=allowed_tools,
            wave_name=wave_name,
            capture_writer=capture_writer,
            langfuse_emitter=langfuse_emitter,
            test_fix_attempts=project_config.limits.test_fix_attempts,
        )

        if impl_result.outcome != ImplementOutcome.GATES_PASSED:
            blocker = impl_result.blocker or BlockerRecord(
                issue_number=task.issue_number,
                reason=f"Implementation failed: {impl_result.outcome}",
            )
            parked.append(blocker)
            esc = escalate(
                blocker_record=blocker,
                run_id=run_id,
                wave_name=wave_name,
                blocker_store=_blocker_store,
                dispatcher=dispatcher,
                blocker_type=blocker_type_for_outcome(impl_result.outcome.value),
            )
            escalation_results.append(esc)
            fb.discard()
            return IssueOutcome(
                issue_number=task.issue_number,
                completed=False,
                blocker=blocker,
            )

        review_result = await review_and_merge(
            issue_number=task.issue_number,
            issue_body=issue_bodies.get(task.issue_number, ""),
            feature_branch=fb,
            repo_path=repo_path,
            adapter=adapter,
            impl_rendered=impl_rendered,
            review_rendered=review_rendered,
            marker_store=marker_store,
            merge_queue=merge_queue,
            run_id=run_id,
            model=model,
            allowed_tools=allowed_tools,
            wave_name=wave_name,
            capture_writer=capture_writer,
            langfuse_emitter=langfuse_emitter,
            review_cycles=project_config.limits.review_cycles,
        )

        if review_result.outcome != ReviewOutcome.APPROVED_AND_MERGED:
            blocker = BlockerRecord(
                issue_number=task.issue_number,
                reason=review_result.blocker_reason or "Review not approved",
            )
            parked.append(blocker)
            esc = escalate(
                blocker_record=blocker,
                run_id=run_id,
                wave_name=wave_name,
                blocker_store=_blocker_store,
                dispatcher=dispatcher,
                blocker_type=BlockerType.OTHER,
            )
            escalation_results.append(esc)
            return IssueOutcome(
                issue_number=task.issue_number,
                completed=False,
                blocker=blocker,
            )

        return IssueOutcome(issue_number=task.issue_number, completed=True)

    try:
        results = await scheduler.run_wave(tasks, execute_issue)
        all_outcomes = list(results.values())
    except Exception:
        all_outcomes = [
            IssueOutcome(issue_number=t.issue_number, completed=False)
            for t in tasks
            if t.issue_number not in {o.issue_number for o in all_outcomes}
        ]

    _sync_trackers()

    prs: list[PullRequest] = []
    for repo_entry in project_config.repos:
        if repo_entry.name not in agent_branches:
            continue
        ab = agent_branches[repo_entry.name]
        repo_path = repo_paths[repo_entry.name]

        completed = [o for o in all_outcomes if o.completed]
        handoff = HandoffInput(
            wave_name=wave_name,
            summary=f"Wave {wave_name}: {len(completed)} completed, {len(parked)} parked",
            issue_notes=[IssueNote(number=o.issue_number, summary="Completed") for o in completed],
            parked_blockers=[
                ParkedBlocker(issue_number=b.issue_number, reason=b.reason) for b in parked
            ],
        )

        try:
            pr = handoff_engine.push_and_open_pr(
                repo_name=repo_entry.name,
                repo_path=repo_path,
                agent_branch=ab.name,
                integration_branch=ab.integration_branch,
                handoff=handoff,
            )
            prs.append(pr)
        except Exception:
            pass

    if social_context_updater is not None:
        result = social_context_updater.update(wave_name)
        if not result.success:
            logger.warning(
                "Social Context update failed for wave %s: %s",
                wave_name,
                result.error,
            )

    return WaveResult(
        issue_outcomes=all_outcomes,
        prs=prs,
        parked_blockers=parked,
        escalation_results=escalation_results,
    )


def _find_persona_key(rendered: dict[str, RenderedOutput], type_prefix: str) -> str:
    for key in rendered:
        if key.startswith(type_prefix):
            return key
    return ""


def _sync_trackers() -> None:
    """Stub for Phase 5 tracker sync (GitHub board, Notion)."""
