from __future__ import annotations

import time

from app.providers.types import AuditRecord

CODING_TOOLS: frozenset[str] = frozenset({"bash", "str_replace_based_edit_tool"})


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
