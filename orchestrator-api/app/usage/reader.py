from __future__ import annotations

from abc import ABC, abstractmethod

from app.usage.models import UsageSnapshot


class UsageReader(ABC):
    """Interface for reading usage from a provider (Spec §6.2).

    #31 (subscription) and #32 (API) provide concrete implementations.
    The active reader is selected by the current provider/plan.
    """

    @abstractmethod
    async def read(self) -> UsageSnapshot:
        """Read current usage and return a snapshot."""
