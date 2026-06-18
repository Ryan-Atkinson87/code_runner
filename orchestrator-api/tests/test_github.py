from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from app.github import (
    BranchProtectionError,
    GitHubAuthError,
    GitHubClient,
    GitHubError,
    PullRequest,
)


def _mock_response(
    status_code: int = 200,
    json_data: dict | list | None = None,
    text: str = "",
) -> httpx.Response:
    if json_data is not None:
        content = json.dumps(json_data).encode()
        headers = {"content-type": "application/json"}
    else:
        content = text.encode()
        headers = {}
    return httpx.Response(
        status_code=status_code,
        content=content,
        headers=headers,
        request=httpx.Request("GET", "https://api.github.com/test"),
    )


SAMPLE_PR_DATA = {
    "number": 42,
    "title": "Add feature X",
    "body": "Closes #10",
    "html_url": "https://github.com/owner/repo/pull/42",
    "head": {"ref": "feature-branch"},
    "base": {"ref": "dev"},
    "state": "open",
}


@pytest.fixture()
def client() -> GitHubClient:
    return GitHubClient(token="ghp_test_token", owner="test-owner")


class TestAuthHeader:
    def test_bearer_token_in_headers(self, client: GitHubClient) -> None:
        assert client._http.headers["authorization"] == "Bearer ghp_test_token"

    def test_github_api_version_header(self, client: GitHubClient) -> None:
        assert client._http.headers["x-github-api-version"] == "2022-11-28"


class TestAuthErrors:
    def test_401_raises_auth_error(self, client: GitHubClient) -> None:
        with (
            patch.object(
                client._http, "request", return_value=_mock_response(401, text="Bad credentials")
            ),
            pytest.raises(GitHubAuthError, match="Authentication failed"),
        ):
            client.get_pull_request("repo", 1)

    def test_403_raises_auth_error(self, client: GitHubClient) -> None:
        with (
            patch.object(
                client._http, "request", return_value=_mock_response(403, text="Forbidden")
            ),
            pytest.raises(GitHubAuthError),
        ):
            client.get_pull_request("repo", 1)


class TestCreatePullRequest:
    def test_success(self, client: GitHubClient) -> None:
        with patch.object(
            client._http,
            "request",
            return_value=_mock_response(201, json_data=SAMPLE_PR_DATA),
        ):
            pr = client.create_pull_request("repo", "feature-branch", "dev", "Add X", "Body")
            assert isinstance(pr, PullRequest)
            assert pr.number == 42
            assert pr.head_branch == "feature-branch"
            assert pr.base_branch == "dev"

    def test_branch_protection_error(self, client: GitHubClient) -> None:
        error_body = {
            "message": "Validation Failed",
            "errors": [{"message": "Protected branch rules not satisfied"}],
        }
        with (
            patch.object(
                client._http,
                "request",
                return_value=_mock_response(422, json_data=error_body),
            ),
            pytest.raises(BranchProtectionError, match="protection"),
        ):
            client.create_pull_request("repo", "feature", "main", "Title", "Body")

    def test_validation_error_not_protection(self, client: GitHubClient) -> None:
        error_body = {
            "message": "Validation Failed",
            "errors": [{"message": "A pull request already exists"}],
        }
        with patch.object(
            client._http,
            "request",
            return_value=_mock_response(422, json_data=error_body),
        ):
            with pytest.raises(GitHubError) as exc_info:
                client.create_pull_request("repo", "feature", "dev", "Title", "Body")
            assert not isinstance(exc_info.value, BranchProtectionError)


class TestGetPullRequest:
    def test_success(self, client: GitHubClient) -> None:
        with patch.object(
            client._http,
            "request",
            return_value=_mock_response(200, json_data=SAMPLE_PR_DATA),
        ):
            pr = client.get_pull_request("repo", 42)
            assert pr.number == 42
            assert pr.title == "Add feature X"

    def test_not_found(self, client: GitHubClient) -> None:
        with patch.object(
            client._http,
            "request",
            return_value=_mock_response(404, text="Not Found"),
        ):
            with pytest.raises(GitHubError) as exc_info:
                client.get_pull_request("repo", 999)
            assert exc_info.value.status_code == 404


class TestListPullRequests:
    def test_success(self, client: GitHubClient) -> None:
        with patch.object(
            client._http,
            "request",
            return_value=_mock_response(200, json_data=[SAMPLE_PR_DATA]),
        ):
            prs = client.list_pull_requests("repo")
            assert len(prs) == 1
            assert prs[0].number == 42

    def test_empty_list(self, client: GitHubClient) -> None:
        with patch.object(
            client._http,
            "request",
            return_value=_mock_response(200, json_data=[]),
        ):
            prs = client.list_pull_requests("repo")
            assert prs == []


class TestPushBranch:
    def test_refuses_protected_branch(self, client: GitHubClient) -> None:
        for branch in ("main", "master", "dev", "develop"):
            with pytest.raises(BranchProtectionError, match="protected branch"):
                client.push_branch(Path("/fake"), branch)

    def test_success(self, client: GitHubClient, tmp_path: Path) -> None:
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            client.push_branch(tmp_path, "feature-branch")
            mock_run.assert_called_once()

    def test_push_failure(self, client: GitHubClient, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="error: failed to push"
            )
            with pytest.raises(GitHubError, match="Push failed"):
                client.push_branch(tmp_path, "feature-branch")

    def test_push_rejected_by_protection(self, client: GitHubClient, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr="remote: error: GH006: Protected branch update failed",
            )
            with pytest.raises(BranchProtectionError):
                client.push_branch(tmp_path, "feature-branch")


class TestContextManager:
    def test_close(self) -> None:
        client = GitHubClient(token="test", owner="owner")
        client.close()

    def test_context_manager(self) -> None:
        with GitHubClient(token="test", owner="owner") as client:
            assert client._owner == "owner"


class TestPullRequestModel:
    def test_fields(self) -> None:
        pr = PullRequest(
            number=1,
            title="Title",
            body="Body",
            html_url="https://github.com/o/r/pull/1",
            head_branch="feature",
            base_branch="dev",
            state="open",
        )
        assert pr.number == 1
        assert pr.state == "open"
