from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from app.git.repo import GitRepo


def build_prompt(prompt: str, context_files: list[Path]) -> str:
    parts = [prompt]
    for path in context_files:
        if path.exists():
            parts.append(f"\n\n--- {path.name} ---\n{path.read_text(encoding='utf-8')}")
    return "\n".join(parts)


async def derive_artifacts(repo: GitRepo, head_before: str) -> list[str]:
    changed: set[str] = set()

    def run(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, cwd=repo.path, capture_output=True, text=True)

    result = await asyncio.to_thread(run, ["git", "diff", "--name-only"])
    if result.stdout.strip():
        changed.update(result.stdout.strip().split("\n"))

    result = await asyncio.to_thread(run, ["git", "diff", "--cached", "--name-only"])
    if result.stdout.strip():
        changed.update(result.stdout.strip().split("\n"))

    head_now = repo.rev_parse("HEAD")
    if head_now != head_before:
        result = await asyncio.to_thread(
            run, ["git", "diff", "--name-only", head_before, head_now]
        )
        if result.stdout.strip():
            changed.update(result.stdout.strip().split("\n"))

    result = await asyncio.to_thread(run, ["git", "ls-files", "--others", "--exclude-standard"])
    if result.stdout.strip():
        changed.update(result.stdout.strip().split("\n"))

    return sorted(changed)
