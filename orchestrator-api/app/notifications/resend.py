from __future__ import annotations

import logging

import httpx

from app.notifications.channel import MessageKind

logger = logging.getLogger(__name__)

_RESEND_API = "https://api.resend.com"


class ResendSendError(Exception):
    pass


class ResendChannel:
    """Outbound Resend email channel — sends digests/summaries."""

    def __init__(
        self,
        secrets: dict[str, str],
        from_address: str = "Code Runner <noreply@coderunner.dev>",
        to_address: str = "",
    ) -> None:
        api_key = secrets.get("resend_api_key", "")
        if not api_key:
            raise ResendSendError("resend_api_key must be present in resolved secrets")
        self._api_key = api_key
        self._from = from_address
        self._to = to_address or secrets.get("resend_to_address", "")
        if not self._to:
            raise ResendSendError(
                "resend_to_address must be present in resolved secrets or passed explicitly"
            )
        self._http = httpx.Client(timeout=30.0)

    @property
    def name(self) -> str:
        return "email"

    @property
    def supported_kinds(self) -> frozenset[MessageKind]:
        return frozenset({MessageKind.DIGEST})

    def send(self, subject: str, body: str, kind: MessageKind) -> None:
        response = self._http.post(
            f"{_RESEND_API}/emails",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": self._from,
                "to": [self._to],
                "subject": subject,
                "text": body,
            },
        )
        if response.status_code not in (200, 201):
            raise ResendSendError(f"Resend send failed ({response.status_code}): {response.text}")
        logger.debug("Resend email sent to %s", self._to)

    def close(self) -> None:
        self._http.close()
