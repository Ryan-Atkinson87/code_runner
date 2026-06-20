"""Architectural guard: no unauthorised GitHub merge calls.

The engine must not merge PRs — the human gate (Spec §1 Principle 6, §5.4).
GitHubClient.merge_pull_request is a deny-method that raises NotImplementedError.
This test scans app/ source for any merge operation outside that deny-method,
catching violations at CI time rather than in review.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "app"

MERGE_PATTERNS = re.compile(
    r"merge_pull_request"
    r"|gh\s+pr\s+merge"
    r"|/pulls/[^/]+/merge"
    r"|/repos/[^/]+/[^/]+/merges",
)

ALLOWED = {
    "app/github/client.py": re.compile(
        r"def merge_pull_request|"
        r"raise NotImplementedError.*human gate"
    ),
}


class TestNoUnauthorisedMergeCalls:
    def test_app_source_has_no_merge_calls_outside_deny_method(self) -> None:
        violations: list[str] = []

        for py_file in sorted(APP_DIR.rglob("*.py")):
            rel = str(py_file.relative_to(REPO_ROOT))
            allowlist = ALLOWED.get(rel)

            for lineno, line in enumerate(py_file.read_text().splitlines(), start=1):
                if not MERGE_PATTERNS.search(line):
                    continue
                if allowlist and allowlist.search(line):
                    continue
                violations.append(f"{rel}:{lineno}: {line.strip()}")

        assert violations == [], (
            "Unauthorised GitHub merge call(s) found in app/ source.\n"
            "The engine must not merge PRs — human gate (Spec §5.4).\n"
            "The only allowed location is the deny-method in "
            "app/github/client.py.\n\n"
            + "\n".join(violations)
        )

    def test_no_shell_merge_commands_anywhere(self) -> None:
        """No subprocess or shell call to `gh pr merge` in any source file."""
        violations: list[str] = []
        shell_merge = re.compile(r"gh\s+pr\s+merge")

        for py_file in sorted(REPO_ROOT.rglob("*.py")):
            if py_file.name == "test_arch_merge_guard.py":
                continue
            rel = str(py_file.relative_to(REPO_ROOT))
            for lineno, line in enumerate(py_file.read_text().splitlines(), start=1):
                if shell_merge.search(line):
                    violations.append(f"{rel}:{lineno}: {line.strip()}")

        assert violations == [], (
            "Shell-level `gh pr merge` call(s) found.\n"
            "The engine must not merge PRs — human gate (Spec §5.4).\n\n"
            + "\n".join(violations)
        )

    def test_no_github_api_merge_endpoints(self) -> None:
        """No direct GitHub API merge endpoint calls in any source file."""
        violations: list[str] = []
        api_merge = re.compile(r"/pulls/[^/]+/merge|/repos/[^/]+/[^/]+/merges")

        for py_file in sorted(REPO_ROOT.rglob("*.py")):
            if py_file.name == "test_arch_merge_guard.py":
                continue
            rel = str(py_file.relative_to(REPO_ROOT))
            for lineno, line in enumerate(py_file.read_text().splitlines(), start=1):
                if api_merge.search(line):
                    violations.append(f"{rel}:{lineno}: {line.strip()}")

        assert violations == [], (
            "Direct GitHub API merge endpoint call(s) found.\n"
            "The engine must not merge PRs — human gate (Spec §5.4).\n\n"
            + "\n".join(violations)
        )
