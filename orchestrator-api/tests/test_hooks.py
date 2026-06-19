from __future__ import annotations

from pathlib import Path

import pytest

from app.providers.hooks import (
    CODING_TOOLS,
    ToolPermissionError,
    create_audit_record,
    pre_tool_use_check,
)


class TestCodingTools:
    def test_contains_bash(self) -> None:
        assert "bash" in CODING_TOOLS

    def test_contains_text_editor(self) -> None:
        assert "str_replace_based_edit_tool" in CODING_TOOLS

    def test_nothing_else(self) -> None:
        assert len(CODING_TOOLS) == 2


class TestPreToolUseCheckBash:
    def test_blocks_cat_env(self, tmp_path: Path) -> None:
        with pytest.raises(ToolPermissionError, match="secret"):
            pre_tool_use_check("bash", {"command": "cat .env"}, tmp_path)

    def test_blocks_source_env_local(self, tmp_path: Path) -> None:
        with pytest.raises(ToolPermissionError, match="secret"):
            pre_tool_use_check("bash", {"command": "source .env.local"}, tmp_path)

    def test_blocks_head_env_production(self, tmp_path: Path) -> None:
        with pytest.raises(ToolPermissionError, match="secret"):
            pre_tool_use_check("bash", {"command": "head -5 .env.production"}, tmp_path)

    def test_allows_env_example(self, tmp_path: Path) -> None:
        pre_tool_use_check("bash", {"command": "cat .env.example"}, tmp_path)

    def test_allows_echo_to_env_example(self, tmp_path: Path) -> None:
        pre_tool_use_check("bash", {"command": "echo FOO=bar >> .env.example"}, tmp_path)

    def test_blocks_ci_workflow_read(self, tmp_path: Path) -> None:
        with pytest.raises(ToolPermissionError, match="CI/workflow"):
            pre_tool_use_check("bash", {"command": "cat .github/workflows/ci.yml"}, tmp_path)

    def test_blocks_ci_workflow_edit(self, tmp_path: Path) -> None:
        with pytest.raises(ToolPermissionError, match="CI/workflow"):
            pre_tool_use_check(
                "bash",
                {"command": "echo 'step' >> .github/workflows/deploy.yml"},
                tmp_path,
            )

    def test_allows_normal_commands(self, tmp_path: Path) -> None:
        pre_tool_use_check("bash", {"command": "ls -la"}, tmp_path)
        pre_tool_use_check("bash", {"command": "echo hello"}, tmp_path)
        pre_tool_use_check("bash", {"command": "pwd"}, tmp_path)

    def test_allows_dependency_install(self, tmp_path: Path) -> None:
        pre_tool_use_check("bash", {"command": "pip install requests"}, tmp_path)
        pre_tool_use_check("bash", {"command": "npm install express"}, tmp_path)

    def test_allows_test_commands(self, tmp_path: Path) -> None:
        pre_tool_use_check("bash", {"command": "pytest tests/"}, tmp_path)
        pre_tool_use_check("bash", {"command": "npm test"}, tmp_path)

    def test_allows_rm_within_workdir(self, tmp_path: Path) -> None:
        pre_tool_use_check("bash", {"command": "rm -rf dist/"}, tmp_path)
        pre_tool_use_check("bash", {"command": "rm temp.txt"}, tmp_path)

    def test_blocks_rm_absolute_outside_workdir(self, tmp_path: Path) -> None:
        with pytest.raises(ToolPermissionError, match="outside"):
            pre_tool_use_check("bash", {"command": "rm /etc/passwd"}, tmp_path)

    def test_blocks_rm_with_dotdot_escaping(self, tmp_path: Path) -> None:
        with pytest.raises(ToolPermissionError, match="outside"):
            pre_tool_use_check("bash", {"command": "rm ../../etc/passwd"}, tmp_path)

    def test_blocks_rm_rf_root(self, tmp_path: Path) -> None:
        with pytest.raises(ToolPermissionError, match="outside"):
            pre_tool_use_check("bash", {"command": "rm -rf /"}, tmp_path)

    def test_allows_rm_absolute_within_workdir(self, tmp_path: Path) -> None:
        target = tmp_path / "subdir"
        pre_tool_use_check("bash", {"command": f"rm -rf {target}"}, tmp_path)

    def test_empty_command_allowed(self, tmp_path: Path) -> None:
        pre_tool_use_check("bash", {"command": ""}, tmp_path)

    def test_restart_allowed(self, tmp_path: Path) -> None:
        pre_tool_use_check("bash", {"restart": True}, tmp_path)


class TestPreToolUseCheckFileEditor:
    def test_blocks_view_env(self, tmp_path: Path) -> None:
        with pytest.raises(ToolPermissionError, match="secret"):
            pre_tool_use_check(
                "str_replace_based_edit_tool",
                {"path": ".env", "command": "view"},
                tmp_path,
            )

    def test_blocks_edit_env_local(self, tmp_path: Path) -> None:
        with pytest.raises(ToolPermissionError, match="secret"):
            pre_tool_use_check(
                "str_replace_based_edit_tool",
                {"path": ".env.local", "command": "str_replace"},
                tmp_path,
            )

    def test_allows_env_example(self, tmp_path: Path) -> None:
        pre_tool_use_check(
            "str_replace_based_edit_tool",
            {"path": ".env.example", "command": "view"},
            tmp_path,
        )

    def test_blocks_ci_workflow(self, tmp_path: Path) -> None:
        with pytest.raises(ToolPermissionError, match="CI/workflow"):
            pre_tool_use_check(
                "str_replace_based_edit_tool",
                {"path": ".github/workflows/ci.yml", "command": "str_replace"},
                tmp_path,
            )

    def test_blocks_path_traversal(self, tmp_path: Path) -> None:
        with pytest.raises(ToolPermissionError, match="outside"):
            pre_tool_use_check(
                "str_replace_based_edit_tool",
                {"path": "../../../etc/passwd", "command": "view"},
                tmp_path,
            )

    def test_allows_normal_file_ops(self, tmp_path: Path) -> None:
        pre_tool_use_check(
            "str_replace_based_edit_tool",
            {"path": "src/main.py", "command": "view"},
            tmp_path,
        )

    def test_empty_path_allowed(self, tmp_path: Path) -> None:
        pre_tool_use_check(
            "str_replace_based_edit_tool",
            {"path": "", "command": "view"},
            tmp_path,
        )


class TestCreateAuditRecord:
    def test_normal_record(self) -> None:
        record = create_audit_record("bash", {"command": "ls"})
        assert record.tool_name == "bash"
        assert record.blocked is False
        assert record.block_reason == ""
        assert record.timestamp > 0

    def test_blocked_record(self) -> None:
        record = create_audit_record(
            "bash",
            {"command": "cat .env"},
            blocked=True,
            block_reason="secret file access",
        )
        assert record.blocked is True
        assert "secret" in record.block_reason

    def test_preserves_tool_input(self) -> None:
        tool_input: dict[str, object] = {"command": "echo hi", "timeout": 30}
        record = create_audit_record("bash", tool_input)
        assert record.tool_input == tool_input


class TestPreToolUseUnknownTool:
    def test_unknown_tool_passes(self, tmp_path: Path) -> None:
        pre_tool_use_check("unknown_tool", {"arg": "value"}, tmp_path)
