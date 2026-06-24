from __future__ import annotations

from app.config.schema import NotificationsSection
from app.notifications.channel import Channel
from app.notifications.dispatcher import Dispatcher
from app.notifications.resend import ResendChannel
from app.notifications.telegram import TelegramChannel


class ChannelRegistry:
    def __init__(self) -> None:
        self._constructors: dict[str, type[Channel]] = {}

    def register(self, name: str, cls: type[Channel]) -> None:
        self._constructors[name] = cls

    def available(self) -> list[str]:
        return list(self._constructors.keys())

    def get(self, name: str) -> type[Channel] | None:
        return self._constructors.get(name)


_registry = ChannelRegistry()
_registry.register("telegram", TelegramChannel)  # type: ignore[arg-type]
_registry.register("email", ResendChannel)  # type: ignore[arg-type]


def get_registry() -> ChannelRegistry:
    return _registry


def build_dispatcher(
    config: NotificationsSection,
    secrets: dict[str, str],
    registry: ChannelRegistry | None = None,
) -> Dispatcher:
    reg = registry or _registry
    channels: list[Channel] = []
    toggles = {"telegram": config.telegram, "email": config.email}
    for name, enabled in toggles.items():
        if not enabled:
            continue
        cls = reg.get(name)
        if cls is None:
            continue
        channels.append(cls(secrets=secrets))  # type: ignore[call-arg]
    return Dispatcher(channels)
