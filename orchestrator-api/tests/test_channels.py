from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.notifications.channel import MessageKind
from app.notifications.resend import ResendChannel, ResendSendError
from app.notifications.telegram import (
    TelegramChannel,
    TelegramSendError,
    _escape_markdown,
)

# ── Helpers ───────────────────────────────────────────────────────────


def _mock_transport(handler: Any) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _make_telegram(
    handler: Any,
    token: str = "test-bot-token",
    chat_id: str = "12345",
) -> TelegramChannel:
    channel = TelegramChannel.__new__(TelegramChannel)
    channel._token = token
    channel._chat_id = chat_id
    channel._http = httpx.Client(transport=_mock_transport(handler))
    return channel


def _make_resend(
    handler: Any,
    api_key: str = "re_test_key",
    to_address: str = "test@example.com",
) -> ResendChannel:
    channel = ResendChannel.__new__(ResendChannel)
    channel._api_key = api_key
    channel._from = "Code Runner <noreply@coderunner.dev>"
    channel._to = to_address
    channel._http = httpx.Client(transport=_mock_transport(handler))
    return channel


# ── Telegram tests ───────────────────────────────────────────────────


class TestTelegramChannel:
    def test_properties(self) -> None:
        channel = _make_telegram(lambda r: httpx.Response(200, json={"ok": True}))
        assert channel.name == "telegram"
        assert channel.supported_kinds == frozenset({MessageKind.INSTANT})
        channel.close()

    def test_send_success(self) -> None:
        requests_seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests_seen.append(request)
            return httpx.Response(200, json={"ok": True})

        channel = _make_telegram(handler)
        channel.send("Alert", "Something happened", MessageKind.INSTANT)

        assert len(requests_seen) == 1
        req = requests_seen[0]
        assert "sendMessage" in str(req.url)
        assert "test-bot-token" in str(req.url)

        import json

        body = json.loads(req.content)
        assert body["chat_id"] == "12345"
        assert body["parse_mode"] == "MarkdownV2"
        assert "Alert" in body["text"]
        channel.close()

    def test_send_failure_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400,
                json={"ok": False, "description": "Bad Request: chat not found"},
                headers={"content-type": "application/json"},
            )

        channel = _make_telegram(handler)
        with pytest.raises(TelegramSendError, match="chat not found"):
            channel.send("Alert", "body", MessageKind.INSTANT)
        channel.close()

    def test_send_non_json_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                502,
                text="Bad Gateway",
                headers={"content-type": "text/plain"},
            )

        channel = _make_telegram(handler)
        with pytest.raises(TelegramSendError, match="502"):
            channel.send("Alert", "body", MessageKind.INSTANT)
        channel.close()

    def test_constructor_missing_token_raises(self) -> None:
        with pytest.raises(TelegramSendError, match="telegram_bot_token"):
            TelegramChannel(secrets={"telegram_chat_id": "123"})

    def test_constructor_missing_chat_id_raises(self) -> None:
        with pytest.raises(TelegramSendError, match="telegram_chat_id"):
            TelegramChannel(secrets={"telegram_bot_token": "tok"})

    def test_constructor_with_valid_secrets(self) -> None:
        channel = TelegramChannel(
            secrets={
                "telegram_bot_token": "tok",
                "telegram_chat_id": "123",
            }
        )
        assert channel._token == "tok"
        assert channel._chat_id == "123"
        channel.close()


class TestEscapeMarkdown:
    def test_escapes_special_chars(self) -> None:
        assert _escape_markdown("hello_world") == r"hello\_world"
        assert _escape_markdown("*bold*") == r"\*bold\*"
        assert _escape_markdown("a.b") == r"a\.b"

    def test_plain_text_unchanged(self) -> None:
        assert _escape_markdown("hello world") == "hello world"

    def test_empty_string(self) -> None:
        assert _escape_markdown("") == ""


# ── Resend tests ─────────────────────────────────────────────────────


class TestResendChannel:
    def test_properties(self) -> None:
        channel = _make_resend(lambda r: httpx.Response(200, json={"id": "x"}))
        assert channel.name == "email"
        assert channel.supported_kinds == frozenset({MessageKind.DIGEST})
        channel.close()

    def test_send_success(self) -> None:
        requests_seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests_seen.append(request)
            return httpx.Response(200, json={"id": "email-123"})

        channel = _make_resend(handler)
        channel.send("Daily Summary", "Here is the digest", MessageKind.DIGEST)

        assert len(requests_seen) == 1
        req = requests_seen[0]
        assert "/emails" in str(req.url)

        import json

        body = json.loads(req.content)
        assert body["subject"] == "Daily Summary"
        assert body["text"] == "Here is the digest"
        assert body["to"] == ["test@example.com"]
        assert "Bearer re_test_key" in req.headers.get("authorization", "")
        channel.close()

    def test_send_201_accepted(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(201, json={"id": "email-456"})

        channel = _make_resend(handler)
        channel.send("Summary", "body", MessageKind.DIGEST)
        channel.close()

    def test_send_failure_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"message": "Invalid email"})

        channel = _make_resend(handler)
        with pytest.raises(ResendSendError, match="422"):
            channel.send("Summary", "body", MessageKind.DIGEST)
        channel.close()

    def test_send_server_error_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal Server Error")

        channel = _make_resend(handler)
        with pytest.raises(ResendSendError, match="500"):
            channel.send("Summary", "body", MessageKind.DIGEST)
        channel.close()

    def test_constructor_missing_api_key_raises(self) -> None:
        with pytest.raises(ResendSendError, match="resend_api_key"):
            ResendChannel(secrets={"resend_to_address": "a@b.com"})

    def test_constructor_missing_to_address_raises(self) -> None:
        with pytest.raises(ResendSendError, match="resend_to_address"):
            ResendChannel(secrets={"resend_api_key": "key"})

    def test_constructor_with_valid_secrets(self) -> None:
        channel = ResendChannel(
            secrets={
                "resend_api_key": "key",
                "resend_to_address": "a@b.com",
            }
        )
        assert channel._api_key == "key"
        assert channel._to == "a@b.com"
        channel.close()

    def test_explicit_to_overrides_secrets(self) -> None:
        channel = ResendChannel(
            secrets={"resend_api_key": "key", "resend_to_address": "a@b.com"},
            to_address="override@example.com",
        )
        assert channel._to == "override@example.com"
        channel.close()


# ── Registration tests ───────────────────────────────────────────────


class TestRegistration:
    def test_telegram_registered_in_default_registry(self) -> None:
        from app.notifications.factory import get_registry

        reg = get_registry()
        assert reg.get("telegram") is TelegramChannel

    def test_resend_registered_in_default_registry(self) -> None:
        from app.notifications.factory import get_registry

        reg = get_registry()
        assert reg.get("email") is ResendChannel
