"""Gemini CLI provider adapter (Spec §3.1, §3.2).

Expected JSONL event format (one JSON object per stdout line):
  {"type": "content", "role": "model", "text": "..."}
  {"type": "thought", "text": "..."}
  {"type": "tool_call", "name": "...", "input": {...}}
  {"type": "tool_result", "name": "...", "output": "..."}
  {"type": "usage", "prompt_tokens": N, "candidates_tokens": N}
  {"type": "done", "status": "completed"|"error"|"cancelled"}
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import time
from pathlib import Path

from app.git.repo import GitRepo
from app.providers.adapter import ProviderAdapter
from app.providers.types import (
    EventKind,
    NormalisedEvent,
    SessionOutcome,
    SessionResult,
    SessionRole,
    UsageReport,
)
from app.providers.utils import build_prompt, derive_artifacts

_BLOCKED_PHRASES = (
    "i need human input",
    "i need your input",
    "please clarify",
    "i cannot proceed without",
    "waiting for your response",
)

# Lockdown: flags that MUST be present in every Gemini invocation (Spec §7.4).
# _validate_lockdown raises LockdownError if any are absent — fails closed.
_REQUIRED_LOCKDOWN_FLAGS: tuple[str, ...] = ("--sandbox",)

# Patterns matched against raw tool_call input JSON. Any hit → BLOCKED (Spec §7.5).
_PROHIBITED_CALL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bgit\s+push\b.+--force"),  # force-push long form
    re.compile(r"\bgit\s+push\b.+-f\b"),  # force-push short form
    re.compile(r"\bgit\s+push\b.+\borigin\b.+\b(?:main|dev)\b"),  # push to main/dev
    re.compile(r"\.env(?!\.example)\b"),  # .env secret files
    re.compile(r"\.github/workflows"),  # CI/workflow files
)


class LockdownError(Exception):
    """Raised when lockdown configuration is invalid (Spec §7.4, fails closed)."""


class GeminiAdapter(ProviderAdapter):
    """Gemini CLI provider adapter (Spec §3.1, §3.2).

    Invokes the Gemini CLI headless with -p and --output-format json.
    Each call starts a fresh, stateless session (§4.3). Artifacts are
    derived from git, not the provider's self-report.
    """

    async def run_session(
        self,
        workdir: Path,
        role: SessionRole,
        model: str,
        allowed_tools: list[str],
        prompt: str,
        context_files: list[Path],
    ) -> SessionResult:
        full_prompt = build_prompt(prompt, context_files)
        cmd = _build_lockdown_cmd(model, full_prompt, role)

        try:
            _validate_lockdown(cmd)
        except LockdownError as exc:
            return SessionResult(
                outcome=SessionOutcome.ERROR,
                events=[
                    NormalisedEvent(
                        kind=EventKind.OUTPUT,
                        content=f"Lockdown error: {exc}",
                        timestamp=time.time(),
                    )
                ],
                usage=UsageReport(model=model, duration_seconds=0.0),
            )

        start = time.monotonic()
        repo = GitRepo(workdir)
        head_before = repo.rev_parse("HEAD")

        try:
            result = await asyncio.to_thread(
                subprocess.run,
                cmd,
                cwd=workdir,
                capture_output=True,
                text=True,
            )
        except (OSError, FileNotFoundError) as exc:
            return SessionResult(
                outcome=SessionOutcome.ERROR,
                events=[
                    NormalisedEvent(
                        kind=EventKind.OUTPUT,
                        content=f"gemini: {exc}",
                        timestamp=time.time(),
                    )
                ],
                usage=UsageReport(model=model, duration_seconds=time.monotonic() - start),
            )

        events, usage_raw, outcome = _parse_output(result.stdout)

        if result.returncode != 0 and outcome == SessionOutcome.COMPLETED:
            outcome = SessionOutcome.ERROR

        if outcome == SessionOutcome.COMPLETED:
            outcome = _check_prohibited_ops(events)

        artifacts = await derive_artifacts(repo, head_before)

        return SessionResult(
            events=events,
            usage=UsageReport(
                tokens_in=usage_raw.get("prompt_tokens", 0),
                tokens_out=usage_raw.get("candidates_tokens", 0),
                cost_usd=0.0,
                model=model,
                duration_seconds=time.monotonic() - start,
            ),
            outcome=outcome,
            artifacts=artifacts,
        )


def _build_lockdown_cmd(model: str, full_prompt: str, role: SessionRole) -> list[str]:
    cmd = [
        "gemini",
        "--sandbox",
        "-p",
        full_prompt,
        "--output-format",
        "json",
        "--model",
        model,
    ]
    if role == SessionRole.ORCHESTRATOR:
        cmd.insert(2, "--readonly")
    return cmd


def _validate_lockdown(cmd: list[str]) -> None:
    for flag in _REQUIRED_LOCKDOWN_FLAGS:
        if flag not in cmd:
            raise LockdownError(f"Lockdown flag '{flag}' absent — refusing to run unsandboxed")


def _check_prohibited_ops(events: list[NormalisedEvent]) -> SessionOutcome:
    for event in events:
        if event.kind != EventKind.TOOL_CALL:
            continue
        haystack = event.tool_input or ""
        for pattern in _PROHIBITED_CALL_PATTERNS:
            if pattern.search(haystack):
                return SessionOutcome.BLOCKED
    return SessionOutcome.COMPLETED


def _parse_output(
    output: str,
) -> tuple[list[NormalisedEvent], dict[str, int], SessionOutcome]:
    events: list[NormalisedEvent] = []
    usage_raw: dict[str, int] = {}
    outcome = SessionOutcome.COMPLETED

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_type = obj.get("type", "")

        if event_type == "content" and obj.get("role") == "model":
            content = str(obj.get("text", ""))
            events.append(
                NormalisedEvent(kind=EventKind.OUTPUT, content=content, timestamp=time.time())
            )
            if _is_blocked(content):
                outcome = SessionOutcome.BLOCKED

        elif event_type == "thought":
            content = str(obj.get("text", ""))
            events.append(
                NormalisedEvent(kind=EventKind.REASONING, content=content, timestamp=time.time())
            )

        elif event_type == "tool_call":
            tool_input = obj.get("input", {})
            events.append(
                NormalisedEvent(
                    kind=EventKind.TOOL_CALL,
                    tool_name=str(obj.get("name", "")),
                    tool_input=json.dumps(tool_input),
                    timestamp=time.time(),
                )
            )

        elif event_type == "tool_result":
            events.append(
                NormalisedEvent(
                    kind=EventKind.TOOL_RESULT,
                    tool_name=str(obj.get("name", "")),
                    content=str(obj.get("output", "")),
                    timestamp=time.time(),
                )
            )

        elif event_type == "usage":
            usage_raw["prompt_tokens"] = int(obj.get("prompt_tokens", 0))
            usage_raw["candidates_tokens"] = int(obj.get("candidates_tokens", 0))

        elif event_type == "done":
            status = str(obj.get("status", "completed"))
            outcome = _map_status(status)

    return events, usage_raw, outcome


def _map_status(status: str) -> SessionOutcome:
    if status == "completed":
        return SessionOutcome.COMPLETED
    if status == "cancelled":
        return SessionOutcome.BLOCKED
    return SessionOutcome.ERROR


def _is_blocked(content: str) -> bool:
    lowered = content.lower()
    return any(phrase in lowered for phrase in _BLOCKED_PHRASES)
