import os

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.auth.dependencies import get_session_store
from app.auth.rate_limit import RateLimiter

router = APIRouter(tags=["auth"])
_ph = PasswordHasher()
_login_limiter = RateLimiter()


class LoginRequest(BaseModel):
    password: str


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response) -> dict[str, str]:
    client_ip = request.client.host if request.client else "unknown"
    if _login_limiter.is_blocked(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests"
        )

    stored_hash = os.environ.get("AUTH_PASSWORD_HASH", "")
    if not stored_hash:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Auth not configured",
        )

    try:
        _ph.verify(stored_hash, body.password)
    except VerifyMismatchError:
        _login_limiter.record(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized"
        ) from None

    store = get_session_store()
    token = store.create()
    response.set_cookie(
        key="session_id",
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
    )
    return {"status": "ok"}


@router.post("/logout")
async def logout(
    response: Response, session_id: str | None = Cookie(default=None)
) -> dict[str, str]:
    if session_id is not None:
        store = get_session_store()
        store.revoke(session_id)
    response.delete_cookie(key="session_id", httponly=True, secure=True, samesite="strict")
    return {"status": "ok"}
