from __future__ import annotations

import json
import logging
import time
from enum import StrEnum
from pathlib import Path

import httpx

from app.providers.types import ProviderName
from app.usage.models import Meter, MeterKind, UsageSnapshot
from app.usage.reader import UsageReader

logger = logging.getLogger(__name__)

_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_BETA_HEADER = "oauth-2025-04-20"
_CACHE_TTL_SECONDS = 300.0


class FallbackLevel(StrEnum):
    OAUTH = "oauth"
    STATUS_LINE = "status_line"
    TOKEN_ESTIMATION = "token_estimation"


class SubscriptionUsageReader(UsageReader):
    """Reads Claude subscription usage via OAuth endpoint (Spec §6.2).

    Degradation chain: OAuth endpoint -> statusLine -> token estimation.
    Result is cached for ~5 minutes per §15 resolution.
    """

    def __init__(
        self,
        credentials_path: Path,
        provider: ProviderName,
        plan: str,
        *,
        http_client: httpx.AsyncClient | None = None,
        status_line_path: Path | None = None,
    ) -> None:
        self._credentials_path = credentials_path
        self._provider: ProviderName = provider
        self._plan = plan
        self._http_client = http_client
        self._status_line_path = status_line_path
        self._cache: UsageSnapshot | None = None
        self._cache_time: float = 0.0
        self.fallback_level: FallbackLevel = FallbackLevel.OAUTH

    async def read(self) -> UsageSnapshot:
        now = time.time()
        if self._cache and (now - self._cache_time) < _CACHE_TTL_SECONDS:
            return self._cache

        snapshot = await self._try_oauth(now)
        if snapshot is None:
            snapshot = self._try_status_line(now)
        if snapshot is None:
            snapshot = self._token_estimation_fallback(now)

        self._cache = snapshot
        self._cache_time = now
        return snapshot

    async def _try_oauth(self, now: float) -> UsageSnapshot | None:
        token = self._read_oauth_token()
        if token is None:
            logger.warning("No OAuth token found at %s", self._credentials_path)
            return None

        client = self._http_client or httpx.AsyncClient()
        owns_client = self._http_client is None
        try:
            response = await client.get(
                _USAGE_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "anthropic-beta": _BETA_HEADER,
                },
                timeout=10.0,
            )
            if response.status_code != 200:
                logger.warning(
                    "OAuth usage endpoint returned %d: %s",
                    response.status_code,
                    response.text[:200],
                )
                return None

            data = response.json()
            meters = _parse_oauth_response(data)
            self.fallback_level = FallbackLevel.OAUTH
            return UsageSnapshot(
                meters=meters,
                timestamp=now,
                provider=self._provider,
                plan=self._plan,
            )
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("OAuth usage read failed: %s", exc)
            return None
        finally:
            if owns_client:
                await client.aclose()

    def _try_status_line(self, now: float) -> UsageSnapshot | None:
        if self._status_line_path is None or not self._status_line_path.exists():
            return None

        try:
            text = self._status_line_path.read_text(encoding="utf-8")
            data = json.loads(text)
            rate_limits = data.get("rate_limits", {})
            meters: list[Meter] = []
            if "five_hour" in rate_limits:
                meters.append(
                    Meter(
                        kind=MeterKind.FIVE_HOUR,
                        utilisation=float(rate_limits["five_hour"]),
                    )
                )
            if "seven_day" in rate_limits:
                meters.append(
                    Meter(
                        kind=MeterKind.SEVEN_DAY,
                        utilisation=float(rate_limits["seven_day"]),
                    )
                )
            if not meters:
                return None

            self.fallback_level = FallbackLevel.STATUS_LINE
            return UsageSnapshot(
                meters=meters,
                timestamp=now,
                provider=self._provider,
                plan=self._plan,
            )
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            logger.warning("StatusLine fallback failed: %s", exc)
            return None

    def _token_estimation_fallback(self, now: float) -> UsageSnapshot:
        self.fallback_level = FallbackLevel.TOKEN_ESTIMATION
        logger.warning("All usage readers failed; returning empty snapshot (token estimation)")
        return UsageSnapshot(
            meters=[],
            timestamp=now,
            provider=self._provider,
            plan=self._plan,
        )

    def _read_oauth_token(self) -> str | None:
        if not self._credentials_path.exists():
            return None
        try:
            data = json.loads(self._credentials_path.read_text(encoding="utf-8"))
            for key in ("accessToken", "access_token", "token"):
                if key in data:
                    return str(data[key])
            return None
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read OAuth credentials: %s", exc)
            return None


def _parse_oauth_response(data: dict[str, object]) -> list[Meter]:
    """Parse the OAuth usage endpoint response into Meter objects.

    Tolerates unknown fields by carrying them as extra meters (§6.2).
    """
    meters: list[Meter] = []
    _KNOWN_WINDOW_KEYS = {
        "five_hour": MeterKind.FIVE_HOUR,
        "seven_day": MeterKind.SEVEN_DAY,
        "seven_day_opus": MeterKind.SEVEN_DAY_OPUS,
        "seven_day_sonnet": MeterKind.SEVEN_DAY_SONNET,
    }

    for response_key, meter_kind in _KNOWN_WINDOW_KEYS.items():
        window = data.get(response_key)
        if not isinstance(window, dict):
            continue
        utilisation = window.get("utilization", window.get("utilisation", 0))
        meters.append(
            Meter(
                kind=meter_kind,
                utilisation=float(utilisation),
                resets_at=_float_or_none(window.get("resets_at")),
                limit=_float_or_none(window.get("limit")),
                used=_float_or_none(window.get("used")),
            )
        )

    extra = data.get("extra_usage")
    if isinstance(extra, dict) and extra.get("is_enabled"):
        monthly_limit = _float_or_none(extra.get("monthly_limit"))
        used_credits = _float_or_none(extra.get("used_credits"))
        utilisation = extra.get("utilization", extra.get("utilisation", 0))
        meters.append(
            Meter(
                kind=MeterKind.AGENT_SDK_CREDIT,
                utilisation=float(utilisation),
                limit=monthly_limit,
                used=used_credits,
            )
        )

    for key, value in data.items():
        if key in _KNOWN_WINDOW_KEYS or key == "extra_usage":
            continue
        if isinstance(value, dict) and "utilization" in value:
            meters.append(
                Meter(
                    kind=key,
                    utilisation=float(value["utilization"]),
                    resets_at=_float_or_none(value.get("resets_at")),
                    limit=_float_or_none(value.get("limit")),
                    used=_float_or_none(value.get("used")),
                )
            )

    return meters


def _float_or_none(val: object) -> float | None:
    if val is None:
        return None
    return float(val)  # type: ignore[arg-type]
