from __future__ import annotations

import re
import time
from pathlib import Path

from app.providers.types import AuditRecord

CODING_TOOLS: frozenset[str] = frozenset({"bash", "str_replace_based_edit_tool"})

# .env, .env.local, .env.production — but NOT .env.example
_SECRET_FILE_RE = re.compile(r"\.env(?!\.example)\b")
_CI_WORKFLOW_RE = re.compile(r"\.github/workflows")


class ToolPermissionError(Exception):
    pass


def pre_tool_use_check(
    tool_name: str,
    tool_input: dict[str, object],
    workdir: Path,
) -> None:
    """Validate a tool call is within security bounds (Spec §7.4).

    Raises ToolPermissionError for out-of-bounds operations.
    This is the inner permission layer — the container mount boundary
    and network egress allowlist are the primary defences.
    """
    if tool_name == "bash":
        _check_bash_command(tool_input, workdir)
    elif tool_name == "str_replace_based_edit_tool":
        _check_file_op(tool_input, workdir)


def create_audit_record(
    tool_name: str,
    tool_input: dict[str, object],
    blocked: bool = False,
    block_reason: str = "",
) -> AuditRecord:
    return AuditRecord(
        tool_name=tool_name,
        tool_input=tool_input,
        blocked=blocked,
        block_reason=block_reason,
        timestamp=time.time(),
    )


def _check_bash_command(tool_input: dict[str, object], workdir: Path) -> None:
    command = str(tool_input.get("command", ""))
    if not command:
        return

    if _SECRET_FILE_RE.search(command):
        raise ToolPermissionError(f"bash command references secret files (.env): {command[:200]}")

    if _CI_WORKFLOW_RE.search(command):
        raise ToolPermissionError(f"bash command targets CI/workflow files: {command[:200]}")

    _check_rm_bounds(command, workdir)


def _check_rm_bounds(command: str, workdir: Path) -> None:
    if not re.search(r"\brm\b", command):
        return

    workdir_str = str(workdir.resolve())
    tokens = command.split()
    in_rm = False
    for token in tokens:
        if token == "rm":
            in_rm = True
            continue
        if not in_rm:
            continue
        if token.startswith("-"):
            continue
        if token in ("|", "&&", "||", ";"):
            in_rm = False
            continue

        if token.startswith("/") and not token.startswith(workdir_str):
            raise ToolPermissionError(f"rm targets path outside project directory: {token}")

        if ".." in token:
            try:
                resolved = str((workdir / token).resolve())
            except (ValueError, OSError) as exc:
                raise ToolPermissionError(f"rm targets suspicious path: {token}") from exc
            if not resolved.startswith(workdir_str):
                raise ToolPermissionError(f"rm targets path outside project directory: {token}")


def _check_file_op(tool_input: dict[str, object], workdir: Path) -> None:
    rel_path = str(tool_input.get("path", ""))
    if not rel_path:
        return

    target = (workdir / rel_path).resolve()
    if not target.is_relative_to(workdir.resolve()):
        raise ToolPermissionError(f"file operation outside project directory: {rel_path}")

    if _SECRET_FILE_RE.search(rel_path):
        raise ToolPermissionError(f"file operation on secret file: {rel_path}")

    if _CI_WORKFLOW_RE.search(rel_path):
        raise ToolPermissionError(f"file operation on CI/workflow file: {rel_path}")
