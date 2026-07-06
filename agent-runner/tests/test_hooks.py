from __future__ import annotations

from pathlib import Path

import pytest

from app.hooks import ToolPermissionError, pre_tool_use_check


class TestBashChecks:
    def test_allows_normal_command(self, tmp_path: Path) -> None:
        pre_tool_use_check("bash", {"command": "echo hi"}, tmp_path)

    def test_blocks_env_file_read(self, tmp_path: Path) -> None:
        with pytest.raises(ToolPermissionError, match="secret"):
            pre_tool_use_check("bash", {"command": "cat .env"}, tmp_path)

    def test_allows_env_example(self, tmp_path: Path) -> None:
        pre_tool_use_check("bash", {"command": "cat .env.example"}, tmp_path)

    def test_blocks_ci_workflow_edit(self, tmp_path: Path) -> None:
        with pytest.raises(ToolPermissionError, match="CI/workflow"):
            pre_tool_use_check("bash", {"command": "cat .github/workflows/ci.yml"}, tmp_path)

    def test_blocks_rm_outside_workdir(self, tmp_path: Path) -> None:
        with pytest.raises(ToolPermissionError, match="outside"):
            pre_tool_use_check("bash", {"command": "rm /etc/passwd"}, tmp_path)

    def test_blocks_rm_parent_traversal(self, tmp_path: Path) -> None:
        with pytest.raises(ToolPermissionError, match="outside"):
            pre_tool_use_check("bash", {"command": "rm ../../secrets.txt"}, tmp_path)

    def test_allows_rm_inside_workdir(self, tmp_path: Path) -> None:
        pre_tool_use_check("bash", {"command": "rm somefile.txt"}, tmp_path)

    def test_empty_command_noop(self, tmp_path: Path) -> None:
        pre_tool_use_check("bash", {}, tmp_path)


class TestFileOpChecks:
    def test_allows_normal_path(self, tmp_path: Path) -> None:
        pre_tool_use_check("str_replace_based_edit_tool", {"path": "src/app.py"}, tmp_path)

    def test_blocks_path_escape(self, tmp_path: Path) -> None:
        with pytest.raises(ToolPermissionError, match="outside"):
            pre_tool_use_check(
                "str_replace_based_edit_tool", {"path": "../../etc/passwd"}, tmp_path
            )

    def test_blocks_secret_file(self, tmp_path: Path) -> None:
        with pytest.raises(ToolPermissionError, match="secret"):
            pre_tool_use_check("str_replace_based_edit_tool", {"path": ".env"}, tmp_path)

    def test_allows_env_example_file(self, tmp_path: Path) -> None:
        pre_tool_use_check("str_replace_based_edit_tool", {"path": ".env.example"}, tmp_path)

    def test_blocks_ci_workflow_file(self, tmp_path: Path) -> None:
        with pytest.raises(ToolPermissionError, match="CI/workflow"):
            pre_tool_use_check(
                "str_replace_based_edit_tool",
                {"path": ".github/workflows/ci.yml"},
                tmp_path,
            )

    def test_empty_path_noop(self, tmp_path: Path) -> None:
        pre_tool_use_check("str_replace_based_edit_tool", {}, tmp_path)


class TestUnknownTool:
    def test_unknown_tool_noop(self, tmp_path: Path) -> None:
        pre_tool_use_check("some_other_tool", {"command": "cat .env"}, tmp_path)
