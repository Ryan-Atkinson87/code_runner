from __future__ import annotations

from dataclasses import dataclass

from app.engine.markers import (
    IssueMarker,
    RecoveryAction,
    WaveStep,
    recovery_action_for,
)
from app.git.repo import GitRepo


@dataclass(frozen=True)
class RecoveryDecision:
    issue_number: int
    action: RecoveryAction
    reason: str
    marker_step: WaveStep | None = None


def evaluate_recovery(
    marker_store: IssueMarker,
    repo: GitRepo,
    run_id: int,
    issue_number: int,
    feature_branch_name: str,
    agent_branch_name: str,
) -> RecoveryDecision:
    """Evaluate recovery action for a single in-flight issue (Spec §18.1–18.4).

    Git/GitHub state is truth; markers are hints. If they disagree, git wins.
    """
    marker = marker_store.read(run_id, issue_number)
    branch_exists = repo.branch_exists(feature_branch_name)

    if not branch_exists:
        return RecoveryDecision(
            issue_number=issue_number,
            action=RecoveryAction.RESUME,
            marker_step=marker[0] if marker else None,
            reason="No feature branch — fresh start",
        )

    has_commits = False
    if branch_exists:
        try:
            commits = repo.commits_between(agent_branch_name, feature_branch_name)
            has_commits = len(commits) > 0
        except Exception:
            has_commits = False

    if not has_commits:
        return RecoveryDecision(
            issue_number=issue_number,
            action=RecoveryAction.RESUME,
            marker_step=marker[0] if marker else None,
            reason="Branch exists with no commits — reuse, restart implement",
        )

    if marker is not None:
        step, _count = marker
        action = recovery_action_for(step)
        return RecoveryDecision(
            issue_number=issue_number,
            action=action,
            marker_step=step,
            reason=f"Last step was {step.value} — {action.value}",
        )

    return RecoveryDecision(
        issue_number=issue_number,
        action=RecoveryAction.RESET,
        reason="Commits exist but no marker — ambiguous, discard and restart",
    )
