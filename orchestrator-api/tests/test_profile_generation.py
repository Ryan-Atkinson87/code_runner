from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.config.schema import (
    GitHubIntegration,
    IntegrationsSection,
    ProjectConfig,
    ProjectSection,
    RepoEntry,
)
from app.engine.profile_generation import (
    ProposalOutcome,
    _build_proposal_prompt,
    _extract_yaml,
    _scan_repos,
    confirm_and_write,
    generate_proposal,
    needs_regeneration,
)
from app.profile.schema import ExecutionProfile, PersonaEntry, PersonaType
from app.providers.types import (
    EventKind,
    NormalisedEvent,
    SessionOutcome,
    SessionResult,
    UsageReport,
)


def _project_config() -> ProjectConfig:
    return ProjectConfig(
        project=ProjectSection(name="test-project"),
        integrations=IntegrationsSection(
            github=GitHubIntegration(owner="test-org"),
        ),
        repos=[
            RepoEntry(name="backend", path="backend", backend=True),
            RepoEntry(name="frontend", path="frontend"),
        ],
        secrets={},
    )


_VALID_PROFILE_YAML = """\
personas:
  - type: planner
  - type: implementor
    speciality: backend
  - type: reviewer
    speciality: backend
"""


def _session_with_yaml(yaml_content: str) -> SessionResult:
    text = f"Here is the proposed profile:\n\n```yaml\n{yaml_content}\n```\n\nThis should work."
    return SessionResult(
        outcome=SessionOutcome.COMPLETED,
        events=[NormalisedEvent(kind=EventKind.OUTPUT, content=text)],
        usage=UsageReport(duration_seconds=30.0),
    )


def _session_with_text(text: str) -> SessionResult:
    return SessionResult(
        outcome=SessionOutcome.COMPLETED,
        events=[NormalisedEvent(kind=EventKind.OUTPUT, content=text)],
        usage=UsageReport(duration_seconds=5.0),
    )


def _error_session() -> SessionResult:
    return SessionResult(
        outcome=SessionOutcome.ERROR,
        usage=UsageReport(duration_seconds=1.0),
    )


class TestExtractYaml:
    def test_extracts_from_yaml_block(self) -> None:
        text = "Here:\n```yaml\nfoo: bar\n```\nDone."
        assert _extract_yaml(text) == "foo: bar"

    def test_extracts_from_yml_block(self) -> None:
        text = "```yml\nfoo: bar\n```"
        assert _extract_yaml(text) == "foo: bar"

    def test_falls_back_to_full_text(self) -> None:
        text = "foo: bar\nbaz: qux"
        assert _extract_yaml(text) == text

    def test_handles_empty(self) -> None:
        assert _extract_yaml("") == ""


class TestScanRepos:
    def test_lists_entries(self, tmp_path: Path) -> None:
        repo = tmp_path / "myrepo"
        repo.mkdir()
        (repo / "src").mkdir()
        (repo / "README.md").write_text("# readme")
        result = _scan_repos([repo])
        assert "myrepo" in result
        assert "src/" in result
        assert "README.md" in result

    def test_includes_config_content(self, tmp_path: Path) -> None:
        repo = tmp_path / "backend"
        repo.mkdir()
        (repo / "pyproject.toml").write_text('[project]\nname = "backend"')
        result = _scan_repos([repo])
        assert "pyproject.toml" in result
        assert "[project]" in result


class TestBuildProposalPrompt:
    def test_includes_project_name(self) -> None:
        config = _project_config()
        prompt = _build_proposal_prompt(config, "scan data")
        assert "test-project" in prompt
        assert "backend" in prompt
        assert "frontend" in prompt
        assert "scan data" in prompt


