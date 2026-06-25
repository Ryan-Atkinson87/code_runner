from __future__ import annotations

import subprocess
from pathlib import Path

from app.git.errors import GitError, MergeConflictError, PathBoundaryError


class GitRepo:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).resolve()
        if not (self._path / ".git").is_dir():
            raise PathBoundaryError(f"Not a git repository: {self._path}")

    @property
    def path(self) -> Path:
        return self._path

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args],
            cwd=self._path,
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            stderr = result.stderr.strip()
            if self._is_merge_conflict(result):
                raise MergeConflictError(
                    f"Merge conflict: {stderr}",
                    exit_code=result.returncode,
                    stderr=stderr,
                )
            raise GitError(
                f"git {' '.join(args)} failed (exit {result.returncode}): {stderr}",
                exit_code=result.returncode,
                stderr=stderr,
            )
        return result

    @staticmethod
    def _is_merge_conflict(result: subprocess.CompletedProcess[str]) -> bool:
        if result.returncode == 0:
            return False
        combined = result.stdout + result.stderr
        conflict_signals = [
            "CONFLICT",
            "Automatic merge failed",
            "fix conflicts and then commit",
        ]
        return any(signal in combined for signal in conflict_signals)

    def fetch(self, remote: str = "origin", branch: str | None = None) -> None:
        args = ["fetch", remote]
        if branch is not None:
            args.append(branch)
        self._run(*args)

    def create_branch(self, name: str, start_point: str | None = None) -> None:
        args = ["branch", name]
        if start_point is not None:
            args.append(start_point)
        self._run(*args)

    def checkout(self, branch: str) -> None:
        self._run("checkout", branch)

    def create_and_checkout(self, name: str, start_point: str | None = None) -> None:
        args = ["checkout", "-b", name]
        if start_point is not None:
            args.append(start_point)
        self._run(*args)

    def delete_branch(self, name: str, force: bool = False) -> None:
        flag = "-D" if force else "-d"
        self._run("branch", flag, name)

    def merge(self, branch: str, message: str | None = None) -> None:
        args = ["merge", branch, "--no-ff"]
        if message is not None:
            args.extend(["-m", message])
        self._run(*args)

    def abort_merge(self) -> None:
        self._run("merge", "--abort")

    def stage(self, *paths: str) -> None:
        if not paths:
            return
        for p in paths:
            resolved = (self._path / p).resolve()
            if not resolved.is_relative_to(self._path):
                raise PathBoundaryError(f"Path {p} resolves outside repo boundary {self._path}")
        self._run("add", "--", *paths)

    def stage_all(self) -> None:
        self._run("add", "-A")

    def commit(self, message: str) -> str:
        self._run("commit", "-m", message)
        result = self._run("rev-parse", "HEAD")
        return result.stdout.strip()

    def is_dirty(self) -> bool:
        result = self._run("status", "--porcelain")
        return bool(result.stdout.strip())

    def current_branch(self) -> str:
        result = self._run("rev-parse", "--abbrev-ref", "HEAD")
        return result.stdout.strip()

    def branch_exists(self, name: str) -> bool:
        result = self._run("rev-parse", "--verify", f"refs/heads/{name}", check=False)
        return result.returncode == 0

    def commits_between(self, base: str, head: str) -> list[str]:
        result = self._run("log", "--oneline", f"{base}..{head}", "--format=%H")
        lines = result.stdout.strip()
        if not lines:
            return []
        return lines.split("\n")

    def is_merged(self, branch: str, into: str) -> bool:
        result = self._run("branch", "--merged", into)
        merged_branches = [
            line.strip().removeprefix("* ")
            for line in result.stdout.strip().split("\n")
        ]
        return branch in merged_branches

    def diff(self, base: str, head: str) -> str:
        result = self._run("diff", f"{base}...{head}")
        return result.stdout

    def diff_stat(self, base: str, head: str) -> str:
        result = self._run("diff", "--stat", f"{base}...{head}")
        return result.stdout.strip()

    def rebase(self, onto: str) -> None:
        self._run("rebase", onto)

    def rev_parse(self, ref: str) -> str:
        result = self._run("rev-parse", ref)
        return result.stdout.strip()

    def reset_hard(self, ref: str = "HEAD") -> None:
        self._run("reset", "--hard", ref)

    def clean_untracked(self, directories: bool = True) -> None:
        args = ["clean", "-f"]
        if directories:
            args.append("-d")
        self._run(*args)

    def merge_base(self, ref1: str, ref2: str) -> str:
        result = self._run("merge-base", ref1, ref2)
        return result.stdout.strip()

    def was_merged_into(self, branch: str, into: str) -> bool:
        """Check if branch was merged into another via a merge commit.

        Unlike is_merged (reachability only), this confirms a merge commit
        exists whose parent is branch's tip. Used to distinguish an empty
        branch from one that was merged but not yet deleted.
        """
        tip = self.rev_parse(branch)
        result = self._run("log", f"{branch}..{into}", "--merges", "--format=%P")
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            if tip in line.split():
                return True
        return False
