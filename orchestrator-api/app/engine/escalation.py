from __future__ import annotations

import logging
from dataclasses import dataclass

from app.blockers.models import Blocker, BlockerType
from app.blockers.store import BlockerStore
from app.engine.implement_loop import BlockerRecord
from app.notifications.channel import MessageKind
from app.notifications.dispatcher import Dispatcher, DispatchResult

logger = logging.getLogger(__name__)

_OUTCOME_TYPE_MAP: dict[str, BlockerType] = {
    "parked_stuck": BlockerType.STUCK_AGENT,
    "parked_fix_bound": BlockerType.OTHER,
    "error": BlockerType.OTHER,
}


@dataclass
class EscalationResult:
    blocker: Blocker
    notification: DispatchResult | None
    notification_error: str = ""


def escalate(
    blocker_record: BlockerRecord,
    run_id: int,
    wave_name: str,
    blocker_store: BlockerStore,
    dispatcher: Dispatcher | None,
    blocker_type: BlockerType = BlockerType.OTHER,
) -> EscalationResult:
    """Park an issue and notify the human immediately (Spec §9.1).

    Records the structured blocker and sends an instant notification.
    A notification failure does not fail the escalation — the blocker
    is still recorded and the wave continues.
    """
    blocker = blocker_store.record(
        Blocker(
            run_id=run_id,
            issue_number=blocker_record.issue_number,
            blocker_type=blocker_type,
            reason=blocker_record.reason,
            needed_to_unblock=blocker_record.reason,
        )
    )

    notification: DispatchResult | None = None
    notification_error = ""
    if dispatcher is not None:
        subject = f"Blocker: issue #{blocker_record.issue_number} parked"
        body = (
            f"Wave: {wave_name}\n"
            f"Issue: #{blocker_record.issue_number}\n"
            f"Type: {blocker_type.value}\n"
            f"Reason: {blocker_record.reason}"
        )
        try:
            notification = dispatcher.send(subject, body, MessageKind.INSTANT)
        except Exception as exc:
            notification_error = str(exc)
            logger.error(
                "Escalation notification failed for issue #%d: %s",
                blocker_record.issue_number,
                exc,
            )

    return EscalationResult(
        blocker=blocker,
        notification=notification,
        notification_error=notification_error,
    )


def blocker_type_for_outcome(outcome: str) -> BlockerType:
    return _OUTCOME_TYPE_MAP.get(outcome, BlockerType.OTHER)
