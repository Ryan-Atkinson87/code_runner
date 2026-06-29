from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.dependencies import require_auth
from app.github.client import GitHubClient
from app.github.errors import GitHubError

router = APIRouter(prefix="/prs", tags=["prs"], dependencies=[Depends(require_auth)])

_github_client: GitHubClient | None = None
_repo_name: str = ""

_CHECKLIST_RE = re.compile(r"^- \[([ xX])\] (.+)$", re.MULTILINE)


def init_prs_deps(client: GitHubClient, repo_name: str) -> None:
    global _github_client, _repo_name
    _github_client = client
    _repo_name = repo_name


def _get_client() -> GitHubClient:
    if _github_client is None:
        raise RuntimeError("GitHubClient not initialised for PRs router")
    return _github_client


class ChecklistItem(BaseModel):
    text: str
    checked: bool


class HandoffPR(BaseModel):
    number: int
    title: str
    body: str
    html_url: str
    head_branch: str
    base_branch: str
    state: str
    checklist: list[ChecklistItem] = Field(default_factory=list)


class PRListResponse(BaseModel):
    prs: list[HandoffPR]


def _extract_checklist(body: str) -> list[ChecklistItem]:
    items: list[ChecklistItem] = []
    for match in _CHECKLIST_RE.finditer(body):
        checked = match.group(1).lower() == "x"
        text = match.group(2).strip()
        items.append(ChecklistItem(text=text, checked=checked))
    return items


@router.get("", response_model=PRListResponse)
async def list_prs(head: str | None = None) -> PRListResponse:
    client = _get_client()
    try:
        prs = client.list_pull_requests(_repo_name, state="open", head=head)
    except GitHubError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"GitHub API error: {exc}",
        ) from exc

    return PRListResponse(
        prs=[
            HandoffPR(
                number=pr.number,
                title=pr.title,
                body=pr.body,
                html_url=pr.html_url,
                head_branch=pr.head_branch,
                base_branch=pr.base_branch,
                state=pr.state,
                checklist=_extract_checklist(pr.body),
            )
            for pr in prs
        ]
    )


@router.get("/{pr_number}", response_model=HandoffPR)
async def get_pr(pr_number: int) -> HandoffPR:
    client = _get_client()
    try:
        pr = client.get_pull_request(_repo_name, pr_number)
    except GitHubError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"GitHub API error: {exc}",
        ) from exc

    return HandoffPR(
        number=pr.number,
        title=pr.title,
        body=pr.body,
        html_url=pr.html_url,
        head_branch=pr.head_branch,
        base_branch=pr.base_branch,
        state=pr.state,
        checklist=_extract_checklist(pr.body),
    )
