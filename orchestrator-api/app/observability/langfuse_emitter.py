from __future__ import annotations

import logging
import os

from langfuse import Langfuse
from langfuse.model import ModelUsage

from app.observability.models import SessionCapture

logger = logging.getLogger(__name__)

_DEFAULT_HOST = "http://langfuse:3000"


class LangfuseEmitter:
    """Emits completed AI sessions as Layer 2 Langfuse traces (Spec §11.1).

    A Langfuse outage must not block the wave: emit() catches all
    exceptions and logs a warning, never re-raising.
    """

    def __init__(self, public_key: str, secret_key: str, host: str) -> None:
        self._client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )

    @classmethod
    def from_env(cls) -> LangfuseEmitter:
        return cls(
            public_key=os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
            secret_key=os.environ.get("LANGFUSE_SECRET_KEY", ""),
            host=os.environ.get("LANGFUSE_HOST", _DEFAULT_HOST),
        )

    def emit(self, capture: SessionCapture) -> None:
        """Emit capture as a Langfuse trace. Exceptions are caught and logged."""
        try:
            self._emit_trace(capture)
        except Exception as exc:
            logger.warning(
                "Langfuse trace emission failed for session %s: %s",
                capture.session_id,
                exc,
            )

    def _emit_trace(self, capture: SessionCapture) -> None:
        month = capture.started_at.strftime("%Y-%m")
        trace = self._client.trace(
            id=capture.session_id,
            name=f"{capture.role}/{capture.skill}",
            tags=[
                f"wave:{capture.wave}",
                f"issue:{capture.issue_number}",
                f"month:{month}",
                str(capture.role),
                str(capture.skill),
            ],
            metadata={
                "run_id": capture.run_id,
                "wave": capture.wave,
                "issue_number": capture.issue_number,
                "role": capture.role,
                "skill": capture.skill,
                "model": capture.model,
                "outcome": capture.outcome,
                "retry_count": capture.retry_count,
                "artifacts": capture.artifacts,
                "month": month,
            },
            input={"tokens_in": capture.usage.tokens_in},
            output={
                "tokens_out": capture.usage.tokens_out,
                "outcome": capture.outcome,
                "artifacts": capture.artifacts,
            },
            start_time=capture.started_at,
            end_time=capture.finished_at,
        )
        usage: ModelUsage = {  # type: ignore[misc]
            "input": capture.usage.tokens_in,
            "output": capture.usage.tokens_out,
            "unit": "TOKENS",
            "total_cost": capture.usage.cost_usd,
        }
        trace.generation(
            name="session",
            model=capture.model,
            usage=usage,
            start_time=capture.started_at,
            end_time=capture.finished_at,
            output={"outcome": capture.outcome},
        )
        self._client.flush()
