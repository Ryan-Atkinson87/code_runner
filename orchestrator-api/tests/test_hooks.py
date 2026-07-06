from __future__ import annotations

from app.providers.hooks import CODING_TOOLS, create_audit_record


class TestCodingTools:
    def test_contains_bash(self) -> None:
        assert "bash" in CODING_TOOLS

    def test_contains_text_editor(self) -> None:
        assert "str_replace_based_edit_tool" in CODING_TOOLS

    def test_nothing_else(self) -> None:
        assert len(CODING_TOOLS) == 2


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
