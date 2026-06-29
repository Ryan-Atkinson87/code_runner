from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import httpx

from app.github.errors import BranchProtectionError, GitHubAuthError, GitHubError
from app.github.models import Issue, Milestone, PullRequest

PROTECTED_BRANCHES = frozenset({"main", "master", "dev", "develop"})


class GitHubClient:
    def __init__(self, token: str, owner: str, api_base: str = "https://api.github.com") -> None:
        self._owner = owner
        self._api_base = api_base
        self._http = httpx.Client(
            base_url=api_base,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = self._http.request(method, path, **kwargs)
        if response.status_code in (401, 403):
            raise GitHubAuthError(
                f"Authentication failed: {response.status_code} {response.text}",
                status_code=response.status_code,
            )
        if response.status_code == 422:
            body = response.json()
            errors = body.get("errors", [])
            for err in errors:
                msg = err.get("message", "")
                if "protected branch" in msg.lower():
                    raise BranchProtectionError(
                        f"Branch protection prevented the operation: {msg}",
                        status_code=422,
                    )
            raise GitHubError(
                f"Validation error: {response.text}",
                status_code=422,
            )
        if response.status_code >= 400:
            raise GitHubError(
                f"GitHub API error: {response.status_code} {response.text}",
                status_code=response.status_code,
            )
        return response

    def push_branch(
        self,
        repo_path: Path,
        branch: str,
        remote: str = "origin",
    ) -> None:
        if branch in PROTECTED_BRANCHES:
            raise BranchProtectionError(f"Refusing to push to protected branch: {branch}")
        result = subprocess.run(
            ["git", "push", remote, branch],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "protected branch" in stderr.lower():
                raise BranchProtectionError(f"Push rejected by branch protection: {stderr}")
            raise GitHubError(f"Push failed: {stderr}")

    def delete_remote_branch(
        self,
        repo_path: Path,
        branch: str,
        remote: str = "origin",
    ) -> None:
        if branch in PROTECTED_BRANCHES:
            raise BranchProtectionError(
                f"Refusing to delete protected branch: {branch}"
            )
        result = subprocess.run(
            ["git", "push", remote, "--delete", branch],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise GitHubError(f"Delete remote branch failed: {result.stderr.strip()}")

    def create_pull_request(
        self,
        repo: str,
        head: str,
        base: str,
        title: str,
        body: str,
    ) -> PullRequest:
        response = self._request(
            "POST",
            f"/repos/{self._owner}/{repo}/pulls",
            json={"head": head, "base": base, "title": title, "body": body},
        )
        return self._parse_pr(response.json())

    def merge_pull_request(self, repo: str, number: int) -> None:
        raise NotImplementedError(
            "Engine must not merge GitHub PRs — human gate (Spec §5.4)"
        )

    def get_pull_request(self, repo: str, number: int) -> PullRequest:
        response = self._request("GET", f"/repos/{self._owner}/{repo}/pulls/{number}")
        return self._parse_pr(response.json())

    def list_pull_requests(
        self,
        repo: str,
        state: str = "open",
        head: str | None = None,
    ) -> list[PullRequest]:
        params: dict[str, str] = {"state": state, "per_page": "30"}
        if head is not None:
            params["head"] = f"{self._owner}:{head}"
        response = self._request(
            "GET",
            f"/repos/{self._owner}/{repo}/pulls",
            params=params,
        )
        return [self._parse_pr(pr) for pr in response.json()]

    def list_milestones(
        self,
        repo: str,
        state: str = "open",
    ) -> list[Milestone]:
        response = self._request(
            "GET",
            f"/repos/{self._owner}/{repo}/milestones",
            params={"state": state, "per_page": "100"},
        )
        return [self._parse_milestone(m) for m in response.json()]

    def list_issues(
        self,
        repo: str,
        milestone_number: int,
        state: str = "open",
    ) -> list[Issue]:
        response = self._request(
            "GET",
            f"/repos/{self._owner}/{repo}/issues",
            params={
                "milestone": str(milestone_number),
                "state": state,
                "per_page": "100",
            },
        )
        items = response.json()
        issues = [
            self._parse_issue(i, repo)
            for i in items
            if "pull_request" not in i
        ]
        return issues

    @staticmethod
    def _parse_milestone(data: dict[str, Any]) -> Milestone:
        return Milestone(
            number=data["number"],
            title=data["title"],
            state=data["state"],
        )

    @staticmethod
    def _parse_issue(data: dict[str, Any], repo: str) -> Issue:
        ms_data = data.get("milestone")
        milestone = (
            Milestone(
                number=ms_data["number"],
                title=ms_data["title"],
                state=ms_data["state"],
            )
            if ms_data
            else None
        )
        return Issue(
            number=data["number"],
            title=data["title"],
            body=data.get("body") or "",
            state=data["state"],
            repo=repo,
            milestone=milestone,
            labels=[lbl["name"] for lbl in data.get("labels", [])],
        )

    @staticmethod
    def _parse_pr(data: dict[str, Any]) -> PullRequest:
        return PullRequest(
            number=data["number"],
            title=data["title"],
            body=data.get("body") or "",
            html_url=data["html_url"],
            head_branch=data["head"]["ref"],
            base_branch=data["base"]["ref"],
            state=data["state"],
        )
