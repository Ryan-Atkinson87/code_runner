from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.git.repo import GitRepo


class BranchState(Enum):
    """Durable feature-branch states derivable from git alone (Spec §18.2)."""

    ABSENT = "absent"
    EMPTY = "empty"
    DIRTY = "dirty"
    COMMITS_ONLY = "commits_only"
    MERGED = "merged"


@dataclass(frozen=True)
class BranchClassification:
    state: BranchState
    issue_number: int
    branch_name: str
    commits_ahead: int = 0


def _feature_branch_name(issue_number: int) -> str:
    return f"feature/issue-{issue_number}"


class BranchRecovery:
    """Branch-state inference and crash recovery (Spec §18.1, §18.4).

    Reads git state only — no markers, no AI invocation. Per-issue state
    markers live with the wave loop (Phase 3); this module is the
    git-derived truth that markers are checked against.
    """

    def __init__(self, repo: GitRepo, agent_branch: str) -> None:
        self._repo = repo
        self._agent_branch = agent_branch

    def classify(self, issue_number: int) -> BranchClassification:
        """Classify a feature branch's durable state from git alone.

        Returns one of:
        - ABSENT: no feature branch exists
        - EMPTY: branch exists, no commits ahead of agent branch
        - DIRTY: branch is checked out with uncommitted changes
        - COMMITS_ONLY: branch has commits, not yet merged
        - MERGED: already merged into the agent branch (advance, don't re-merge)
        """
        branch_name = _feature_branch_name(issue_number)

        if not self._repo.branch_exists(branch_name):
            return BranchClassification(
                state=BranchState.ABSENT,
                issue_number=issue_number,
                branch_name=branch_name,
            )

        is_dirty = self._repo.current_branch() == branch_name and self._repo.is_dirty()

        commits = self._repo.commits_between(self._agent_branch, branch_name)

        if commits:
            if is_dirty:
                return BranchClassification(
                    state=BranchState.DIRTY,
                    issue_number=issue_number,
                    branch_name=branch_name,
                    commits_ahead=len(commits),
                )
            return BranchClassification(
                state=BranchState.COMMITS_ONLY,
                issue_number=issue_number,
                branch_name=branch_name,
                commits_ahead=len(commits),
            )

        if self._repo.was_merged_into(branch_name, self._agent_branch):
            return BranchClassification(
                state=BranchState.MERGED,
                issue_number=issue_number,
                branch_name=branch_name,
            )

        if is_dirty:
            return BranchClassification(
                state=BranchState.DIRTY,
                issue_number=issue_number,
                branch_name=branch_name,
            )

        return BranchClassification(
            state=BranchState.EMPTY,
            issue_number=issue_number,
            branch_name=branch_name,
        )

    def classify_all(self, issue_numbers: list[int]) -> dict[int, BranchClassification]:
        """Classify multiple feature branches at once.

        On restart the engine evaluates all in-flight issues (bounded by
        the concurrency cap, §18.8). This method classifies each.
        """
        return {n: self.classify(n) for n in issue_numbers}

    def discard_and_restart(self, issue_number: int) -> None:
        """Discard a feature branch and leave the repo on the agent branch.

        Per §18.4: the partial diff is not salvaged or preserved; it is
        discarded. Handles both dirty working trees and committed-only
        branches.
        """
        branch_name = _feature_branch_name(issue_number)
        if not self._repo.branch_exists(branch_name):
            return

        if self._repo.current_branch() == branch_name:
            if self._repo.is_dirty():
                self._repo.reset_hard()
                self._repo.clean_untracked()
            self._repo.checkout(self._agent_branch)
        elif self._repo.current_branch() != self._agent_branch:
            self._repo.checkout(self._agent_branch)

        self._repo.delete_branch(branch_name, force=True)
