from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call

from app.gates.runner import GateResult, GateRunResult, GateStatus
from app.github.models import PullRequest
from app.handoff.body import assemble_pr_body, engine_checks_from_gates
from app.handoff.engine import HandoffEngine
from app.handoff.models import HandoffInput, IssueNote, ParkedBlocker


class TestAssemblePrBody:
    def test_summary_section(self) -> None:
        handoff = HandoffInput(
            wave_name="Foundations",
            summary="Scaffold the project and add core infrastructure.",
        )
        body = assemble_pr_body(handoff)
        assert "## Summary" in body
        assert "Scaffold the project and add core infrastructure." in body

    def test_issue_notes_use_issue_colon_format(self) -> None:
        handoff = HandoffInput(
            wave_name="Wave 1",
            summary="Done.",
            issue_notes=[
                IssueNote(number=1, summary="Scaffold project"),
                IssueNote(number=2, summary="Add auth"),
            ],
        )
        body = assemble_pr_body(handoff)
        assert "- Issue: #1 — Scaffold project" in body
        assert "- Issue: #2 — Add auth" in body
        assert "Closes" not in body

    def test_engine_checks_are_pre_ticked(self) -> None:
        handoff = HandoffInput(
            wave_name="Wave 1",
            summary="Done.",
            engine_checks=["Tests pass", "Lint clean", "Typecheck clean"],
        )
        body = assemble_pr_body(handoff)
        assert "## Engine-verified checks" in body
        assert "- [x] Tests pass" in body
        assert "- [x] Lint clean" in body
        assert "- [x] Typecheck clean" in body

    def test_human_checks_are_open_boxes(self) -> None:
        handoff = HandoffInput(
            wave_name="Wave 1",
            summary="Done.",
            human_checks=["Visual layout", "Responsive breakpoints"],
        )
        body = assemble_pr_body(handoff)
        assert "## Human review checklist" in body
        assert "- [ ] Visual layout" in body
        assert "- [ ] Responsive breakpoints" in body

    def test_human_checks_omitted_when_empty(self) -> None:
        handoff = HandoffInput(
            wave_name="Wave 1",
            summary="Done.",
            human_checks=[],
        )
        body = assemble_pr_body(handoff)
        assert "Human review checklist" not in body

    def test_parked_blockers_section(self) -> None:
        handoff = HandoffInput(
            wave_name="Wave 1",
            summary="Done.",
            parked_blockers=[
                ParkedBlocker(issue_number=5, reason="Needs API key not yet provisioned"),
                ParkedBlocker(issue_number=8, reason="Spec ambiguity on auth flow"),
            ],
        )
        body = assemble_pr_body(handoff)
        assert "## Parked blockers" in body
        assert "- **#5:** Needs API key not yet provisioned" in body
        assert "- **#8:** Spec ambiguity on auth flow" in body

    def test_parked_blockers_omitted_when_empty(self) -> None:
        handoff = HandoffInput(
            wave_name="Wave 1",
            summary="Done.",
            parked_blockers=[],
        )
        body = assemble_pr_body(handoff)
        assert "Parked blockers" not in body

    def test_ci_note_always_present(self) -> None:
        handoff = HandoffInput(wave_name="Wave 1", summary="Done.")
        body = assemble_pr_body(handoff)
        assert "> CI must pass before merging." in body

    def test_full_body_with_all_sections(self) -> None:
        handoff = HandoffInput(
            wave_name="Git/PR engine",
            summary="Implemented the git and PR engine.",
            issue_notes=[
                IssueNote(number=9, summary="Git wrapper"),
                IssueNote(number=10, summary="Agent branch lifecycle"),
            ],
            engine_checks=["Tests pass", "Lint clean"],
            human_checks=["Visual layout"],
            parked_blockers=[ParkedBlocker(issue_number=15, reason="Needs design review")],
        )
        body = assemble_pr_body(handoff)

        sections = body.split("\n\n## ")
        headings = [s.split("\n")[0] for s in sections]
        assert "Summary" in headings[0]
        assert "Issues" in headings[1]
        assert "Engine-verified checks" in headings[2]
        assert "Human review checklist" in headings[3]

    def test_issue_notes_omitted_when_empty(self) -> None:
        handoff = HandoffInput(wave_name="Wave 1", summary="Done.", issue_notes=[])
        body = assemble_pr_body(handoff)
        assert "## Issues" not in body

    def test_engine_checks_omitted_when_empty(self) -> None:
        handoff = HandoffInput(wave_name="Wave 1", summary="Done.", engine_checks=[])
        body = assemble_pr_body(handoff)
        assert "Engine-verified checks" not in body


