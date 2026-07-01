"""Codex CLI provider adapter (Spec §3.1, §3.2).

Expected JSONL event format (one JSON object per stdout line):
  {"type": "message", "role": "assistant", "content": "..."}
  {"type": "reasoning", "content": "..."}
  {"type": "function_call", "call_id": "...", "name": "...", "arguments": "..."}
  {"type": "function_call_output", "call_id": "...", "output": "..."}
  {"type": "usage", "input_tokens": N, "output_tokens": N}
  {"type": "done", "status": "success"|"error"|"cancelled"}
"""

from __future__ import annotations

import asyncio
import json
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


class CodexAdapter(ProviderAdapter):
    """Codex CLI provider adapter (Spec §3.1, §3.2).

    Invokes the Codex CLI non-interactively with --approval-mode full-auto
    and --output-format json. Each call starts a fresh, stateless session
    (§4.3). Artifacts are derived from git, not the provider's self-report.
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
        cmd = [
            "codex",
            "--approval-mode",
            "full-auto",
            "--output-format",
            "json",
            "--model",
            model,
            full_prompt,
        ]

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
                        content=f"codex: {exc}",
                        timestamp=time.time(),
                    )
                ],
                usage=UsageReport(model=model, duration_seconds=time.monotonic() - start),
            )

        events, usage_raw, outcome = _parse_output(result.stdout)

        if result.returncode != 0 and outcome == SessionOutcome.COMPLETED:
            outcome = SessionOutcome.ERROR

        artifacts = await derive_artifacts(repo, head_before)

        return SessionResult(
            events=events,
            usage=UsageReport(
                tokens_in=usage_raw.get("input_tokens", 0),
                tokens_out=usage_raw.get("output_tokens", 0),
                cost_usd=0.0,
                model=model,
                duration_seconds=time.monotonic() - start,
            ),
            outcome=outcome,
            artifacts=artifacts,
        )


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

        if event_type == "message" and obj.get("role") == "assistant":
            content = str(obj.get("content", ""))
            events.append(
                NormalisedEvent(kind=EventKind.OUTPUT, content=content, timestamp=time.time())
            )
            if _is_blocked(content):
                outcome = SessionOutcome.BLOCKED

        elif event_type == "reasoning":
            content = str(obj.get("content", ""))
            events.append(
                NormalisedEvent(kind=EventKind.REASONING, content=content, timestamp=time.time())
            )

        elif event_type == "function_call":
            events.append(
                NormalisedEvent(
                    kind=EventKind.TOOL_CALL,
                    tool_name=str(obj.get("name", "")),
                    tool_input=str(obj.get("arguments", "")),
                    timestamp=time.time(),
                )
            )

        elif event_type == "function_call_output":
            events.append(
                NormalisedEvent(
                    kind=EventKind.TOOL_RESULT,
                    tool_name=str(obj.get("name", "")),
                    content=str(obj.get("output", "")),
                    timestamp=time.time(),
                )
            )

        elif event_type == "usage":
            usage_raw["input_tokens"] = int(obj.get("input_tokens", 0))
            usage_raw["output_tokens"] = int(obj.get("output_tokens", 0))

        elif event_type == "done":
            status = str(obj.get("status", "success"))
            outcome = _map_status(status)

    return events, usage_raw, outcome


def _map_status(status: str) -> SessionOutcome:
    if status == "success":
        return SessionOutcome.COMPLETED
    if status == "cancelled":
        return SessionOutcome.BLOCKED
    return SessionOutcome.ERROR


def _is_blocked(content: str) -> bool:
    lowered = content.lower()
    return any(phrase in lowered for phrase in _BLOCKED_PHRASES)


