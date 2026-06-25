from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app.config.schema import RepoCommands

GATE_NAMES = ("test", "lint", "typecheck")


def _decode_partial(raw: bytes | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode(errors="replace")
    return raw


class GateStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_ESTABLISHED = "not_established"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class GateResult:
    name: str
    status: GateStatus
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float


@dataclass(frozen=True)
class GateRunResult:
    repo_name: str
    results: tuple[GateResult, ...]

    @property
    def all_passed(self) -> bool:
        return all(r.status in (GateStatus.PASSED, GateStatus.SKIPPED) for r in self.results)


def _run_single_gate(
    name: str,
    command: str,
    cwd: Path,
    *,
    timeout_seconds: float,
    expected: bool,
) -> GateResult:
    if not command.strip():
        status = GateStatus.NOT_ESTABLISHED if expected else GateStatus.SKIPPED
        return GateResult(
            name=name,
            status=status,
            exit_code=None,
            stdout="",
            stderr="",
            duration_seconds=0.0,
        )

    start = time.monotonic()
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        elapsed = time.monotonic() - start
        status = GateStatus.PASSED if result.returncode == 0 else GateStatus.FAILED
        return GateResult(
            name=name,
            status=status,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_seconds=elapsed,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - start
        return GateResult(
            name=name,
            status=GateStatus.TIMED_OUT,
            exit_code=None,
            stdout=_decode_partial(exc.stdout),
            stderr=_decode_partial(exc.stderr) or f"Command timed out after {timeout_seconds}s",
            duration_seconds=elapsed,
        )


def run_gates(
    repo_name: str,
    repo_path: Path,
    commands: RepoCommands,
    *,
    timeout_seconds: float = 300.0,
    expected_gates: set[str] | None = None,
) -> GateRunResult:
    if expected_gates is None:
        expected_gates = set()

    results: list[GateResult] = []
    for gate_name in GATE_NAMES:
        command = getattr(commands, gate_name)
        results.append(
            _run_single_gate(
                gate_name,
                command,
                repo_path,
                timeout_seconds=timeout_seconds,
                expected=gate_name in expected_gates,
            )
        )

    return GateRunResult(repo_name=repo_name, results=tuple(results))
