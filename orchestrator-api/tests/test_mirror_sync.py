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
from app.notion.models import DatabaseRow, NotionDatabase
from app.sync.mirror import (
    MirrorSyncError,
    NotionMirrorSync,
    SyncResult,
    _build_target_properties,
    _issue_key,
    _properties_differ,
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
            ),
        ),
        repos=[RepoEntry(name=r) for r in repo_list],
        secrets={"github_pat": "GITHUB_PAT", "notion_token": "NOTION_TOKEN"},
    )


def _config_no_notion() -> ProjectConfig:
    return ProjectConfig(
        project=ProjectSection(name="Test Project"),
        integrations=IntegrationsSection(
            github=GitHubIntegration(owner="test-owner"),
            notion=None,
        ),
        repos=[RepoEntry(name="code_runner")],
        secrets={},
    )


MILESTONE = Milestone(number=1, title="Phase 1", state="open")

ISSUES: list[Issue] = [
    Issue(
        number=1,
        title="First issue",
        body="The first one",
        state="open",
        repo="code_runner",
        milestone=MILESTONE,
        labels=["enhancement"],
    ),
    Issue(
        number=2,
        title="Second issue",
        body="The second one",
        state="closed",
        repo="code_runner",
        milestone=MILESTONE,
        labels=["bug", "chore"],
    ),
]

TECH_TASKS_DB = NotionDatabase(
    id="db000000-0000-0000-0000-000000000001",
    title="Technical Tasks",
    url="https://notion.so/db",
    parent_id="dash-00000000-0000-0000-0000-000000000001",
)


def _notion_row(
    row_id: str,
    number: int,
    repo: str,
    title: str = "Some title",
    status: str = "Open",
    milestone: str | None = "Phase 1",
    labels: list[str] | None = None,
) -> DatabaseRow:
    props: dict[str, Any] = {
        "Name": {"type": "title", "title": [{"plain_text": title}]},
        "GitHub #": {"type": "number", "number": number},
        "Repo": {"type": "select", "select": {"name": repo}},
        "Status": {"type": "select", "select": {"name": status}},
    }
    if milestone:
        props["Milestone"] = {"type": "select", "select": {"name": milestone}}
    else:
        props["Milestone"] = {"type": "select", "select": None}
    label_list = labels or []
    props["Labels"] = {
        "type": "multi_select",
        "multi_select": [{"name": label} for label in label_list],
    }
    return DatabaseRow(id=row_id, properties=props)


# ── Unit tests for helpers ────────────────────────────────────────────


class TestIssueKey:
    def test_formats_key(self) -> None:
        assert _issue_key(ISSUES[0]) == "code_runner#1"

    def test_different_repo(self) -> None:
        issue = Issue(number=5, title="X", body="", state="open", repo="other_repo")
        assert _issue_key(issue) == "other_repo#5"


class TestBuildTargetProperties:
    def test_open_issue(self) -> None:
        props = _build_target_properties(ISSUES[0])
        assert props["Name"] == {"title": [{"text": {"content": "First issue"}}]}
        assert props["GitHub #"] == {"number": 1}
        assert props["Repo"] == {"select": {"name": "code_runner"}}
        assert props["Status"] == {"select": {"name": "Open"}}
        assert props["Milestone"] == {"select": {"name": "Phase 1"}}
        assert props["Labels"] == {"multi_select": [{"name": "enhancement"}]}

    def test_closed_issue(self) -> None:
        props = _build_target_properties(ISSUES[1])
        assert props["Status"] == {"select": {"name": "Closed"}}
        assert props["Labels"] == {
            "multi_select": [{"name": "bug"}, {"name": "chore"}]
        }

    def test_issue_no_milestone(self) -> None:
        issue = Issue(number=3, title="No ms", body="", state="open", repo="r")
        props = _build_target_properties(issue)
        assert props["Milestone"] == {"select": None}

    def test_issue_no_labels(self) -> None:
        issue = Issue(
            number=4, title="No labels", body="", state="open", repo="r",
            milestone=MILESTONE,
        )
        props = _build_target_properties(issue)
        assert props["Labels"] == {"multi_select": []}


