from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.notifications.channel import Channel, MessageKind

logger = logging.getLogger(__name__)


@dataclass
class ChannelResult:
    channel_name: str
    success: bool
    error: str = ""


@dataclass
class DispatchResult:
    results: list[ChannelResult] = field(default_factory=list)

    @property
    def all_succeeded(self) -> bool:
        return all(r.success for r in self.results)

    @property
    def any_succeeded(self) -> bool:
        return any(r.success for r in self.results)

    @property
    def failures(self) -> list[ChannelResult]:
        return [r for r in self.results if not r.success]


class Dispatcher:
    def __init__(self, channels: list[Channel]) -> None:
        self._channels = list(channels)

    def send(self, subject: str, body: str, kind: MessageKind) -> DispatchResult:
        result = DispatchResult()
        for channel in self._channels:
            if kind not in channel.supported_kinds:
                continue
            try:
                channel.send(subject, body, kind)
                result.results.append(ChannelResult(channel_name=channel.name, success=True))
            except Exception as exc:
                logger.error("Channel %s failed: %s", channel.name, exc)
                result.results.append(
                    ChannelResult(channel_name=channel.name, success=False, error=str(exc))
                )
        return result
