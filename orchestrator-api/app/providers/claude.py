from __future__ import annotations

import json
import time
from pathlib import Path

import anthropic

from app.git.repo import GitRepo
from app.providers.adapter import ProviderAdapter
from app.providers.executor_client import ExecutorClient, ExecutorError, ToolExecutor
from app.providers.hooks import create_audit_record
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
_PERMISSION_DENIED_PREFIX = "Permission denied: "


class ClaudeAdapter(ProviderAdapter):
    """Claude provider adapter via the Anthropic Python SDK (Spec §3.1, §3.2).

    Each call to ``run_session`` starts a fresh, stateless session (§4.3).
    Artifacts are derived from git, not from the model's self-report. Tool calls run
    inside the agent-runner executor (Spec §7.1/§7.2), not in this process — see
    ``ExecutorClient``.
    """

    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        executor: ToolExecutor | None = None,
    ) -> None:
        self._client = client
        self._executor = executor or ExecutorClient.from_env()

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
                tool_results, new_audit = await _execute_tools(tool_blocks, self._executor)
                events.extend(_tool_result_events(tool_blocks, tool_results))
                audit_log.extend(new_audit)
                messages.append({"role": "user", "content": tool_results})

        except (anthropic.APIError, anthropic.APIConnectionError, ExecutorError):
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
    executor: ToolExecutor,
) -> tuple[list[dict[str, object]], list[AuditRecord]]:
    """Run each tool call through the agent-runner executor RPC.

    The executor enforces ``pre_tool_use_check`` itself and always answers with a
    normal 200 response (Spec §7.4) — a "Permission denied: ..."/"Error: ..." string is
    a tool-level outcome, not an RPC failure. ``ExecutorError`` (raised only for an
    unreachable/timed-out executor) is deliberately left to propagate to ``run_session``,
    where it maps to ``SessionOutcome.ERROR`` alongside ``anthropic.APIError``.
    """
    results: list[dict[str, object]] = []
    audit: list[AuditRecord] = []
    for block in tool_blocks:
        tool_input = block.input if isinstance(block.input, dict) else {}

        if block.name == "bash":
            output = await executor.bash(tool_input)
        elif block.name == "str_replace_based_edit_tool":
            output = await executor.text_editor(tool_input)
        else:
            output = f"Unknown tool: {block.name}"

        blocked = output.startswith(_PERMISSION_DENIED_PREFIX)
        result: dict[str, object] = {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": output,
        }
        if blocked or output.startswith("Error"):
            result["is_error"] = True
        results.append(result)

        block_reason = output.removeprefix(_PERMISSION_DENIED_PREFIX) if blocked else ""
        audit.append(
            create_audit_record(block.name, tool_input, blocked=blocked, block_reason=block_reason)
        )
    return results, audit
