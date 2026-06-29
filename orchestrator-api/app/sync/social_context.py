from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.config.schema import ProjectConfig
from app.github.client import GitHubClient
from app.github.models import Issue, Milestone
from app.notion.client import NotionClient
from app.notion.errors import NotionError

logger = logging.getLogger(__name__)


class SocialContextError(Exception):
    pass


@dataclass(frozen=True)
class SocialContextResult:
    success: bool
    error: str = ""


@dataclass(frozen=True)
class WaveContext:
    wave_name: str
    closed_issues: list[Issue] = field(default_factory=list)
    open_issues: list[Issue] = field(default_factory=list)
    next_milestone: Milestone | None = None


class SocialContextUpdater:
    """Updates the Social Media Context Notion page at every wave hand-off (§5.4 step 6)."""

    def __init__(
        self,
        github: GitHubClient,
        notion: NotionClient,
        config: ProjectConfig,
    ) -> None:
        self._github = github
        self._notion = notion
        self._config = config

    def update(self, wave_name: str) -> SocialContextResult:
        notion_cfg = self._config.integrations.notion
        if notion_cfg is None or not notion_cfg.social_context_page:
            raise SocialContextError(
                "Notion integration not configured: "
                "integrations.notion.social_context_page is required"
            )

        try:
            context = self._build_wave_context(wave_name)
            blocks = _render_blocks(context)
            self._notion.replace_block_children(notion_cfg.social_context_page, blocks)
            logger.info("Social Media Context page updated for wave %r", wave_name)
            return SocialContextResult(success=True)
        except NotionError as exc:
            msg = f"Social Context update failed: {exc}"
            logger.error(msg)
            return SocialContextResult(success=False, error=msg)

    def _build_wave_context(self, wave_name: str) -> WaveContext:
        closed: list[Issue] = []
        open_issues: list[Issue] = []
        next_milestone: Milestone | None = None

        for repo_entry in self._config.repos:
            milestones = self._github.list_milestones(repo_entry.name, state="all")
            matching = [m for m in milestones if m.title == wave_name]

            if matching:
                milestone = matching[0]
                closed.extend(
                    self._github.list_issues(repo_entry.name, milestone.number, state="closed")
                )
                open_issues.extend(
                    self._github.list_issues(repo_entry.name, milestone.number, state="open")
                )

            open_milestones = [m for m in milestones if m.state == "open"]
            future = [m for m in open_milestones if m.title != wave_name]
            if future and next_milestone is None:
                future.sort(key=lambda m: m.number)
                next_milestone = future[0]

        return WaveContext(
            wave_name=wave_name,
            closed_issues=closed,
            open_issues=open_issues,
            next_milestone=next_milestone,
        )


def _render_blocks(context: WaveContext) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []

    blocks.append(_heading_block("Current Status"))

    if context.open_issues:
        status = (
            f'Wave "{context.wave_name}" is in progress. '
            f"{len(context.closed_issues)} issue(s) completed, "
            f"{len(context.open_issues)} remaining."
        )
    else:
        count = len(context.closed_issues)
        status = f'Wave "{context.wave_name}" is complete. All {count} issue(s) delivered.'

    blocks.append(_paragraph_block(status))

    blocks.append(_heading_block("Recent Milestones"))

    if context.closed_issues:
        for issue in context.closed_issues:
            blocks.append(_bulleted_list_block(f"#{issue.number} {issue.title}"))
    else:
        blocks.append(_paragraph_block("No issues completed yet in this wave."))

    blocks.append(_heading_block("What's Coming Next"))

    if context.next_milestone:
        blocks.append(_paragraph_block(f"Next up: {context.next_milestone.title}."))
    else:
        blocks.append(_paragraph_block("No upcoming milestones scheduled."))

    return blocks


def _heading_block(text: str) -> dict[str, Any]:
    return {
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
        },
    }


def _paragraph_block(text: str) -> dict[str, Any]:
    return {
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
        },
    }


def _bulleted_list_block(text: str) -> dict[str, Any]:
    return {
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
        },
    }
