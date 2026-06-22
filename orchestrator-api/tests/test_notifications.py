from __future__ import annotations

from app.config.schema import NotificationsSection
from app.notifications.channel import MessageKind
from app.notifications.dispatcher import Dispatcher, DispatchResult
from app.notifications.factory import ChannelRegistry, build_dispatcher

# ── Test doubles ──────────────────────────────────────────────────────


class FakeInstantChannel:
    def __init__(self, secrets: dict[str, str] | None = None) -> None:
        self.sent: list[tuple[str, str, MessageKind]] = []
        self._secrets = secrets or {}

    @property
    def name(self) -> str:
        return "telegram"

    @property
    def supported_kinds(self) -> frozenset[MessageKind]:
        return frozenset({MessageKind.INSTANT})

    def send(self, subject: str, body: str, kind: MessageKind) -> None:
        self.sent.append((subject, body, kind))


class FakeDigestChannel:
    def __init__(self, secrets: dict[str, str] | None = None) -> None:
        self.sent: list[tuple[str, str, MessageKind]] = []
        self._secrets = secrets or {}

    @property
    def name(self) -> str:
        return "email"

    @property
    def supported_kinds(self) -> frozenset[MessageKind]:
        return frozenset({MessageKind.DIGEST})

    def send(self, subject: str, body: str, kind: MessageKind) -> None:
        self.sent.append((subject, body, kind))


class FakeBothChannel:
    def __init__(self, secrets: dict[str, str] | None = None) -> None:
        self.sent: list[tuple[str, str, MessageKind]] = []

    @property
    def name(self) -> str:
        return "both"

    @property
    def supported_kinds(self) -> frozenset[MessageKind]:
        return frozenset({MessageKind.INSTANT, MessageKind.DIGEST})

    def send(self, subject: str, body: str, kind: MessageKind) -> None:
        self.sent.append((subject, body, kind))


class FailingChannel:
    def __init__(self, secrets: dict[str, str] | None = None) -> None:
        pass

    @property
    def name(self) -> str:
        return "failing"

    @property
    def supported_kinds(self) -> frozenset[MessageKind]:
        return frozenset({MessageKind.INSTANT, MessageKind.DIGEST})

    def send(self, subject: str, body: str, kind: MessageKind) -> None:
        raise RuntimeError("channel send failed")


# ── Dispatcher tests ──────────────────────────────────────────────────


class TestDispatcher:
    def test_routes_instant_to_matching_channel(self) -> None:
        instant = FakeInstantChannel()
        digest = FakeDigestChannel()
        dispatcher = Dispatcher([instant, digest])
        result = dispatcher.send("Alert", "Something happened", MessageKind.INSTANT)
        assert result.all_succeeded
        assert len(instant.sent) == 1
        assert len(digest.sent) == 0

    def test_routes_digest_to_matching_channel(self) -> None:
        instant = FakeInstantChannel()
        digest = FakeDigestChannel()
        dispatcher = Dispatcher([instant, digest])
        result = dispatcher.send("Summary", "Daily report", MessageKind.DIGEST)
        assert result.all_succeeded
        assert len(instant.sent) == 0
        assert len(digest.sent) == 1

    def test_routes_to_both_when_both_support_kind(self) -> None:
        both1 = FakeBothChannel()
        both2 = FakeBothChannel()
        dispatcher = Dispatcher([both1, both2])
        result = dispatcher.send("Alert", "body", MessageKind.INSTANT)
        assert result.all_succeeded
        assert len(both1.sent) == 1
        assert len(both2.sent) == 1

    def test_no_channels_returns_empty_result(self) -> None:
        dispatcher = Dispatcher([])
        result = dispatcher.send("Alert", "body", MessageKind.INSTANT)
        assert result.all_succeeded
        assert len(result.results) == 0

    def test_failure_isolated_other_channels_still_deliver(self) -> None:
        failing = FailingChannel()
        instant = FakeInstantChannel()
        dispatcher = Dispatcher([failing, instant])
        result = dispatcher.send("Alert", "body", MessageKind.INSTANT)
        assert not result.all_succeeded
        assert result.any_succeeded
        assert len(result.failures) == 1
        assert result.failures[0].channel_name == "failing"
        assert len(instant.sent) == 1

    def test_all_channels_fail(self) -> None:
        f1 = FailingChannel()
        f2 = FailingChannel()
        dispatcher = Dispatcher([f1, f2])
        result = dispatcher.send("Alert", "body", MessageKind.INSTANT)
        assert not result.all_succeeded
        assert not result.any_succeeded
        assert len(result.failures) == 2

    def test_failure_records_error_message(self) -> None:
        failing = FailingChannel()
        dispatcher = Dispatcher([failing])
        result = dispatcher.send("Alert", "body", MessageKind.INSTANT)
        assert result.failures[0].error == "channel send failed"


