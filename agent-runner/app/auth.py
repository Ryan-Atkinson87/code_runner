from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from app.settings import Settings

_settings: Settings | None = None


def init_auth(settings: Settings) -> None:
    global _settings
    _settings = settings


async def require_token(authorization: str | None = Header(default=None)) -> None:
    settings = _settings
    if settings is None or not settings.token:
        raise HTTPException(status_code=503, detail="agent-runner has no auth token configured")

    expected = f"Bearer {settings.token}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="invalid or missing bearer token")
