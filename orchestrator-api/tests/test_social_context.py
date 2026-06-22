from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.config.schema import (
    GitHubIntegration,
    IntegrationsSection,
    NotionIntegration,
    ProjectConfig,
    ProjectSection,
    RepoEntry,
)
from app.github.client import GitHubClient
from app.github.models import Issue, Milestone
from app.notion.client import NotionClient
from app.notion.errors import NotionError
from app.sync.social_context import (
    SocialContextError,
    SocialContextUpdater,
    WaveContext,
    _render_blocks,
)

# ── Fixtures ──────────────────────────────────────────────────────────


def _config(repos: list[str] | None = None) -> ProjectConfig:
    repo_list = repos or ["code_runner"]
    return ProjectConfig(
        project=ProjectSection(name="Test Project"),
        integrations=IntegrationsSection(
            github=GitHubIntegration(owner="test-owner"),
            notion=NotionIntegration(
                workspace="test-ws",
                dashboard_page="dash-00000000-0000-0000-0000-000000000001",
                social_context_page="sc-00000000-0000-0000-0000-000000000002",
            ),
        ),
        repos=[RepoEntry(name=r) for r in repo_list],
        secrets={"github_pat": "GITHUB_PAT", "notion_token": "NOTION_TOKEN"},
    )


def _config_no_social_page() -> ProjectConfig:
    return ProjectConfig(
        project=ProjectSection(name="Test Project"),
        integrations=IntegrationsSection(
            github=GitHubIntegration(owner="test-owner"),
            notion=NotionIntegration(
                workspace="test-ws",
                dashboard_page="dash-00000000-0000-0000-0000-000000000001",
            ),
        ),
        repos=[RepoEntry(name="code_runner")],
        secrets={},
    )


MILESTONE_CURRENT = Milestone(number=1, title="Phase 1", state="closed")
MILESTONE_NEXT = Milestone(number=2, title="Phase 2", state="open")

CLOSED_ISSUES = [
    Issue(
        number=1, title="First feature", body="", state="closed",
        repo="code_runner", milestone=MILESTONE_CURRENT,
    ),
    Issue(
        number=2, title="Second feature", body="", state="closed",
        repo="code_runner", milestone=MILESTONE_CURRENT,
    ),
]

OPEN_ISSUES = [
    Issue(
        number=3, title="Unfinished task", body="", state="open",
        repo="code_runner", milestone=MILESTONE_CURRENT,
    ),
]


# ── Render blocks ────────────────────────────────────────────────────


class TestRenderBlocks:
    def test_complete_wave(self) -> None:
        ctx = WaveContext(
            wave_name="Phase 1",
            closed_issues=CLOSED_ISSUES,
            open_issues=[],
            next_milestone=MILESTONE_NEXT,
        )
        blocks = _render_blocks(ctx)
        texts = _extract_texts(blocks)

        assert any("Current Status" in t for t in texts)
        assert any("complete" in t.lower() and "2 issue(s)" in t for t in texts)
        assert any("#1 First feature" in t for t in texts)
        assert any("#2 Second feature" in t for t in texts)
        assert any("Phase 2" in t for t in texts)

    def test_in_progress_wave(self) -> None:
        ctx = WaveContext(
            wave_name="Phase 1",
            closed_issues=CLOSED_ISSUES,
            open_issues=OPEN_ISSUES,
            next_milestone=MILESTONE_NEXT,
        )
        blocks = _render_blocks(ctx)
        texts = _extract_texts(blocks)

        assert any("in progress" in t.lower() for t in texts)
        assert any("2 issue(s) completed" in t and "1 remaining" in t for t in texts)

    def test_no_closed_issues(self) -> None:
        ctx = WaveContext(
            wave_name="Phase 1",
            closed_issues=[],
            open_issues=OPEN_ISSUES,
        )
        blocks = _render_blocks(ctx)
        texts = _extract_texts(blocks)
        assert any("No issues completed" in t for t in texts)

    def test_no_next_milestone(self) -> None:
        ctx = WaveContext(
            wave_name="Phase 1",
            closed_issues=CLOSED_ISSUES,
            open_issues=[],
        )
        blocks = _render_blocks(ctx)
        texts = _extract_texts(blocks)
        assert any("No upcoming milestones" in t for t in texts)

    def test_sections_present(self) -> None:
        ctx = WaveContext(wave_name="Phase 1", closed_issues=[], open_issues=[])
        blocks = _render_blocks(ctx)
        headings = [
            _block_text(b)
            for b in blocks
            if b.get("type") == "heading_2"
        ]
        assert "Current Status" in headings
        assert "Recent Milestones" in headings
        assert "What's Coming Next" in headings


# ── Updater integration tests ────────────────────────────────────────


