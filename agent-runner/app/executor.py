from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

_BASH_TIMEOUT = 300


async def execute_bash(tool_input: dict[str, object], workdir: Path) -> str:
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


def execute_text_editor(tool_input: dict[str, object], workdir: Path) -> str:
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
