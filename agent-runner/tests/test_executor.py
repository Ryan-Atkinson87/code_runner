from __future__ import annotations

from pathlib import Path

import pytest

from app.executor import execute_bash, execute_text_editor


class TestExecuteBash:
    @pytest.mark.asyncio
    async def test_simple_command(self, tmp_path: Path) -> None:
        result = await execute_bash({"command": "echo hello"}, tmp_path)
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_stderr_included(self, tmp_path: Path) -> None:
        result = await execute_bash({"command": "echo err >&2"}, tmp_path)
        assert "err" in result

    @pytest.mark.asyncio
    async def test_restart(self, tmp_path: Path) -> None:
        result = await execute_bash({"restart": True}, tmp_path)
        assert "restarted" in result.lower()

    @pytest.mark.asyncio
    async def test_runs_in_workdir(self, tmp_path: Path) -> None:
        result = await execute_bash({"command": "pwd"}, tmp_path)
        assert str(tmp_path) in result

    @pytest.mark.asyncio
    async def test_no_output(self, tmp_path: Path) -> None:
        result = await execute_bash({"command": "true"}, tmp_path)
        assert result == "(no output)"

    @pytest.mark.asyncio
    async def test_timeout_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess

        import app.executor as executor_module

        monkeypatch.setattr(executor_module, "_BASH_TIMEOUT", 0.01)
        with pytest.raises(subprocess.TimeoutExpired):
            await execute_bash({"command": "sleep 1"}, tmp_path)


class TestExecuteTextEditor:
    def test_view_file(self, tmp_path: Path) -> None:
        (tmp_path / "hello.py").write_text("print('hi')")
        result = execute_text_editor({"command": "view", "path": "hello.py"}, tmp_path)
        assert "print('hi')" in result

    def test_view_directory(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.py").write_text("")
        result = execute_text_editor({"command": "view", "path": "."}, tmp_path)
        assert "a.py" in result
        assert "b.py" in result

    def test_view_range(self, tmp_path: Path) -> None:
        (tmp_path / "hello.py").write_text("one\ntwo\nthree\nfour")
        result = execute_text_editor(
            {"command": "view", "path": "hello.py", "view_range": [2, 3]}, tmp_path
        )
        assert result == "two\nthree"

    def test_create_file(self, tmp_path: Path) -> None:
        result = execute_text_editor(
            {"command": "create", "path": "new.py", "file_text": "x = 1"},
            tmp_path,
        )
        assert "Created" in result
        assert (tmp_path / "new.py").read_text() == "x = 1"

    def test_create_nested(self, tmp_path: Path) -> None:
        execute_text_editor(
            {"command": "create", "path": "sub/dir/file.py", "file_text": "y = 2"},
            tmp_path,
        )
        assert (tmp_path / "sub" / "dir" / "file.py").read_text() == "y = 2"

    def test_str_replace(self, tmp_path: Path) -> None:
        (tmp_path / "code.py").write_text("x = 1\ny = 2\nz = 3")
        result = execute_text_editor(
            {"command": "str_replace", "path": "code.py", "old_str": "y = 2", "new_str": "y = 99"},
            tmp_path,
        )
        assert "Replaced" in result
        assert "y = 99" in (tmp_path / "code.py").read_text()

    def test_str_replace_not_found(self, tmp_path: Path) -> None:
        (tmp_path / "code.py").write_text("x = 1")
        result = execute_text_editor(
            {"command": "str_replace", "path": "code.py", "old_str": "nope", "new_str": "yes"},
            tmp_path,
        )
        assert "not found" in result.lower()

    def test_str_replace_multiple_matches(self, tmp_path: Path) -> None:
        (tmp_path / "code.py").write_text("x = 1\nx = 1\n")
        result = execute_text_editor(
            {"command": "str_replace", "path": "code.py", "old_str": "x = 1", "new_str": "x = 2"},
            tmp_path,
        )
        assert "2 times" in result

    def test_insert(self, tmp_path: Path) -> None:
        (tmp_path / "code.py").write_text("line1\nline2")
        result = execute_text_editor(
            {"command": "insert", "path": "code.py", "insert_line": 1, "insert_text": "inserted"},
            tmp_path,
        )
        assert "Inserted" in result
        content = (tmp_path / "code.py").read_text()
        assert "inserted" in content

    def test_path_traversal_blocked(self, tmp_path: Path) -> None:
        result = execute_text_editor({"command": "view", "path": "../../etc/passwd"}, tmp_path)
        assert "outside" in result.lower()

    def test_unknown_command(self, tmp_path: Path) -> None:
        result = execute_text_editor({"command": "frobnicate", "path": "x.py"}, tmp_path)
        assert "Unknown command" in result
