from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.providers.types import SessionResult, SessionRole


class ProviderAdapter(ABC):
    """Interface every AI provider must implement (Spec §3.1).

    The orchestrator calls only this interface — never a provider SDK
    directly. Each invocation is a fresh, stateless session (§4.3);
    multi-provider event-mapping depth is deferred (§3.3 MVP note).
    """

    @abstractmethod
    async def run_session(
        self,
        workdir: Path,
        role: SessionRole,
        model: str,
        allowed_tools: list[str],
        prompt: str,
        context_files: list[Path],
    ) -> SessionResult:
        """Run a single AI session and return the normalised result.

        Each call starts a fresh session that re-reads live state — no
        session inherits another's context (§4.3).
        """
