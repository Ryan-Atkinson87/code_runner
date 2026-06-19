from __future__ import annotations

from pathlib import Path

from app.github.client import GitHubClient
from app.github.models import PullRequest
from app.handoff.body import assemble_pr_body
from app.handoff.models import HandoffInput


class HandoffEngine:
    """Pushes the agent branch and opens one structured PR per repo (Spec §5.4).

    This is the only push to GitHub in the whole wave. Human notification
    (step 4) and Social Media Context update (step 6) are extension points
    for Phase 5 — not implemented here.
    """

    def __init__(self, github: GitHubClient) -> None:
        self._github = github

    def push_and_open_pr(
        self,
        repo_name: str,
        repo_path: Path,
        agent_branch: str,
        integration_branch: str,
        handoff: HandoffInput,
    ) -> PullRequest:
        """Push the agent branch and open a single hand-off PR.

        Returns the created PullRequest.
        """
        self._github.push_branch(repo_path, agent_branch)

        body = assemble_pr_body(handoff)
        return self._github.create_pull_request(
            repo=repo_name,
            head=agent_branch,
            base=integration_branch,
            title=f"Wave: {handoff.wave_name}",
            body=body,
        )

    def cleanup_after_merge(
        self,
        repo_path: Path,
        agent_branch: str,
    ) -> None:
        """Delete the remote agent branch after the human merges the PR."""
        self._github.delete_remote_branch(repo_path, agent_branch)