class TestPropertiesDiffer:
    def test_same_properties(self) -> None:
        existing: dict[str, Any] = {
            "Name": {"type": "title", "title": [{"plain_text": "First issue"}]},
            "GitHub #": {"type": "number", "number": 1},
            "Status": {"type": "select", "select": {"name": "Open"}},
            "Repo": {"type": "select", "select": {"name": "code_runner"}},
            "Milestone": {"type": "select", "select": {"name": "Phase 1"}},
            "Labels": {"type": "multi_select", "multi_select": [{"name": "enhancement"}]},
        }
        target = _build_target_properties(ISSUES[0])
        assert not _properties_differ(existing, target)

    def test_status_changed(self) -> None:
        existing: dict[str, Any] = {
            "Name": {"type": "title", "title": [{"plain_text": "First issue"}]},
            "GitHub #": {"type": "number", "number": 1},
            "Status": {"type": "select", "select": {"name": "Closed"}},
            "Repo": {"type": "select", "select": {"name": "code_runner"}},
            "Milestone": {"type": "select", "select": {"name": "Phase 1"}},
            "Labels": {"type": "multi_select", "multi_select": [{"name": "enhancement"}]},
        }
        target = _build_target_properties(ISSUES[0])
        assert _properties_differ(existing, target)

    def test_missing_property(self) -> None:
        existing: dict[str, Any] = {
            "Name": {"type": "title", "title": [{"plain_text": "First issue"}]},
            "GitHub #": {"type": "number", "number": 1},
        }
        target = _build_target_properties(ISSUES[0])
        assert _properties_differ(existing, target)

    def test_labels_order_irrelevant(self) -> None:
        existing: dict[str, Any] = {
            "Name": {"type": "title", "title": [{"plain_text": "Second issue"}]},
            "GitHub #": {"type": "number", "number": 2},
            "Status": {"type": "select", "select": {"name": "Closed"}},
            "Repo": {"type": "select", "select": {"name": "code_runner"}},
            "Milestone": {"type": "select", "select": {"name": "Phase 1"}},
            "Labels": {
                "type": "multi_select",
                "multi_select": [{"name": "chore"}, {"name": "bug"}],
            },
        }
        target = _build_target_properties(ISSUES[1])
        assert not _properties_differ(existing, target)


# ── Integration-level sync tests ─────────────────────────────────────


class TestFirstSync:
    def test_creates_rows_for_all_issues(self) -> None:
        github = MagicMock(spec=GitHubClient)
        github.list_milestones.return_value = [MILESTONE]
        github.list_issues.side_effect = [
            ISSUES,  # open
            [],      # closed
        ]

        notion = MagicMock(spec=NotionClient)
        notion.discover_databases.return_value = {"technical_tasks": TECH_TASKS_DB}
        notion.query_database.return_value = []
        notion.create_database_row.return_value = DatabaseRow(id="new", properties={})

        sync = NotionMirrorSync(github, notion, _config())
        result = sync.sync()

        assert result.created == 2
        assert result.updated == 0
        assert result.unchanged == 0
        assert result.ok
        assert notion.create_database_row.call_count == 2


class TestConvergenceResync:
    def test_no_op_when_already_in_sync(self) -> None:
        github = MagicMock(spec=GitHubClient)
        github.list_milestones.return_value = [MILESTONE]
        github.list_issues.side_effect = [
            ISSUES,  # open
            [],      # closed
        ]

        existing_rows = [
            _notion_row(
                "row-1", 1, "code_runner",
                title="First issue", status="Open",
                milestone="Phase 1", labels=["enhancement"],
            ),
            _notion_row(
                "row-2", 2, "code_runner",
                title="Second issue", status="Closed",
                milestone="Phase 1", labels=["bug", "chore"],
            ),
        ]

        notion = MagicMock(spec=NotionClient)
        notion.discover_databases.return_value = {"technical_tasks": TECH_TASKS_DB}
        notion.query_database.return_value = existing_rows

        sync = NotionMirrorSync(github, notion, _config())
        result = sync.sync()

        assert result.created == 0
        assert result.updated == 0
        assert result.unchanged == 2
        assert result.ok
        notion.create_database_row.assert_not_called()
        notion.update_database_row.assert_not_called()

    def test_updates_changed_status(self) -> None:
        github = MagicMock(spec=GitHubClient)
        github.list_milestones.return_value = [MILESTONE]
        github.list_issues.side_effect = [
            ISSUES,  # open
            [],      # closed
        ]

        existing_rows = [
            _notion_row(
                "row-1", 1, "code_runner",
                title="First issue", status="Closed",
                milestone="Phase 1", labels=["enhancement"],
            ),
            _notion_row(
                "row-2", 2, "code_runner",
                title="Second issue", status="Closed",
                milestone="Phase 1", labels=["bug", "chore"],
            ),
        ]

        notion = MagicMock(spec=NotionClient)
        notion.discover_databases.return_value = {"technical_tasks": TECH_TASKS_DB}
        notion.query_database.return_value = existing_rows
        notion.update_database_row.return_value = DatabaseRow(id="row-1", properties={})

        sync = NotionMirrorSync(github, notion, _config())
        result = sync.sync()

        assert result.created == 0
        assert result.updated == 1
        assert result.unchanged == 1
        assert result.ok


