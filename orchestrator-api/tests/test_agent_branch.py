from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.config.schema import BranchesSection
from app.git import GitRepo, MergeConflictError
from app.git.agent_branch import AgentBranch, agent_branch_name, slugify_wave


class TestSlugifyWave:
    def test_simple_name(self) -> None:
        assert slugify_wave("Foundations") == "foundations"

    def test_phase_prefix(self) -> None:
        assert slugify_wave("P3 – Services & Profiles") == "p3-services-profiles"

    def test_unicode_normalization(self) -> None:
        assert slugify_wave("café résumé") == "cafe-resume"

    def test_punctuation_stripped(self) -> None:
        assert slugify_wave("hello, world! (v2)") == "hello-world-v2"

    def test_multiple_separators_collapsed(self) -> None:
        assert slugify_wave("a   ---  b") == "a-b"

    def test_leading_trailing_hyphens_stripped(self) -> None:
        assert slugify_wave("---hello---") == "hello"

    def test_digits_preserved(self) -> None:
        assert slugify_wave("Phase 1.2.3") == "phase-1-2-3"

    def test_empty_after_stripping(self) -> None:
        assert slugify_wave("") == ""

    def test_only_special_chars(self) -> None:
        assert slugify_wave("— – • ·") == ""

    def test_cjk_characters_stripped(self) -> None:
        assert slugify_wave("Phase 計画 1") == "phase-1"

    def test_stability(self) -> None:
        name = "P3 – Services & Profiles"
        assert slugify_wave(name) == slugify_wave(name)


class TestAgentBranchName:
    def test_default_pattern(self) -> None:
        branches = BranchesSection()
        assert agent_branch_name("Foundations", branches) == "code-runner/foundations"

    def test_custom_pattern(self) -> None:
        branches = BranchesSection(agent_pattern="agent/<wave-slug>")
        assert agent_branch_name("Foundations", branches) == "agent/foundations"

    def test_unicode_wave(self) -> None:
        branches = BranchesSection()
        result = agent_branch_name("P3 – Services & Profiles", branches)
        assert result == "code-runner/p3-services-profiles"


