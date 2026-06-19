from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    body: str
    html_url: str
    head_branch: str
    base_branch: str
    state: str


@dataclass(frozen=True)
class Milestone:
    number: int
    title: str
    state: str


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    body: str
    state: str
    repo: str
    milestone: Milestone | None = None
    labels: list[str] = field(default_factory=list)
