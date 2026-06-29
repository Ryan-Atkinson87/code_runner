from __future__ import annotations

import pytest

from app.github.models import Issue, Milestone
from app.wave.assembly import (
    DependencyCycleError,
    WaveIssue,
    build_wave_issues,
    is_unplanned,
    parse_dependencies,
    topological_sort,
)


def _issue(
    number: int,
    body: str = "",
    repo: str = "repo-a",
) -> Issue:
    return Issue(
        number=number,
        title=f"Issue #{number}",
        body=body,
        state="open",
        repo=repo,
        milestone=Milestone(number=1, title="Phase 3", state="open"),
    )


class TestParseDependencies:
    def test_single_dependency(self) -> None:
        assert parse_dependencies("Depends on: #5") == [5]

    def test_multiple_dependencies(self) -> None:
        result = parse_dependencies("Depends on: #3, #7, #12")
        assert result == [3, 7, 12]

    def test_deps_shorthand(self) -> None:
        assert parse_dependencies("deps: #1") == [1]

    def test_case_insensitive(self) -> None:
        assert parse_dependencies("depends on: #42") == [42]

    def test_no_dependencies(self) -> None:
        assert parse_dependencies("No dependencies here.") == []

    def test_multiline_body(self) -> None:
        body = "Some description.\n\nDepends on: #10, #20\n\nMore text."
        assert parse_dependencies(body) == [10, 20]

    def test_multiple_depends_lines(self) -> None:
        body = "Depends on: #1\nAlso depends on: #2"
        result = parse_dependencies(body)
        assert 1 in result
        assert 2 in result


class TestBuildWaveIssues:
    def test_converts_issues(self) -> None:
        issues = [
            _issue(1, "No deps."),
            _issue(2, "Depends on: #1"),
        ]
        wave_issues = build_wave_issues(issues)
        assert len(wave_issues) == 2
        assert wave_issues[0].number == 1
        assert wave_issues[0].depends_on == []
        assert wave_issues[1].depends_on == [1]

    def test_preserves_repo(self) -> None:
        issue = _issue(5, repo="backend")
        wave_issues = build_wave_issues([issue])
        assert wave_issues[0].repo == "backend"


class TestTopologicalSort:
    def test_linear_chain(self) -> None:
        issues = [
            WaveIssue(number=3, title="C", repo="r", depends_on=[2]),
            WaveIssue(number=1, title="A", repo="r"),
            WaveIssue(number=2, title="B", repo="r", depends_on=[1]),
        ]
        ordered = topological_sort(issues)
        numbers = [i.number for i in ordered]
        assert numbers == [1, 2, 3]

    def test_independent_issues(self) -> None:
        issues = [
            WaveIssue(number=1, title="A", repo="repo-a"),
            WaveIssue(number=2, title="B", repo="repo-b"),
        ]
        ordered = topological_sort(issues)
        assert len(ordered) == 2
        numbers = {i.number for i in ordered}
        assert numbers == {1, 2}

    def test_diamond_dependency(self) -> None:
        issues = [
            WaveIssue(number=1, title="A", repo="r"),
            WaveIssue(number=2, title="B", repo="r", depends_on=[1]),
            WaveIssue(number=3, title="C", repo="r", depends_on=[1]),
            WaveIssue(
                number=4,
                title="D",
                repo="r",
                depends_on=[2, 3],
            ),
        ]
        ordered = topological_sort(issues)
        numbers = [i.number for i in ordered]
        assert numbers[0] == 1
        assert numbers[-1] == 4
        assert numbers.index(2) < numbers.index(4)
        assert numbers.index(3) < numbers.index(4)

    def test_external_dependency_ignored(self) -> None:
        issues = [
            WaveIssue(
                number=10,
                title="X",
                repo="r",
                depends_on=[99],
            ),
        ]
        ordered = topological_sort(issues)
        assert len(ordered) == 1
        assert ordered[0].number == 10

    def test_cycle_raises(self) -> None:
        issues = [
            WaveIssue(number=1, title="A", repo="r", depends_on=[2]),
            WaveIssue(number=2, title="B", repo="r", depends_on=[1]),
        ]
        with pytest.raises(DependencyCycleError) as exc_info:
            topological_sort(issues)
        assert 1 in exc_info.value.cycle
        assert 2 in exc_info.value.cycle

    def test_three_way_cycle(self) -> None:
        issues = [
            WaveIssue(number=1, title="A", repo="r", depends_on=[3]),
            WaveIssue(number=2, title="B", repo="r", depends_on=[1]),
            WaveIssue(number=3, title="C", repo="r", depends_on=[2]),
        ]
        with pytest.raises(DependencyCycleError):
            topological_sort(issues)


class TestUnplanned:
    def test_empty_issues_is_unplanned(self) -> None:
        assert is_unplanned([]) is True

    def test_issues_present_is_planned(self) -> None:
        assert is_unplanned([_issue(1)]) is False


class TestCrossRepo:
    def test_cross_repo_ordering(self) -> None:
        issues = [
            WaveIssue(number=1, title="Backend", repo="api"),
            WaveIssue(
                number=2,
                title="Frontend",
                repo="ui",
                depends_on=[1],
            ),
        ]
        ordered = topological_sort(issues)
        numbers = [i.number for i in ordered]
        assert numbers.index(1) < numbers.index(2)
