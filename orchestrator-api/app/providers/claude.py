from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path

import anthropic

from app.git.repo import GitRepo
from app.providers.adapter import ProviderAdapter
from app.providers.hooks import ToolPermissionError, create_audit_record, pre_tool_use_check
from app.providers.pricing import calculate_cost
from app.providers.types import (
    AuditRecord,
    EventKind,
    NormalisedEvent,
    SessionOutcome,
    SessionResult,
    SessionRole,
    UsageReport,
)
from app.providers.utils import build_prompt, derive_artifacts

_TOOL_DEFS: dict[str, dict[str, str]] = {
    "bash": {"type": "bash_20250124", "name": "bash"},
    "str_replace_based_edit_tool": {
        "type": "text_editor_20250728",
        "name": "str_replace_based_edit_tool",
    },
}

_MAX_TOKENS = 64_000
_BASH_TIMEOUT = 300


class ClaudeAdapter(ProviderAdapter):
    """Claude provider adapter via the Anthropic Python SDK (Spec §3.1, §3.2).

    Each call to ``run_session`` starts a fresh, stateless session (§4.3).
    Artifacts are derived from git, not from the model's self-report.
    """

    def __init__(self, client: anthropic.AsyncAnthropic) -> None:
        self._client = client

    async def run_session(
        self,
        workdir: Path,
        role: SessionRole,
        model: str,
        allowed_tools: list[str],
        prompt: str,
        context_files: list[Path],
    ) -> SessionResult:
        tools = _build_tools(allowed_tools)
        user_content = build_prompt(prompt, context_files)
        messages: list[dict[str, object]] = [{"role": "user", "content": user_content}]

        events: list[NormalisedEvent] = []
        audit_log: list[AuditRecord] = []
        tokens_in = 0
        tokens_out = 0
        start = time.monotonic()

        repo = GitRepo(workdir)
        head_before = repo.rev_parse("HEAD")

        outcome = SessionOutcome.COMPLETED
        try:
            while True:
                response = await self._call_model(model, messages, tools)

                events.extend(_normalise_content(response.content))
                tokens_in += response.usage.input_tokens
                tokens_out += response.usage.output_tokens

                if response.stop_reason != "tool_use":
                    outcome = _map_stop_reason(response.stop_reason)
                    break

                tool_blocks = [b for b in response.content if b.type == "tool_use"]
                messages.append({"role": "assistant", "content": response.content})
                tool_results, new_audit = await _execute_tools(tool_blocks, workdir)
                events.extend(_tool_result_events(tool_blocks, tool_results))
                audit_log.extend(new_audit)
                messages.append({"role": "user", "content": tool_results})

        except (anthropic.APIError, anthropic.APIConnectionError):
            outcome = SessionOutcome.ERROR
        except TimeoutError:
            outcome = SessionOutcome.ERROR

        artifacts = await derive_artifacts(repo, head_before)

        return SessionResult(
            events=events,
            usage=UsageReport(
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=calculate_cost(model, tokens_in, tokens_out),
                model=model,
                duration_seconds=time.monotonic() - start,
            ),
            outcome=outcome,
            artifacts=artifacts,
            audit_log=audit_log,
        )

    async def _call_model(
        self,
        model: str,
        messages: list[dict[str, object]],
        tools: list[dict[str, str]],
    ) -> anthropic.types.Message:
        if tools:
            async with self._client.messages.stream(
                model=model,
                max_tokens=_MAX_TOKENS,
                messages=messages,  # type: ignore[arg-type]
                tools=tools,  # type: ignore[arg-type]
            ) as stream:
                return await stream.get_final_message()
        async with self._client.messages.stream(
            model=model,
            max_tokens=_MAX_TOKENS,
            messages=messages,  # type: ignore[arg-type]
        ) as stream:
            return await stream.get_final_message()


def _build_tools(allowed_tools: list[str]) -> list[dict[str, str]]:
    return [_TOOL_DEFS[name] for name in allowed_tools if name in _TOOL_DEFS]


def _normalise_content(
    content: list[anthropic.types.ContentBlock],
) -> list[NormalisedEvent]:
    events: list[NormalisedEvent] = []
    now = time.time()
    for block in content:
        if block.type == "text":
            events.append(NormalisedEvent(kind=EventKind.OUTPUT, content=block.text, timestamp=now))
        elif block.type == "thinking":
            events.append(
                NormalisedEvent(kind=EventKind.REASONING, content=block.thinking, timestamp=now)
            )
        elif block.type == "tool_use":
            events.append(
                NormalisedEvent(
                    kind=EventKind.TOOL_CALL,
                    tool_name=block.name,
                    tool_input=json.dumps(block.input),
                    timestamp=now,
                )
            )
    return events


