from __future__ import annotations

import logging

import httpx

from app.notifications.channel import MessageKind

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org"


class TelegramSendError(Exception):
    pass


class TelegramChannel:
    """Outbound Telegram channel — sends instant alerts via the Bot API."""

    def __init__(self, secrets: dict[str, str]) -> None:
        token = secrets.get("telegram_bot_token", "")
        chat_id = secrets.get("telegram_chat_id", "")
        if not token or not chat_id:
            raise TelegramSendError(
                "telegram_bot_token and telegram_chat_id must be present in resolved secrets"
            )
        self._token = token
        self._chat_id = chat_id
        self._http = httpx.Client(timeout=30.0)

    @property
    def name(self) -> str:
        return "telegram"

    @property
    def supported_kinds(self) -> frozenset[MessageKind]:
        return frozenset({MessageKind.INSTANT})

    def send(self, subject: str, body: str, kind: MessageKind) -> None:
        text = f"*{_escape_markdown(subject)}*\n\n{_escape_markdown(body)}"
        url = f"{_TELEGRAM_API}/bot{self._token}/sendMessage"
        response = self._http.post(
            url,
            json={
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": "MarkdownV2",
            },
        )
        if response.status_code != 200:
            content_type = response.headers.get("content-type", "")
            data = response.json() if content_type.startswith("application/json") else {}
            description = data.get("description", response.text)
            raise TelegramSendError(
                f"Telegram sendMessage failed ({response.status_code}): {description}"
            )
        logger.debug("Telegram message sent to chat %s", self._chat_id)

    def close(self) -> None:
        self._http.close()


_MD_V2_SPECIAL = frozenset("_*[]()~`>#+-=|{}.!")


def _escape_markdown(text: str) -> str:
    return "".join(f"\\{ch}" if ch in _MD_V2_SPECIAL else ch for ch in text)
