import time
from collections import defaultdict
from dataclasses import dataclass, field

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 300  # 5 minutes


@dataclass
class RateLimiter:
    max_attempts: int = MAX_ATTEMPTS
    window: int = WINDOW_SECONDS
    _attempts: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    def is_blocked(self, key: str) -> bool:
        now = time.monotonic()
        attempts = self._attempts[key]
        self._attempts[key] = [t for t in attempts if now - t < self.window]
        return len(self._attempts[key]) >= self.max_attempts

    def record(self, key: str) -> None:
        self._attempts[key].append(time.monotonic())
