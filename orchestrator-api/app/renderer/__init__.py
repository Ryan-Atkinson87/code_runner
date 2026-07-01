from __future__ import annotations

from app.renderer.agents import AgentsRenderer
from app.renderer.base import InstructionRenderer, RenderedOutput
from app.renderer.claude import ClaudeRenderer
from app.renderer.pipeline import compose_and_render

__all__ = [
    "AgentsRenderer",
    "ClaudeRenderer",
    "InstructionRenderer",
    "RenderedOutput",
    "compose_and_render",
    "get_renderer",
]


def get_renderer(provider: str) -> InstructionRenderer:
    if provider == "claude":
        return ClaudeRenderer()
    if provider in ("codex", "gemini"):
        return AgentsRenderer(provider)
    raise NotImplementedError(f"Instruction renderer for provider '{provider}' is not implemented")