class TestGenerateProposal:
    @pytest.mark.asyncio
    async def test_valid_proposal(self, tmp_path: Path) -> None:
        repo = tmp_path / "backend"
        repo.mkdir()
        (repo / "app.py").write_text("# app")

        adapter = AsyncMock()
        adapter.run_session = AsyncMock(return_value=_session_with_yaml(_VALID_PROFILE_YAML))

        result = await generate_proposal(
            project_config=_project_config(),
            repo_paths=[repo],
            adapter=adapter,
            model="claude-sonnet-4-6",
        )

        assert result.outcome == ProposalOutcome.PROPOSED
        assert result.proposal is not None
        assert len(result.proposal.profile.personas) == 3

    @pytest.mark.asyncio
    async def test_invalid_yaml_returns_validation_error(self, tmp_path: Path) -> None:
        repo = tmp_path / "backend"
        repo.mkdir()

        adapter = AsyncMock()
        adapter.run_session = AsyncMock(return_value=_session_with_yaml("not: [valid: yaml: {{}"))

        result = await generate_proposal(
            project_config=_project_config(),
            repo_paths=[repo],
            adapter=adapter,
            model="claude-sonnet-4-6",
        )

        assert result.outcome == ProposalOutcome.VALIDATION_ERROR

    @pytest.mark.asyncio
    async def test_invalid_schema_returns_validation_error(self, tmp_path: Path) -> None:
        repo = tmp_path / "backend"
        repo.mkdir()

        adapter = AsyncMock()
        adapter.run_session = AsyncMock(return_value=_session_with_yaml("personas: []"))

        result = await generate_proposal(
            project_config=_project_config(),
            repo_paths=[repo],
            adapter=adapter,
            model="claude-sonnet-4-6",
        )

        assert result.outcome == ProposalOutcome.VALIDATION_ERROR
        assert "validation" in result.error.lower()

    @pytest.mark.asyncio
    async def test_session_error(self, tmp_path: Path) -> None:
        repo = tmp_path / "backend"
        repo.mkdir()

        adapter = AsyncMock()
        adapter.run_session = AsyncMock(return_value=_error_session())

        result = await generate_proposal(
            project_config=_project_config(),
            repo_paths=[repo],
            adapter=adapter,
            model="claude-sonnet-4-6",
        )

        assert result.outcome == ProposalOutcome.SESSION_ERROR

    @pytest.mark.asyncio
    async def test_non_mapping_yaml_returns_error(self, tmp_path: Path) -> None:
        repo = tmp_path / "backend"
        repo.mkdir()

        adapter = AsyncMock()
        adapter.run_session = AsyncMock(return_value=_session_with_yaml("- just\n- a\n- list"))

        result = await generate_proposal(
            project_config=_project_config(),
            repo_paths=[repo],
            adapter=adapter,
            model="claude-sonnet-4-6",
        )

        assert result.outcome == ProposalOutcome.VALIDATION_ERROR
        assert "mapping" in result.error.lower()


class TestConfirmAndWrite:
    def test_writes_file(self, tmp_path: Path) -> None:
        profile = ExecutionProfile(personas=[PersonaEntry(type=PersonaType.PLANNER)])
        from app.engine.profile_generation import ProfileProposal

        proposal = ProfileProposal(
            raw_yaml=_VALID_PROFILE_YAML,
            profile=profile,
            session=_session_with_text("done"),
        )
        output = tmp_path / "execution-profile.yaml"
        result = confirm_and_write(proposal, output)
        assert result == output
        assert output.exists()
        assert "personas" in output.read_text()

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        profile = ExecutionProfile(personas=[PersonaEntry(type=PersonaType.PLANNER)])
        from app.engine.profile_generation import ProfileProposal

        proposal = ProfileProposal(
            raw_yaml=_VALID_PROFILE_YAML,
            profile=profile,
            session=_session_with_text("done"),
        )
        output = tmp_path / "deep" / "nested" / "execution-profile.yaml"
        confirm_and_write(proposal, output)
        assert output.exists()

    def test_rejection_leaves_no_file(self, tmp_path: Path) -> None:
        output = tmp_path / "execution-profile.yaml"
        assert not output.exists()


class TestNeedsRegeneration:
    def test_no_profile_needs_regeneration(self, tmp_path: Path) -> None:
        profile_path = tmp_path / "execution-profile.yaml"
        assert needs_regeneration(profile_path, _project_config(), [tmp_path])

    def test_existing_profile_no_change(self, tmp_path: Path) -> None:
        profile_path = tmp_path / "execution-profile.yaml"
        profile_path.write_text("personas:\n  - type: planner\n\n# backend frontend")
        backend = tmp_path / "backend"
        backend.mkdir()
        frontend = tmp_path / "frontend"
        frontend.mkdir()
        assert not needs_regeneration(profile_path, _project_config(), [backend, frontend])

    def test_new_repo_detected(self, tmp_path: Path) -> None:
        profile_path = tmp_path / "execution-profile.yaml"
        profile_path.write_text("personas:\n  - type: planner")
        config = _project_config()
        backend = tmp_path / "backend"
        backend.mkdir()
        assert needs_regeneration(profile_path, config, [backend])
