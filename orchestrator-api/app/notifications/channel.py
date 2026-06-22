from __future__ import annotations

from enum import Enum
from typing import Protocol


class MessageKind(Enum):
    INSTANT = "instant"
    DIGEST = "digest"


class Channel(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def supported_kinds(self) -> frozenset[MessageKind]: ...

    def send(self, subject: str, body: str, kind: MessageKind) -> None: ...