class TestUpdateSuccess:
    def test_updates_page_with_rendered_blocks(self) -> None:
        github = MagicMock(spec=GitHubClient)
        github.list_milestones.return_value = [MILESTONE_CURRENT, MILESTONE_NEXT]
        github.list_issues.side_effect = [
            CLOSED_ISSUES,  # closed
            [],             # open
        ]

        notion = MagicMock(spec=NotionClient)

        updater = SocialContextUpdater(github, notion, _config())
        result = updater.update("Phase 1")

        assert result.success
        assert result.error == ""
        notion.replace_block_children.assert_called_once()
        page_ref = notion.replace_block_children.call_args[0][0]
        assert page_ref == "sc-00000000-0000-0000-0000-000000000002"


class TestIdempotent:
    def test_rerun_produces_same_blocks(self) -> None:
        github = MagicMock(spec=GitHubClient)
        github.list_milestones.return_value = [MILESTONE_CURRENT, MILESTONE_NEXT]
        github.list_issues.side_effect = [
            CLOSED_ISSUES, [],  # first run
            CLOSED_ISSUES, [],  # second run
        ]

        notion = MagicMock(spec=NotionClient)

        updater = SocialContextUpdater(github, notion, _config())
        result1 = updater.update("Phase 1")
        result2 = updater.update("Phase 1")

        assert result1.success and result2.success
        assert notion.replace_block_children.call_count == 2
        blocks1 = notion.replace_block_children.call_args_list[0][0][1]
        blocks2 = notion.replace_block_children.call_args_list[1][0][1]
        assert blocks1 == blocks2


class TestFailurePaths:
    def test_notion_error_returns_failure_result(self) -> None:
        github = MagicMock(spec=GitHubClient)
        github.list_milestones.return_value = [MILESTONE_CURRENT]
        github.list_issues.side_effect = [
            CLOSED_ISSUES,
            [],
        ]

        notion = MagicMock(spec=NotionClient)
        notion.replace_block_children.side_effect = NotionError(
            "Server error", status_code=500
        )

        updater = SocialContextUpdater(github, notion, _config())
        result = updater.update("Phase 1")

        assert not result.success
        assert "Server error" in result.error

    def test_does_not_raise_on_notion_error(self) -> None:
        github = MagicMock(spec=GitHubClient)
        github.list_milestones.return_value = [MILESTONE_CURRENT]
        github.list_issues.side_effect = [[], []]

        notion = MagicMock(spec=NotionClient)
        notion.replace_block_children.side_effect = NotionError("Fail", status_code=502)

        updater = SocialContextUpdater(github, notion, _config())
        result = updater.update("Phase 1")
        assert not result.success

    def test_raises_when_social_page_not_configured(self) -> None:
        github = MagicMock(spec=GitHubClient)
        notion = MagicMock(spec=NotionClient)

        updater = SocialContextUpdater(github, notion, _config_no_social_page())
        with pytest.raises(SocialContextError, match="not configured"):
            updater.update("Phase 1")


class TestMultiRepo:
    def test_gathers_issues_from_all_repos(self) -> None:
        ms_a = Milestone(number=1, title="Phase 1", state="closed")
        ms_b = Milestone(number=2, title="Phase 1", state="closed")
        ms_next = Milestone(number=3, title="Phase 2", state="open")

        issue_a = Issue(
            number=1, title="Backend done", body="", state="closed",
            repo="backend", milestone=ms_a,
        )
        issue_b = Issue(
            number=1, title="Frontend done", body="", state="closed",
            repo="frontend", milestone=ms_b,
        )

        github = MagicMock(spec=GitHubClient)
        github.list_milestones.side_effect = [
            [ms_a, ms_next],   # backend
            [ms_b],            # frontend
        ]
        github.list_issues.side_effect = [
            [issue_a],  # backend closed
            [],         # backend open
            [issue_b],  # frontend closed
            [],         # frontend open
        ]

        notion = MagicMock(spec=NotionClient)

        updater = SocialContextUpdater(github, notion, _config(["backend", "frontend"]))
        result = updater.update("Phase 1")

        assert result.success
        blocks = notion.replace_block_children.call_args[0][1]
        texts = _extract_texts(blocks)
        assert any("#1 Backend done" in t for t in texts)
        assert any("#1 Frontend done" in t for t in texts)
        assert any("Phase 2" in t for t in texts)


# ── Helpers ───────────────────────────────────────────────────────────


def _extract_texts(blocks: list[dict[str, Any]]) -> list[str]:
    return [_block_text(b) for b in blocks]


def _block_text(block: dict[str, Any]) -> str:
    btype = block.get("type", "")
    content = block.get(btype, {})
    rich_text = content.get("rich_text", [])
    return "".join(
        item.get("text", {}).get("content", "")
        for item in rich_text
        if isinstance(item, dict)
    )