class TestPartialFailureRecovery:
    def test_continues_after_single_row_failure(self) -> None:
        github = MagicMock(spec=GitHubClient)
        github.list_milestones.return_value = [MILESTONE]
        github.list_issues.side_effect = [
            ISSUES,  # open
            [],      # closed
        ]

        notion = MagicMock(spec=NotionClient)
        notion.discover_databases.return_value = {"technical_tasks": TECH_TASKS_DB}
        notion.query_database.return_value = []
        notion.create_database_row.side_effect = [
            NotionError("Server error", status_code=500),
            DatabaseRow(id="row-2", properties={}),
        ]

        sync = NotionMirrorSync(github, notion, _config())
        result = sync.sync()

        assert result.created == 1
        assert result.errors == ["Failed to sync code_runner#1: Server error"]
        assert not result.ok

    def test_rerun_after_failure_converges(self) -> None:
        """Simulate: first run fails on issue #1, second run creates it."""
        github = MagicMock(spec=GitHubClient)
        github.list_milestones.return_value = [MILESTONE]
        github.list_issues.side_effect = [
            ISSUES,  # open
            [],      # closed
        ]

        row_2 = _notion_row(
            "row-2", 2, "code_runner",
            title="Second issue", status="Closed",
            milestone="Phase 1", labels=["bug", "chore"],
        )

        notion = MagicMock(spec=NotionClient)
        notion.discover_databases.return_value = {"technical_tasks": TECH_TASKS_DB}
        notion.query_database.return_value = [row_2]
        notion.create_database_row.return_value = DatabaseRow(id="row-1", properties={})

        sync = NotionMirrorSync(github, notion, _config())
        result = sync.sync()

        assert result.created == 1
        assert result.unchanged == 1
        assert result.ok


class TestMultiRepo:
    def test_syncs_issues_across_repos(self) -> None:
        milestone_a = Milestone(number=1, title="Phase 1", state="open")
        milestone_b = Milestone(number=2, title="Phase 1", state="open")
        issue_a = Issue(
            number=1, title="Backend task", body="", state="open",
            repo="backend", milestone=milestone_a,
        )
        issue_b = Issue(
            number=1, title="Frontend task", body="", state="open",
            repo="frontend", milestone=milestone_b,
        )

        github = MagicMock(spec=GitHubClient)
        github.list_milestones.side_effect = [
            [milestone_a],
            [milestone_b],
        ]
        github.list_issues.side_effect = [
            [issue_a],  # backend open
            [],          # backend closed
            [issue_b],  # frontend open
            [],          # frontend closed
        ]

        notion = MagicMock(spec=NotionClient)
        notion.discover_databases.return_value = {"technical_tasks": TECH_TASKS_DB}
        notion.query_database.return_value = []
        notion.create_database_row.return_value = DatabaseRow(id="new", properties={})

        config = _config(repos=["backend", "frontend"])
        sync = NotionMirrorSync(github, notion, config)
        result = sync.sync()

        assert result.created == 2
        assert result.ok
        calls = notion.create_database_row.call_args_list
        repos_synced = [
            call.args[1]["Repo"]["select"]["name"] for call in calls
        ]
        assert "backend" in repos_synced
        assert "frontend" in repos_synced


class TestConfigValidation:
    def test_raises_when_notion_not_configured(self) -> None:
        github = MagicMock(spec=GitHubClient)
        notion = MagicMock(spec=NotionClient)

        sync = NotionMirrorSync(github, notion, _config_no_notion())
        with pytest.raises(MirrorSyncError, match="not configured"):
            sync.sync()

    def test_raises_when_database_not_found(self) -> None:
        github = MagicMock(spec=GitHubClient)
        notion = MagicMock(spec=NotionClient)
        notion.discover_databases.return_value = {}

        sync = NotionMirrorSync(github, notion, _config())
        with pytest.raises(MirrorSyncError, match="Technical Tasks database not found"):
            sync.sync()


class TestSyncResult:
    def test_total_processed(self) -> None:
        r = SyncResult(created=3, updated=2, unchanged=5)
        assert r.total_processed == 10

    def test_ok_with_no_errors(self) -> None:
        assert SyncResult().ok

    def test_not_ok_with_errors(self) -> None:
        r = SyncResult(errors=["something failed"])
        assert not r.ok
