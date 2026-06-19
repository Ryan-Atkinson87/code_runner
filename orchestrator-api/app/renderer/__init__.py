from __future__ import annotations

from app.renderer.base import InstructionRenderer, RenderedOutput
from app.renderer.claude import ClaudeRenderer
from app.renderer.pipeline import compose_and_render

__all__ = [
    "ClaudeRenderer",
    "InstructionRenderer",
    "RenderedOutput",
    "compose_and_render",
    "get_renderer",
]


def get_renderer(provider: str) -> InstructionRenderer:
    if provider == "claude":
        return ClaudeRenderer()
    raise NotImplementedError(
        f"Instruction renderer for provider '{provider}' is not yet implemented (Phase 7)"
    )
