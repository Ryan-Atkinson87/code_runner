from __future__ import annotations

from app.git.errors import MergeConflictError
from app.git.repo import GitRepo


class FeatureBranch:
    """Short-lived feature branch off an agent branch for a single issue (Spec §5.3).

    Provides deterministic branch creation, diff production, merge, and discard.
    The AI review invocation is not part of this class — that is Phase 3 wiring.
    """

    def __init__(self, repo: GitRepo, agent_branch: str, issue_number: int) -> None:
        self._repo = repo
        self._agent_branch = agent_branch
        self._issue_number = issue_number
        self._branch_name = f"feature/issue-{issue_number}"

    @property
    def name(self) -> str:
        return self._branch_name

    @property
    def agent_branch(self) -> str:
        return self._agent_branch

    @property
    def issue_number(self) -> int:
        return self._issue_number

    def create(self) -> None:
        """Create the feature branch off the agent branch and check it out."""
        self._repo.create_and_checkout(self._branch_name, self._agent_branch)

    def diff(self) -> str:
        """Produce the feature→agent diff that internal review consumes."""
        return self._repo.diff(self._agent_branch, self._branch_name)

    def diff_stat(self) -> str:
        """Produce a summary stat of the feature→agent diff."""
        return self._repo.diff_stat(self._agent_branch, self._branch_name)

    def merge_into_agent(self) -> str:
        """Merge the feature branch into the agent branch and delete it.

        Returns the merge commit SHA. On merge conflict, aborts the merge,
        returns to the feature branch, and raises MergeConflictError so the
        caller can park the issue without corrupting the agent branch.
        """
        self._repo.checkout(self._agent_branch)
        try:
            self._repo.merge(
                self._branch_name,
                message=f"Merge issue #{self._issue_number} into agent branch",
            )
        except MergeConflictError:
            self._repo.abort_merge()
            self._repo.checkout(self._branch_name)
            raise
        sha = self._repo.rev_parse("HEAD")
        self._repo.delete_branch(self._branch_name)
        return sha

    def discard(self) -> None:
        """Discard the feature branch entirely (§18.4 crash recovery).

        Checks out the agent branch and force-deletes the feature branch.
        """
        self._repo.checkout(self._agent_branch)
        self._repo.delete_branch(self._branch_name, force=True)
