from __future__ import annotations

import re
import unicodedata

from app.config.schema import BranchesSection
from app.git.repo import GitRepo


def slugify_wave(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered)
    return slug.strip("-")


def agent_branch_name(wave_name: str, branches: BranchesSection) -> str:
    slug = slugify_wave(wave_name)
    return branches.agent_pattern.replace("<wave-slug>", slug)


class AgentBranch:
    def __init__(self, repo: GitRepo, branches: BranchesSection, wave_name: str) -> None:
        self._repo = repo
        self._branches = branches
        self._wave_name = wave_name
        self._branch_name = agent_branch_name(wave_name, branches)

    @property
    def name(self) -> str:
        return self._branch_name

    @property
    def integration_branch(self) -> str:
        return self._branches.integration

    def create_or_reuse(self) -> bool:
        """Fetch integration branch and create the agent branch, or reuse if it
        already exists (e.g. after a crash). Returns True if freshly created."""
        self._repo.fetch("origin", self._branches.integration)

        if self._repo.branch_exists(self._branch_name):
            self._repo.checkout(self._branch_name)
            return False

        self._repo.create_and_checkout(
            self._branch_name,
            f"origin/{self._branches.integration}",
        )
        return True

    def sync(self) -> bool:
        """Keep the agent branch current with the integration branch.

        Uses the configured sync_strategy (merge or rebase).
        Returns True if a sync was performed, False if already up-to-date.
        """
        self._repo.fetch("origin", self._branches.integration)

        remote_ref = f"origin/{self._branches.integration}"
        new_commits = self._repo.commits_between(self._branch_name, remote_ref)
        if not new_commits:
            return False

        if self._branches.sync_strategy == "rebase":
            self._repo.rebase(remote_ref)
        else:
            self._repo.merge(
                remote_ref,
                message=f"Sync agent branch with {self._branches.integration}",
            )
        return True
