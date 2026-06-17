from fastapi import Cookie, HTTPException, status

from app.auth.sessions import SessionStore

_session_store: SessionStore | None = None


def init_session_store(store: SessionStore) -> None:
    global _session_store
    _session_store = store


def get_session_store() -> SessionStore:
    if _session_store is None:
        raise RuntimeError("SessionStore not initialised — call init_session_store at startup")
    return _session_store


async def require_auth(session_id: str | None = Cookie(default=None)) -> str:
    store = get_session_store()
    if session_id is None or not store.validate(session_id):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    return session_id
