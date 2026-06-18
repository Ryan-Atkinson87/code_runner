from __future__ import annotations

from pathlib import Path

import pytest

from app.config.schema import RepoCommands
from app.gates import GateStatus, run_gates


@pytest.fixture()
def repo_path(tmp_path: Path) -> Path:
    return tmp_path


class TestPassingGates:
    def test_all_pass(self, repo_path: Path) -> None:
        commands = RepoCommands(test="true", lint="true", typecheck="true")
        result = run_gates("test-repo", repo_path, commands)
        assert result.all_passed
        for r in result.results:
            assert r.status == GateStatus.PASSED
            assert r.exit_code == 0

    def test_result_captures_repo_name(self, repo_path: Path) -> None:
        commands = RepoCommands(test="true", lint="true", typecheck="true")
        result = run_gates("my-repo", repo_path, commands)
        assert result.repo_name == "my-repo"

    def test_duration_is_positive(self, repo_path: Path) -> None:
        commands = RepoCommands(test="true")
        result = run_gates("test-repo", repo_path, commands)
        test_result = result.results[0]
        assert test_result.duration_seconds >= 0.0


class TestFailingGates:
    def test_single_failure(self, repo_path: Path) -> None:
        commands = RepoCommands(test="false", lint="true", typecheck="true")
        result = run_gates("test-repo", repo_path, commands)
        assert not result.all_passed
        assert result.results[0].status == GateStatus.FAILED
        assert result.results[0].exit_code != 0

    def test_failure_captures_output(self, repo_path: Path) -> None:
        commands = RepoCommands(
            test="echo 'FAILED: test_foo' && exit 1",
            lint="true",
            typecheck="true",
        )
        result = run_gates("test-repo", repo_path, commands)
        test_result = result.results[0]
        assert test_result.status == GateStatus.FAILED
        assert "FAILED: test_foo" in test_result.stdout

    def test_stderr_captured(self, repo_path: Path) -> None:
        commands = RepoCommands(
            test="echo 'error detail' >&2 && exit 1",
        )
        result = run_gates("test-repo", repo_path, commands)
        test_result = result.results[0]
        assert "error detail" in test_result.stderr


class TestSkippedGates:
    def test_empty_command_skipped(self, repo_path: Path) -> None:
        commands = RepoCommands(test="true", lint="", typecheck="")
        result = run_gates("test-repo", repo_path, commands)
        assert result.results[0].status == GateStatus.PASSED
        assert result.results[1].status == GateStatus.SKIPPED
        assert result.results[2].status == GateStatus.SKIPPED

    def test_skipped_has_no_exit_code(self, repo_path: Path) -> None:
        commands = RepoCommands()
        result = run_gates("test-repo", repo_path, commands)
        for r in result.results:
            assert r.exit_code is None

    def test_all_skipped_counts_as_passed(self, repo_path: Path) -> None:
        commands = RepoCommands()
        result = run_gates("test-repo", repo_path, commands)
        assert result.all_passed


class TestNotEstablished:
    def test_empty_expected_gate_is_not_established(self, repo_path: Path) -> None:
        commands = RepoCommands(test="", lint="", typecheck="")
        result = run_gates(
            "test-repo",
            repo_path,
            commands,
            expected_gates={"test", "lint", "typecheck"},
        )
        for r in result.results:
            assert r.status == GateStatus.NOT_ESTABLISHED

    def test_not_established_does_not_count_as_passed(self, repo_path: Path) -> None:
        commands = RepoCommands(test="", lint="true", typecheck="true")
        result = run_gates(
            "test-repo",
            repo_path,
            commands,
            expected_gates={"test"},
        )
        assert not result.all_passed

    def test_mixed_skipped_and_not_established(self, repo_path: Path) -> None:
        commands = RepoCommands(test="", lint="", typecheck="true")
        result = run_gates(
            "test-repo",
            repo_path,
            commands,
            expected_gates={"test"},
        )
        assert result.results[0].status == GateStatus.NOT_ESTABLISHED
        assert result.results[1].status == GateStatus.SKIPPED
        assert result.results[2].status == GateStatus.PASSED


class TestTimeout:
    def test_command_timeout(self, repo_path: Path) -> None:
        commands = RepoCommands(test="sleep 10")
        result = run_gates("test-repo", repo_path, commands, timeout_seconds=0.5)
        test_result = result.results[0]
        assert test_result.status == GateStatus.TIMED_OUT
        assert test_result.exit_code is None
        assert "timed out" in test_result.stderr.lower()
        assert not result.all_passed


class TestGateRunResultProperties:
    def test_all_passed_with_mix(self, repo_path: Path) -> None:
        commands = RepoCommands(test="true", lint="true", typecheck="")
        result = run_gates("test-repo", repo_path, commands)
        assert result.all_passed

    def test_not_passed_with_failure(self, repo_path: Path) -> None:
        commands = RepoCommands(test="true", lint="false", typecheck="true")
        result = run_gates("test-repo", repo_path, commands)
        assert not result.all_passed

    def test_results_are_in_gate_order(self, repo_path: Path) -> None:
        commands = RepoCommands(test="true", lint="true", typecheck="true")
        result = run_gates("test-repo", repo_path, commands)
        assert [r.name for r in result.results] == ["test", "lint", "typecheck"]
