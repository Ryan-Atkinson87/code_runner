from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.config.schema import ProjectConfig
from app.github.client import GitHubClient
from app.github.models import Issue
from app.notion.client import NotionClient
from app.notion.errors import NotionError
from app.notion.models import DatabaseRow

logger = logging.getLogger(__name__)


class MirrorSyncError(Exception):
    pass


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total_processed(self) -> int:
        return self.created + self.updated + self.unchanged

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


class NotionMirrorSync:
    """Idempotent GitHub→Notion mirror: make the target match the source (§18.5)."""

    def __init__(
        self,
        github: GitHubClient,
        notion: NotionClient,
        config: ProjectConfig,
    ) -> None:
        self._github = github
        self._notion = notion
        self._config = config

    def sync(self) -> SyncResult:
        result = SyncResult()

        notion_cfg = self._config.integrations.notion
        if notion_cfg is None or not notion_cfg.dashboard_page:
            raise MirrorSyncError(
                "Notion integration not configured: integrations.notion.dashboard_page is required"
            )

        databases = self._notion.discover_databases(notion_cfg.dashboard_page)
        if "technical_tasks" not in databases:
            raise MirrorSyncError(
                "Technical Tasks database not found under the Notion dashboard page"
            )
        db = databases["technical_tasks"]

        github_issues = self._read_all_github_issues()
        existing_rows = self._notion.query_database(db.id)
        row_index = self._index_rows_by_issue_key(existing_rows)

        for issue in github_issues:
            key = _issue_key(issue)
            target_props = _build_target_properties(issue)
            try:
                if key in row_index:
                    row = row_index[key]
                    if _properties_differ(row.properties, target_props):
                        self._notion.update_database_row(row.id, target_props)
                        result.updated += 1
                        logger.debug("Updated Notion row for %s", key)
                    else:
                        result.unchanged += 1
                else:
                    self._notion.create_database_row(db.id, target_props)
                    result.created += 1
                    logger.debug("Created Notion row for %s", key)
            except NotionError as exc:
                msg = f"Failed to sync {key}: {exc}"
                logger.warning(msg)
                result.errors.append(msg)

        return result

    def _read_all_github_issues(self) -> list[Issue]:
        all_issues: list[Issue] = []
        for repo_entry in self._config.repos:
            milestones = self._github.list_milestones(repo_entry.name, state="all")
            for milestone in milestones:
                for state in ("open", "closed"):
                    issues = self._github.list_issues(
                        repo_entry.name, milestone.number, state=state
                    )
                    all_issues.extend(issues)
        return all_issues

    @staticmethod
    def _index_rows_by_issue_key(rows: list[DatabaseRow]) -> dict[str, DatabaseRow]:
        index: dict[str, DatabaseRow] = {}
        for row in rows:
            number = _extract_number_property(row.properties)
            repo = _extract_select_property(row.properties, "Repo")
            if number is not None and repo:
                index[f"{repo}#{number}"] = row
        return index


def _issue_key(issue: Issue) -> str:
    return f"{issue.repo}#{issue.number}"


def _build_target_properties(issue: Issue) -> dict[str, Any]:
    props: dict[str, Any] = {
        "Name": {"title": [{"text": {"content": issue.title}}]},
        "GitHub #": {"number": issue.number},
        "Repo": {"select": {"name": issue.repo}},
        "Status": {"select": {"name": "Closed" if issue.state == "closed" else "Open"}},
    }
    if issue.milestone:
        props["Milestone"] = {"select": {"name": issue.milestone.title}}
    else:
        props["Milestone"] = {"select": None}
    if issue.labels:
        props["Labels"] = {"multi_select": [{"name": label} for label in issue.labels]}
    else:
        props["Labels"] = {"multi_select": []}
    return props


def _extract_number_property(properties: dict[str, object]) -> int | None:
    gh_num = properties.get("GitHub #")
    if isinstance(gh_num, dict):
        val = gh_num.get("number")
        if isinstance(val, (int, float)):
            return int(val)
    return None


def _extract_select_property(properties: dict[str, object], name: str) -> str:
    prop = properties.get(name)
    if isinstance(prop, dict):
        select = prop.get("select")
        if isinstance(select, dict):
            return select.get("name", "")
    return ""


def _properties_differ(existing: dict[str, object], target: dict[str, Any]) -> bool:
    for key, target_val in target.items():
        existing_val = existing.get(key)
        if existing_val is None:
            return True
        if not _property_matches(existing_val, target_val):
            return True
    return False


def _property_matches(existing: object, target: Any) -> bool:
    if not isinstance(existing, dict) or not isinstance(target, dict):
        return existing == target

    prop_type = _infer_property_type(target)

    if prop_type == "title":
        existing_text = _extract_title_text(existing)
        target_text = _extract_title_text(target)
        return existing_text == target_text

    if prop_type == "number":
        return existing.get("number") == target.get("number")

    if prop_type == "select":
        existing_select = existing.get("select")
        target_select = target.get("select")
        if target_select is None:
            return existing_select is None or (
                isinstance(existing_select, dict) and not existing_select.get("name")
            )
        if not isinstance(existing_select, dict) or not isinstance(target_select, dict):
            return existing_select == target_select
        return existing_select.get("name") == target_select.get("name")

    if prop_type == "multi_select":
        existing_ms = existing.get("multi_select", [])
        target_ms = target.get("multi_select", [])
        if not isinstance(existing_ms, list) or not isinstance(target_ms, list):
            return existing_ms == target_ms
        existing_names = sorted(
            item.get("name", "") for item in existing_ms if isinstance(item, dict)
        )
        target_names = sorted(item.get("name", "") for item in target_ms if isinstance(item, dict))
        return existing_names == target_names

    return existing == target


def _infer_property_type(prop: dict[str, Any]) -> str:
    if "title" in prop:
        return "title"
    if "number" in prop:
        return "number"
    if "select" in prop:
        return "select"
    if "multi_select" in prop:
        return "multi_select"
    return "unknown"


def _extract_title_text(prop: object) -> str:
    if not isinstance(prop, dict):
        return ""
    title_list = prop.get("title", [])
    if not isinstance(title_list, list):
        return ""
    parts: list[str] = []
    for item in title_list:
        if isinstance(item, dict):
            text = item.get("text")
            if isinstance(text, dict):
                parts.append(text.get("content", ""))
            elif "plain_text" in item:
                parts.append(item.get("plain_text", ""))
    return "".join(parts)
