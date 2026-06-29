from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

from app.notifications.telegram import _TELEGRAM_API
from app.notifications.telegram_commands import CommandResult, CommandRouter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelegramUpdate:
    update_id: int
    chat_id: int
    text: str


class TelegramInboundError(Exception):
    pass


@dataclass
class TelegramInbound:
    """Two-way Telegram channel: polls for commands, routes them, and replies.

    Only accepts messages from the configured chat_id.
    """

    token: str
    chat_id: str
    router: CommandRouter
    run_id: int | None = None
    _offset: int = 0
    _http: httpx.Client = field(default_factory=lambda: httpx.Client(timeout=35.0))

    def poll(self) -> list[CommandResult]:
        updates = self._get_updates()
        results: list[CommandResult] = []
        for update in updates:
            if str(update.chat_id) != self.chat_id:
                logger.warning(
                    "Ignoring message from unknown chat %s (expected %s)",
                    update.chat_id,
                    self.chat_id,
                )
                continue

            result = self.router.handle(update.text, self.run_id)
            self._send_reply(result.reply)
            results.append(result)

        return results

    def _get_updates(self) -> list[TelegramUpdate]:
        url = f"{_TELEGRAM_API}/bot{self.token}/getUpdates"
        try:
            response = self._http.get(
                url,
                params={
                    "offset": self._offset,
                    "timeout": 30,
                    "allowed_updates": '["message"]',
                },
            )
        except httpx.HTTPError as exc:
            raise TelegramInboundError(f"Failed to poll Telegram: {exc}") from exc

        if response.status_code != 200:
            raise TelegramInboundError(
                f"Telegram getUpdates failed ({response.status_code}): {response.text}"
            )

        data = response.json()
        if not data.get("ok"):
            raise TelegramInboundError(f"Telegram getUpdates returned error: {data}")

        updates: list[TelegramUpdate] = []
        for item in data.get("result", []):
            self._offset = item["update_id"] + 1
            message = item.get("message", {})
            text = message.get("text", "")
            chat = message.get("chat", {})
            chat_id = chat.get("id", 0)
            if text and chat_id:
                updates.append(
                    TelegramUpdate(
                        update_id=item["update_id"],
                        chat_id=chat_id,
                        text=text,
                    )
                )

        return updates

    def _send_reply(self, text: str) -> None:
        url = f"{_TELEGRAM_API}/bot{self.token}/sendMessage"
        try:
            response = self._http.post(
                url,
                json={"chat_id": self.chat_id, "text": text},
            )
            if response.status_code != 200:
                logger.error(
                    "Failed to send Telegram reply (%d): %s",
                    response.status_code,
                    response.text,
                )
        except httpx.HTTPError as exc:
            logger.error("Telegram reply failed: %s", exc)

    def close(self) -> None:
        self._http.close()