def _tool_result_events(
    tool_blocks: list[anthropic.types.ToolUseBlock],
    tool_results: list[dict[str, object]],
) -> list[NormalisedEvent]:
    events: list[NormalisedEvent] = []
    now = time.time()
    for block, result in zip(tool_blocks, tool_results, strict=True):
        content = result.get("content", "")
        events.append(
            NormalisedEvent(
                kind=EventKind.TOOL_RESULT,
                tool_name=block.name,
                content=str(content),
                timestamp=now,
            )
        )
    return events


def _map_stop_reason(stop_reason: str | None) -> SessionOutcome:
    if stop_reason == "refusal":
        return SessionOutcome.BLOCKED
    if stop_reason in ("end_turn", "max_tokens", "stop_sequence", None):
        return SessionOutcome.COMPLETED
    return SessionOutcome.ERROR


async def _execute_tools(
    tool_blocks: list[anthropic.types.ToolUseBlock],
    workdir: Path,
) -> tuple[list[dict[str, object]], list[AuditRecord]]:
    results: list[dict[str, object]] = []
    audit: list[AuditRecord] = []
    for block in tool_blocks:
        tool_input = block.input if isinstance(block.input, dict) else {}

        try:
            pre_tool_use_check(block.name, tool_input, workdir)
        except ToolPermissionError as exc:
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"Permission denied: {exc}",
                    "is_error": True,
                }
            )
            audit.append(
                create_audit_record(block.name, tool_input, blocked=True, block_reason=str(exc))
            )
            continue

        try:
            if block.name == "bash":
                output = await _execute_bash(tool_input, workdir)
            elif block.name == "str_replace_based_edit_tool":
                output = _execute_text_editor(tool_input, workdir)
            else:
                output = f"Unknown tool: {block.name}"
        except Exception as exc:
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"Error: {exc}",
                    "is_error": True,
                }
            )
            audit.append(create_audit_record(block.name, tool_input))
            continue

        results.append(
            {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
            }
        )
        audit.append(create_audit_record(block.name, tool_input))
    return results, audit


async def _execute_bash(tool_input: dict[str, object], workdir: Path) -> str:
    if tool_input.get("restart"):
        return "Shell session restarted."
    command = str(tool_input.get("command", ""))
    result = await asyncio.to_thread(
        subprocess.run,
        ["bash", "-c", command],
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=_BASH_TIMEOUT,
    )
    output = result.stdout
    if result.stderr:
        output = output + result.stderr if output else result.stderr
    return output or "(no output)"


def _execute_text_editor(tool_input: dict[str, object], workdir: Path) -> str:
    command = str(tool_input.get("command", ""))
    rel_path = str(tool_input.get("path", ""))
    target = (workdir / rel_path).resolve()
    if not target.is_relative_to(workdir.resolve()):
        return f"Error: path {rel_path} resolves outside working directory"

    if command == "view":
        view_range = tool_input.get("view_range")
        if target.is_dir():
            return "\n".join(str(f.relative_to(workdir)) for f in sorted(target.iterdir()))
        text = target.read_text(encoding="utf-8")
        if isinstance(view_range, list) and len(view_range) == 2:
            lines = text.split("\n")
            start = int(str(view_range[0])) - 1
            end = int(str(view_range[1]))
            return "\n".join(lines[start:end])
        return text

    if command == "create":
        file_text = str(tool_input.get("file_text", ""))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file_text, encoding="utf-8")
        return f"Created {rel_path}"

    if command == "str_replace":
        old_str = str(tool_input.get("old_str", ""))
        new_str = str(tool_input.get("new_str", ""))
        content = target.read_text(encoding="utf-8")
        count = content.count(old_str)
        if count == 0:
            return f"Error: old_str not found in {rel_path}"
        if count > 1:
            return f"Error: old_str found {count} times in {rel_path}, expected 1"
        target.write_text(content.replace(old_str, new_str, 1), encoding="utf-8")
        return f"Replaced in {rel_path}"

    if command == "insert":
        insert_line = int(str(tool_input.get("insert_line", 0)))
        insert_text = str(tool_input.get("insert_text", ""))
        content = target.read_text(encoding="utf-8")
        lines = content.split("\n")
        lines.insert(insert_line, insert_text)
        target.write_text("\n".join(lines), encoding="utf-8")
        return f"Inserted at line {insert_line} in {rel_path}"

    return f"Unknown command: {command}"
