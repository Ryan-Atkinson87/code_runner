from __future__ import annotations

import logging
import time
from collections.abc import Mapping

from app.providers.types import ProviderName
from app.usage.models import Meter, MeterKind, UsageSnapshot
from app.usage.reader import UsageReader

logger = logging.getLogger(__name__)

_HEADER_MAP: dict[str, str] = {
    "anthropic-ratelimit-tokens-remaining": "tokens_remaining",
    "anthropic-ratelimit-tokens-limit": "tokens_limit",
    "anthropic-ratelimit-tokens-reset": "tokens_reset",
    "anthropic-ratelimit-requests-remaining": "requests_remaining",
    "anthropic-ratelimit-requests-limit": "requests_limit",
    "anthropic-ratelimit-requests-reset": "requests_reset",
}


class ApiUsageReader(UsageReader):
    """Reads API-mode usage from response headers (Spec §6.2).

    Built for completeness; inactive until an API key is configured.
    Call ``update_from_headers`` after each SDK response to accumulate
    rate-limit state; ``read`` returns the latest snapshot.
    """

    def __init__(self, provider: ProviderName, plan: str) -> None:
        self._provider: ProviderName = provider
        self._plan = plan
        self._latest: UsageSnapshot | None = None

    def update_from_headers(self, headers: Mapping[str, str]) -> None:
        """Extract rate-limit headers from an API response.

        Called by the provider adapter after each SDK call. Missing or
        un-parseable headers are silently skipped (degradation, not crash).
        """
        parsed: dict[str, float] = {}
        for header_name, field_name in _HEADER_MAP.items():
            raw = headers.get(header_name)
            if raw is None:
                continue
            try:
                parsed[field_name] = float(raw)
            except (ValueError, TypeError):
                logger.warning("Unparseable rate-limit header %s=%r", header_name, raw)

        meters = _build_meters(parsed)
        self._latest = UsageSnapshot(
            meters=meters,
            timestamp=time.time(),
            provider=self._provider,
            plan=self._plan,
        )

    async def read(self) -> UsageSnapshot:
        if self._latest is not None:
            return self._latest
        return UsageSnapshot(
            meters=[],
            timestamp=time.time(),
            provider=self._provider,
            plan=self._plan,
        )


def _build_meters(parsed: dict[str, float]) -> list[Meter]:
    meters: list[Meter] = []

    tokens_limit = parsed.get("tokens_limit")
    tokens_remaining = parsed.get("tokens_remaining")
    if tokens_limit is not None and tokens_remaining is not None and tokens_limit > 0:
        used = tokens_limit - tokens_remaining
        utilisation = (used / tokens_limit) * 100.0
        meters.append(
            Meter(
                kind=MeterKind.API_BUDGET,
                utilisation=min(utilisation, 100.0),
                limit=tokens_limit,
                used=used,
                resets_at=parsed.get("tokens_reset"),
            )
        )

    requests_limit = parsed.get("requests_limit")
    requests_remaining = parsed.get("requests_remaining")
    if requests_limit is not None and requests_remaining is not None and requests_limit > 0:
        used = requests_limit - requests_remaining
        utilisation = (used / requests_limit) * 100.0
        meters.append(
            Meter(
                kind=MeterKind.API_REQUESTS,
                utilisation=min(utilisation, 100.0),
                limit=requests_limit,
                used=used,
                resets_at=parsed.get("requests_reset"),
            )
        )

    return meters
