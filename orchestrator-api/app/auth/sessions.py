import secrets
import time
from dataclasses import dataclass, field

SESSION_TTL_SECONDS = 60 * 60 * 24  # 24 hours


@dataclass
class SessionStore:
    _sessions: dict[str, float] = field(default_factory=dict)
    ttl: int = SESSION_TTL_SECONDS

    def create(self) -> str:
        token = secrets.token_urlsafe(32)
        self._sessions[token] = time.monotonic() + self.ttl
        return token

    def validate(self, token: str) -> bool:
        expiry = self._sessions.get(token)
        if expiry is None:
            return False
        if time.monotonic() > expiry:
            self._sessions.pop(token, None)
            return False
        return True

    def revoke(self, token: str) -> None:
        self._sessions.pop(token, None)
