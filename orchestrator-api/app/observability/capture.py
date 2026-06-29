from __future__ import annotations

import gzip
from pathlib import Path

from app.observability.models import SessionCapture


class CaptureError(Exception):
    """Raised when a capture write or read fails."""


class EventCaptureWriter:
    """Writes compressed Layer 1 session captures to disk (Spec §11.1).

    Files are stored as ``<base_dir>/captures/<YYYY-MM>/<session_id>.json.gz``,
    separate from git working copies (§11.2). The month directory supports
    date-based retention pruning.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    def write(self, capture: SessionCapture) -> Path:
        month_dir = self._month_dir(capture)

        try:
            month_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CaptureError(f"Failed to write capture {capture.session_id}: {exc}") from exc

        dest = month_dir / f"{capture.session_id}.json.gz"
        payload = capture.model_dump_json().encode()

        try:
            with gzip.open(dest, "wb") as f:
                f.write(payload)
        except OSError as exc:
            raise CaptureError(f"Failed to write capture {capture.session_id}: {exc}") from exc

        return dest

    def _month_dir(self, capture: SessionCapture) -> Path:
        month_key = capture.started_at.strftime("%Y-%m")
        return self._base_dir / "captures" / month_key


class EventCaptureReader:
    """Reads compressed Layer 1 session captures from disk."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    def read(self, session_id: str, month: str) -> SessionCapture:
        path = self._base_dir / "captures" / month / f"{session_id}.json.gz"
        if not path.exists():
            raise CaptureError(f"Capture not found: {path}")

        try:
            with gzip.open(path, "rb") as f:
                raw = f.read()
        except OSError as exc:
            raise CaptureError(f"Failed to read capture {session_id}: {exc}") from exc

        return SessionCapture.model_validate_json(raw)

    def list_sessions(self, month: str) -> list[str]:
        month_dir = self._base_dir / "captures" / month
        if not month_dir.exists():
            return []

        return [p.name.removesuffix(".json.gz") for p in sorted(month_dir.glob("*.json.gz"))]

    def list_months(self) -> list[str]:
        captures_dir = self._base_dir / "captures"
        if not captures_dir.exists():
            return []

        return sorted(d.name for d in captures_dir.iterdir() if d.is_dir())