def _run_git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def remote_and_local(tmp_path: Path) -> tuple[Path, GitRepo]:
    """Set up a bare 'origin' with a dev branch, and a local clone."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _run_git(origin, "init", "--bare")

    work = tmp_path / "work"
    subprocess.run(
        ["git", "clone", str(origin), str(work)],
        check=True,
        capture_output=True,
        text=True,
    )
    _run_git(work, "config", "user.email", "test@test.com")
    _run_git(work, "config", "user.name", "Test")

    (work / "README.md").write_text("# Test\n")
    _run_git(work, "add", ".")
    _run_git(work, "commit", "-m", "initial")
    _run_git(work, "push", "-u", "origin", "HEAD")

    _run_git(work, "checkout", "-b", "dev")
    _run_git(work, "push", "-u", "origin", "dev")

    return origin, GitRepo(work)


class TestCreateOrReuse:
    def test_fresh_creation(self, remote_and_local: tuple[Path, GitRepo]) -> None:
        _, repo = remote_and_local
        branches = BranchesSection(integration="dev")
        ab = AgentBranch(repo, branches, "Foundations")

        created = ab.create_or_reuse()

        assert created is True
        assert repo.current_branch() == "code-runner/foundations"

    def test_branch_starts_from_integration(self, remote_and_local: tuple[Path, GitRepo]) -> None:
        _, repo = remote_and_local
        branches = BranchesSection(integration="dev")

        repo.checkout("dev")
        (repo.path / "dev-file.txt").write_text("dev content\n")
        repo.stage_all()
        repo.commit("commit on dev")
        _run_git(repo.path, "push", "origin", "dev")

        ab = AgentBranch(repo, branches, "Foundations")
        ab.create_or_reuse()

        assert (repo.path / "dev-file.txt").exists()

    def test_reuse_existing_branch(self, remote_and_local: tuple[Path, GitRepo]) -> None:
        _, repo = remote_and_local
        branches = BranchesSection(integration="dev")
        ab = AgentBranch(repo, branches, "Foundations")

        ab.create_or_reuse()
        (repo.path / "wip.txt").write_text("in progress\n")
        repo.stage_all()
        repo.commit("wip commit")
        wip_sha = repo.rev_parse("HEAD")

        main_branch = "main" if repo.branch_exists("main") else "master"
        repo.checkout(main_branch)

        ab2 = AgentBranch(repo, branches, "Foundations")
        created = ab2.create_or_reuse()

        assert created is False
        assert repo.current_branch() == "code-runner/foundations"
        assert repo.rev_parse("HEAD") == wip_sha

    def test_custom_pattern(self, remote_and_local: tuple[Path, GitRepo]) -> None:
        _, repo = remote_and_local
        branches = BranchesSection(integration="dev", agent_pattern="agent/<wave-slug>")
        ab = AgentBranch(repo, branches, "Phase 1")

        ab.create_or_reuse()

        assert repo.current_branch() == "agent/phase-1"


class TestSync:
    def test_merge_sync_when_integration_advances(
        self, remote_and_local: tuple[Path, GitRepo]
    ) -> None:
        origin, repo = remote_and_local
        branches = BranchesSection(integration="dev")
        ab = AgentBranch(repo, branches, "Wave 1")
        ab.create_or_reuse()

        repo.checkout("dev")
        (repo.path / "new-on-dev.txt").write_text("new\n")
        repo.stage_all()
        repo.commit("advance dev")
        _run_git(repo.path, "push", "origin", "dev")

        repo.checkout(ab.name)
        synced = ab.sync()

        assert synced is True
        assert (repo.path / "new-on-dev.txt").exists()

    def test_no_sync_when_up_to_date(self, remote_and_local: tuple[Path, GitRepo]) -> None:
        _, repo = remote_and_local
        branches = BranchesSection(integration="dev")
        ab = AgentBranch(repo, branches, "Wave 1")
        ab.create_or_reuse()

        synced = ab.sync()

        assert synced is False

    def test_rebase_sync_strategy(self, remote_and_local: tuple[Path, GitRepo]) -> None:
        _, repo = remote_and_local
        branches = BranchesSection(integration="dev", sync_strategy="rebase")
        ab = AgentBranch(repo, branches, "Wave 1")
        ab.create_or_reuse()

        (repo.path / "agent-work.txt").write_text("agent\n")
        repo.stage_all()
        repo.commit("agent work")

        repo.checkout("dev")
        (repo.path / "dev-advance.txt").write_text("dev\n")
        repo.stage_all()
        repo.commit("advance dev")
        _run_git(repo.path, "push", "origin", "dev")

        repo.checkout(ab.name)
        synced = ab.sync()

        assert synced is True
        assert (repo.path / "dev-advance.txt").exists()
        assert (repo.path / "agent-work.txt").exists()

    def test_merge_conflict_during_sync(self, remote_and_local: tuple[Path, GitRepo]) -> None:
        _, repo = remote_and_local
        branches = BranchesSection(integration="dev")
        ab = AgentBranch(repo, branches, "Wave 1")
        ab.create_or_reuse()

        (repo.path / "conflict.txt").write_text("agent version\n")
        repo.stage_all()
        repo.commit("agent conflict file")

        repo.checkout("dev")
        (repo.path / "conflict.txt").write_text("dev version\n")
        repo.stage_all()
        repo.commit("dev conflict file")
        _run_git(repo.path, "push", "origin", "dev")

        repo.checkout(ab.name)
        with pytest.raises(MergeConflictError):
            ab.sync()

        repo.abort_merge()


class TestProperties:
    def test_name_property(self) -> None:
        branches = BranchesSection()
        ab = AgentBranch.__new__(AgentBranch)
        ab._repo = None  # type: ignore[assignment]
        ab._branches = branches
        ab._wave_name = "Test Wave"
        ab._branch_name = agent_branch_name("Test Wave", branches)

        assert ab.name == "code-runner/test-wave"

    def test_integration_branch_property(self) -> None:
        branches = BranchesSection(integration="main")
        ab = AgentBranch.__new__(AgentBranch)
        ab._branches = branches

        assert ab.integration_branch == "main"
