from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    body: str
    html_url: str
    head_branch: str
    base_branch: str
    state: str
