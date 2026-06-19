from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.github.models import Issue

_DEPENDS_RE = re.compile(
    r"(?:Depends\s+on|deps?):\s*(#\d+(?:\s*,\s*#\d+)*)",
    re.IGNORECASE,
)


class WaveAssemblyError(Exception):
    pass


class DependencyCycleError(WaveAssemblyError):
    def __init__(self, cycle: list[int]) -> None:
        self.cycle = cycle
        nums = " → ".join(f"#{n}" for n in cycle)
        super().__init__(f"Dependency cycle detected: {nums}")


@dataclass(frozen=True)
class WaveIssue:
    number: int
    title: str
    repo: str
    depends_on: list[int] = field(default_factory=list)


def parse_dependencies(body: str) -> list[int]:
    """Extract issue dependencies from ``Depends on: #N`` declarations."""
    deps: list[int] = []
    for match in _DEPENDS_RE.finditer(body):
        refs = match.group(1)
        for num_match in re.finditer(r"#(\d+)", refs):
            deps.append(int(num_match.group(1)))
    return deps


def build_wave_issues(issues: list[Issue]) -> list[WaveIssue]:
    """Convert GitHub issues into WaveIssues with parsed dependencies."""
    return [
        WaveIssue(
            number=issue.number,
            title=issue.title,
            repo=issue.repo,
            depends_on=parse_dependencies(issue.body),
        )
        for issue in issues
    ]


def topological_sort(issues: list[WaveIssue]) -> list[WaveIssue]:
    """Order issues by dependency (algorithmic, no AI — Spec Principle 1).

    Raises DependencyCycleError if a cycle is detected.
    """
    by_number = {i.number: i for i in issues}
    in_wave = set(by_number.keys())

    in_degree: dict[int, int] = {n: 0 for n in in_wave}
    for issue in issues:
        for dep in issue.depends_on:
            if dep in in_wave:
                in_degree[issue.number] = in_degree.get(issue.number, 0) + 1

    queue = sorted(n for n, d in in_degree.items() if d == 0)
    result: list[WaveIssue] = []

    while queue:
        current = queue.pop(0)
        result.append(by_number[current])

        for issue in issues:
            if current in issue.depends_on and issue.number in in_wave:
                in_degree[issue.number] -= 1
                if in_degree[issue.number] == 0:
                    queue.append(issue.number)
        queue.sort()

    if len(result) != len(in_wave):
        remaining = in_wave - {i.number for i in result}
        cycle = _find_cycle(issues, remaining)
        raise DependencyCycleError(cycle)

    return result


def _find_cycle(issues: list[WaveIssue], candidates: set[int]) -> list[int]:
    """Find a cycle among the remaining unresolved issues."""
    by_number = {i.number: i for i in issues if i.number in candidates}

    for start in sorted(candidates):
        cycle = _dfs_cycle(start, by_number, candidates)
        if cycle is not None:
            return cycle

    return sorted(candidates)


def _dfs_cycle(
    node: int,
    by_number: dict[int, WaveIssue],
    candidates: set[int],
    visited: set[int] | None = None,
    path: list[int] | None = None,
) -> list[int] | None:
    if visited is None:
        visited = set()
    if path is None:
        path = []

    if node in visited:
        idx = path.index(node) if node in path else 0
        return path[idx:] + [node]
    if node not in by_number:
        return None

    visited.add(node)
    path.append(node)
    for dep in by_number[node].depends_on:
        if dep in candidates:
            result = _dfs_cycle(dep, by_number, candidates, visited, path)
            if result is not None:
                return result
    path.pop()
    return None


def is_unplanned(issues: list[Issue]) -> bool:
    """Detect an unplanned wave (milestone exists but has no issues)."""
    return len(issues) == 0


@dataclass(frozen=True)
class WaveAssemblyResult:
    ordered_issues: list[WaveIssue]
    unplanned: bool = False