# ── DispatchResult tests ──────────────────────────────────────────────


class TestDispatchResult:
    def test_empty_result_all_succeeded(self) -> None:
        result = DispatchResult()
        assert result.all_succeeded
        assert not result.any_succeeded

    def test_mixed_results(self) -> None:
        from app.notifications.dispatcher import ChannelResult

        result = DispatchResult(
            results=[
                ChannelResult(channel_name="a", success=True),
                ChannelResult(channel_name="b", success=False, error="fail"),
            ]
        )
        assert not result.all_succeeded
        assert result.any_succeeded
        assert len(result.failures) == 1


# ── Factory / config integration tests ────────────────────────────────


class TestFactory:
    def _make_registry(self) -> ChannelRegistry:
        reg = ChannelRegistry()
        reg.register("telegram", FakeInstantChannel)  # type: ignore[arg-type]
        reg.register("email", FakeDigestChannel)  # type: ignore[arg-type]
        return reg

    def test_both_enabled(self) -> None:
        config = NotificationsSection(telegram=True, email=True)
        dispatcher = build_dispatcher(config, secrets={}, registry=self._make_registry())
        assert len(dispatcher._channels) == 2

    def test_telegram_only(self) -> None:
        config = NotificationsSection(telegram=True, email=False)
        dispatcher = build_dispatcher(config, secrets={}, registry=self._make_registry())
        assert len(dispatcher._channels) == 1
        assert dispatcher._channels[0].name == "telegram"

    def test_email_only(self) -> None:
        config = NotificationsSection(telegram=False, email=True)
        dispatcher = build_dispatcher(config, secrets={}, registry=self._make_registry())
        assert len(dispatcher._channels) == 1
        assert dispatcher._channels[0].name == "email"

    def test_both_disabled(self) -> None:
        config = NotificationsSection(telegram=False, email=False)
        dispatcher = build_dispatcher(config, secrets={}, registry=self._make_registry())
        assert len(dispatcher._channels) == 0

    def test_defaults_telegram_on_email_off(self) -> None:
        config = NotificationsSection()
        dispatcher = build_dispatcher(config, secrets={}, registry=self._make_registry())
        assert len(dispatcher._channels) == 1
        assert dispatcher._channels[0].name == "telegram"

    def test_missing_channel_class_skipped(self) -> None:
        reg = ChannelRegistry()
        reg.register("telegram", FakeInstantChannel)  # type: ignore[arg-type]
        config = NotificationsSection(telegram=True, email=True)
        dispatcher = build_dispatcher(config, secrets={}, registry=reg)
        assert len(dispatcher._channels) == 1

    def test_secrets_passed_to_channel(self) -> None:
        reg = ChannelRegistry()
        reg.register("telegram", FakeInstantChannel)  # type: ignore[arg-type]
        config = NotificationsSection(telegram=True, email=False)
        secrets = {"telegram_bot_token": "tok", "telegram_chat_id": "123"}
        dispatcher = build_dispatcher(config, secrets=secrets, registry=reg)
        channel = dispatcher._channels[0]
        assert isinstance(channel, FakeInstantChannel)
        assert channel._secrets == secrets


# ── Registry tests ────────────────────────────────────────────────────


class TestChannelRegistry:
    def test_register_and_get(self) -> None:
        reg = ChannelRegistry()
        reg.register("telegram", FakeInstantChannel)  # type: ignore[arg-type]
        assert reg.get("telegram") is FakeInstantChannel

    def test_get_missing_returns_none(self) -> None:
        reg = ChannelRegistry()
        assert reg.get("nonexistent") is None

    def test_available(self) -> None:
        reg = ChannelRegistry()
        reg.register("telegram", FakeInstantChannel)  # type: ignore[arg-type]
        reg.register("email", FakeDigestChannel)  # type: ignore[arg-type]
        assert sorted(reg.available()) == ["email", "telegram"]
