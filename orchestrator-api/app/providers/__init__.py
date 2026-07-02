from app.providers.adapter import ProviderAdapter
from app.providers.claude import ClaudeAdapter
from app.providers.codex import CodexAdapter
from app.providers.gemini import GeminiAdapter
from app.providers.types import (
    EventKind,
    NormalisedEvent,
    ProviderName,
    SessionOutcome,
    SessionResult,
    SessionRole,
    UsageReport,
)

__all__ = [
    "ClaudeAdapter",
    "CodexAdapter",
    "GeminiAdapter",
    "EventKind",
    "NormalisedEvent",
    "ProviderAdapter",
    "ProviderName",
    "SessionOutcome",
    "SessionResult",
    "SessionRole",
    "UsageReport",
    "get_adapter",
]


def get_adapter(provider: ProviderName) -> ProviderAdapter:
    """Return a fresh adapter instance for the given provider (Spec §3.3).

    Claude adapter reads ANTHROPIC_API_KEY from the environment via the
    Anthropic SDK default; Codex and Gemini are pure CLI wrappers.
    """
    if provider == "codex":
        return CodexAdapter()
    if provider == "gemini":
        return GeminiAdapter()
    import anthropic  # noqa: PLC0415

    return ClaudeAdapter(anthropic.AsyncAnthropic())
