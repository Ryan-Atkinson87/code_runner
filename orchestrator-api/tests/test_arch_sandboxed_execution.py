"""Architectural guard: agent tool execution stays sandboxed in agent-runner.

Capstone of #248: the Claude adapter must never go back to running agent-authored
bash/text-editor tool calls in-process (subprocess or direct filesystem writes) inside
`orchestrator-api` — that was the sandbox gap #256-#259 closed by routing tool calls
through the agent-runner executor RPC (`ExecutorClient`). This test scans app/ source
for any subprocess invocation or raw file-write call outside a small, reviewed allowlist
of deterministic engine operations that are unrelated to agent tool execution, catching a
regression at CI time rather than in review.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "app"

SUBPROCESS_PATTERN = re.compile(r"\bsubprocess\b")
FILE_WRITE_PATTERN = re.compile(
    r"\.write_text\(|\.write_bytes\(|open\([^)]*[\"'](?:w|a|wb|ab|x)b?[\"']"
)

# Deterministic engine operations that legitimately shell out or write files directly —
# none of these execute agent-authored tool calls (bash/text-editor) on the agent's behalf.
SUBPROCESS_ALLOWED = {
    "app/git/repo.py",  # deterministic git operations wrapper (#9)
    "app/github/client.py",  # gh CLI wrapper for hand-off (#13)
    "app/gates/runner.py",  # test/lint/typecheck gate runner (#12)
    "app/providers/utils.py",  # git-diff artifact derivation, shared by all adapters
    "app/providers/codex.py",  # invokes the sandboxed Codex CLI itself (Spec §7.4)
    "app/providers/gemini.py",  # invokes the sandboxed Gemini CLI itself (Spec §7.4)
}

FILE_WRITE_ALLOWED = {
    "app/renderer/base.py",  # writes rendered CLAUDE.md/skill files, not agent tool output
    "app/config/loader.py",  # persists project.yaml, not agent tool output
    "app/observability/capture.py",  # writes gzip log archives
    "app/engine/profile_generation.py",  # persists execution-profile.yaml proposal
}


class TestSandboxedToolExecution:
    def test_no_unreviewed_subprocess_calls(self) -> None:
        violations: list[str] = []

        for py_file in sorted(APP_DIR.rglob("*.py")):
            rel = str(py_file.relative_to(REPO_ROOT))
            if rel in SUBPROCESS_ALLOWED:
                continue

            for lineno, line in enumerate(py_file.read_text().splitlines(), start=1):
                if SUBPROCESS_PATTERN.search(line):
                    violations.append(f"{rel}:{lineno}: {line.strip()}")

        assert violations == [], (
            "Unreviewed subprocess call(s) found in app/ source.\n"
            "Agent tool execution (bash/text-editor) must run inside the sandboxed "
            "agent-runner executor via ExecutorClient (Spec §7.1/§7.2), not in-process.\n"
            "If this is a legitimate deterministic operation, add it to SUBPROCESS_ALLOWED "
            "in this test with a one-line justification.\n\n" + "\n".join(violations)
        )

    def test_no_unreviewed_raw_file_writes(self) -> None:
        violations: list[str] = []

        for py_file in sorted(APP_DIR.rglob("*.py")):
            rel = str(py_file.relative_to(REPO_ROOT))
            if rel in FILE_WRITE_ALLOWED:
                continue

            for lineno, line in enumerate(py_file.read_text().splitlines(), start=1):
                if FILE_WRITE_PATTERN.search(line):
                    violations.append(f"{rel}:{lineno}: {line.strip()}")

        assert violations == [], (
            "Unreviewed raw file-write call(s) found in app/ source.\n"
            "Agent-authored file edits must run inside the sandboxed agent-runner executor "
            "via ExecutorClient.text_editor, not as direct filesystem writes from "
            "orchestrator-api.\n"
            "If this is a legitimate deterministic operation, add it to FILE_WRITE_ALLOWED "
            "in this test with a one-line justification.\n\n" + "\n".join(violations)
        )

    def test_claude_adapter_routes_tool_calls_through_executor(self) -> None:
        claude_source = (APP_DIR / "providers" / "claude.py").read_text()

        assert "ExecutorClient" in claude_source and "ToolExecutor" in claude_source, (
            "ClaudeAdapter must execute bash/text-editor tool calls through the "
            "agent-runner executor (ExecutorClient/ToolExecutor), not in-process."
        )
        assert "subprocess" not in claude_source, (
            "ClaudeAdapter must not import subprocess — tool execution belongs in "
            "agent-runner, reached only via ExecutorClient."
        )