class TestEngineChecksFromGates:
    def _gate(self, name: str, status: GateStatus = GateStatus.PASSED) -> GateResult:
        return GateResult(
            name=name,
            status=status,
            exit_code=0 if status == GateStatus.PASSED else 1,
            stdout="",
            stderr="",
            duration_seconds=1.0,
        )

    def test_passed_gates_included(self) -> None:
        results = [
            GateRunResult(
                repo_name="orchestrator-api",
                results=(
                    self._gate("test"),
                    self._gate("lint"),
                    self._gate("typecheck"),
                ),
            )
        ]
        checks = engine_checks_from_gates(results)
        assert checks == ["Tests pass", "Lint clean", "Typecheck clean"]

    def test_failed_gates_excluded(self) -> None:
        results = [
            GateRunResult(
                repo_name="orchestrator-api",
                results=(
                    self._gate("test"),
                    self._gate("lint", GateStatus.FAILED),
                    self._gate("typecheck"),
                ),
            )
        ]
        checks = engine_checks_from_gates(results)
        assert "Lint clean" not in checks
        assert "Tests pass" in checks

    def test_skipped_gates_excluded(self) -> None:
        results = [
            GateRunResult(
                repo_name="orchestrator-api",
                results=(self._gate("test", GateStatus.SKIPPED),),
            )
        ]
        checks = engine_checks_from_gates(results)
        assert checks == []

    def test_deduplicates_across_repos(self) -> None:
        results = [
            GateRunResult(
                repo_name="repo-a",
                results=(self._gate("test"), self._gate("lint")),
            ),
            GateRunResult(
                repo_name="repo-b",
                results=(self._gate("test"), self._gate("lint")),
            ),
        ]
        checks = engine_checks_from_gates(results)
        assert checks.count("Tests pass") == 1
        assert checks.count("Lint clean") == 1

    def test_empty_results(self) -> None:
        checks = engine_checks_from_gates([])
        assert checks == []


class TestHandoffEngine:
    def _mock_github(self) -> MagicMock:
        github = MagicMock()
        github.create_pull_request.return_value = PullRequest(
            number=42,
            title="Wave: Foundations",
            body="body",
            html_url="https://github.com/org/repo/pull/42",
            head_branch="code-runner/foundations",
            base_branch="dev",
            state="open",
        )
        return github

    def test_push_and_open_pr(self) -> None:
        github = self._mock_github()
        engine = HandoffEngine(github)
        handoff = HandoffInput(
            wave_name="Foundations",
            summary="Initial scaffold.",
            issue_notes=[IssueNote(number=1, summary="Scaffold")],
        )

        pr = engine.push_and_open_pr(
            repo_name="code_runner",
            repo_path=Path("/repos/code_runner"),
            agent_branch="code-runner/foundations",
            integration_branch="dev",
            handoff=handoff,
        )

        github.push_branch.assert_called_once_with(
            Path("/repos/code_runner"), "code-runner/foundations"
        )
        github.create_pull_request.assert_called_once()
        call_kwargs = github.create_pull_request.call_args
        assert call_kwargs.kwargs["repo"] == "code_runner"
        assert call_kwargs.kwargs["head"] == "code-runner/foundations"
        assert call_kwargs.kwargs["base"] == "dev"
        assert "Foundations" in call_kwargs.kwargs["title"]
        assert "Issue: #1" in call_kwargs.kwargs["body"]
        assert pr.number == 42

    def test_push_once_per_call(self) -> None:
        github = self._mock_github()
        engine = HandoffEngine(github)
        handoff = HandoffInput(wave_name="Wave 1", summary="Done.")

        engine.push_and_open_pr(
            repo_name="repo",
            repo_path=Path("/repos/repo"),
            agent_branch="code-runner/wave-1",
            integration_branch="dev",
            handoff=handoff,
        )

        assert github.push_branch.call_count == 1

    def test_pr_body_includes_all_sections(self) -> None:
        github = self._mock_github()
        engine = HandoffEngine(github)
        handoff = HandoffInput(
            wave_name="Wave 1",
            summary="Everything.",
            issue_notes=[IssueNote(number=1, summary="First")],
            engine_checks=["Tests pass"],
            human_checks=["Visual layout"],
            parked_blockers=[ParkedBlocker(issue_number=5, reason="Blocked")],
        )

        engine.push_and_open_pr(
            repo_name="repo",
            repo_path=Path("/repos/repo"),
            agent_branch="code-runner/wave-1",
            integration_branch="dev",
            handoff=handoff,
        )

        body = github.create_pull_request.call_args.kwargs["body"]
        assert "## Summary" in body
        assert "## Issues" in body
        assert "## Engine-verified checks" in body
        assert "## Human review checklist" in body
        assert "## Parked blockers" in body
        assert "> CI must pass before merging." in body

    def test_cleanup_after_merge(self) -> None:
        github = self._mock_github()
        engine = HandoffEngine(github)

        engine.cleanup_after_merge(
            repo_path=Path("/repos/repo"),
            agent_branch="code-runner/wave-1",
        )

        github.delete_remote_branch.assert_called_once_with(
            Path("/repos/repo"), "code-runner/wave-1"
        )

    def test_multiple_repos_push_independently(self) -> None:
        github = self._mock_github()
        engine = HandoffEngine(github)
        handoff = HandoffInput(wave_name="Wave 1", summary="Done.")

        engine.push_and_open_pr(
            repo_name="repo-a",
            repo_path=Path("/repos/repo-a"),
            agent_branch="code-runner/wave-1",
            integration_branch="dev",
            handoff=handoff,
        )
        engine.push_and_open_pr(
            repo_name="repo-b",
            repo_path=Path("/repos/repo-b"),
            agent_branch="code-runner/wave-1",
            integration_branch="dev",
            handoff=handoff,
        )

        assert github.push_branch.call_count == 2
        push_calls = github.push_branch.call_args_list
        assert push_calls[0] == call(Path("/repos/repo-a"), "code-runner/wave-1")
        assert push_calls[1] == call(Path("/repos/repo-b"), "code-runner/wave-1")
