from __future__ import annotations

from app.config.schema import ProjectConfig
from app.github.client import GitHubClient
from app.github.models import Issue
from app.wave.assembly import (
    WaveAssemblyResult,
    build_wave_issues,
    is_unplanned,
    topological_sort,
)


class WaveReadError(Exception):
    pass


def read_wave(
    client: GitHubClient,
    config: ProjectConfig,
    wave_name: str,
) -> WaveAssemblyResult:
    """Read a wave's issues from GitHub and produce dependency-ordered work list.

    A wave = all milestones sharing ``wave_name`` across the project's repos.
    Re-readable each session (Spec Principle 2).
    """
    all_issues: list[Issue] = []

    for repo_entry in config.repos:
        milestones = client.list_milestones(repo_entry.name)
        matching = [m for m in milestones if m.title == wave_name]

        if not matching:
            continue

        milestone = matching[0]
        issues = client.list_issues(repo_entry.name, milestone.number)
        all_issues.extend(issues)

    if is_unplanned(all_issues):
        return WaveAssemblyResult(ordered_issues=[], unplanned=True)

    wave_issues = build_wave_issues(all_issues)
    ordered = topological_sort(wave_issues)

    return WaveAssemblyResult(ordered_issues=ordered, unplanned=False)
