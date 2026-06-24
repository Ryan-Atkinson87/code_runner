from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.blockers.models import BlockerStatus, BlockerType
from app.blockers.store import BlockerStore
from app.db.store import StateStore
from app.engine.escalation import (
    EscalationResult,
    blocker_type_for_outcome,
    escalate,
)
from app.engine.implement_loop import BlockerRecord
from app.notifications.channel import MessageKind
from app.notifications.dispatcher import ChannelResult, Dispatcher, DispatchResult


@pytest.fixture()
def state_store(tmp_path: Path) -> StateStore:
    db_path = tmp_path / "test.db"
    s = StateStore(db_path)
    s.open()
    s.conn.execute(
        "INSERT INTO runs (project, milestone, status) VALUES (?, ?, ?)",
        ("test-project", "Phase 5", "running"),
    )
    s.conn.commit()
    yield s  # type: ignore[misc]
    s.close()


@pytest.fixture()
def blocker_store(state_store: StateStore) -> BlockerStore:
    return BlockerStore(state_store.conn)


def _make_blocker_record(
    issue_number: int = 42,
    reason: str = "Gate failures after 3 fix attempts",
) -> BlockerRecord:
    return BlockerRecord(issue_number=issue_number, reason=reason)


def _mock_dispatcher(success: bool = True) -> Dispatcher:
    mock = MagicMock(spec=Dispatcher)
    mock.send.return_value = DispatchResult(
        results=[ChannelResult(channel_name="telegram", success=success)]
    )
    return mock


class TestEscalate:
    def test_records_blocker_in_store(self, blocker_store: BlockerStore) -> None:
        record = _make_blocker_record()
        result = escalate(
            blocker_record=record,
            run_id=1,
            wave_name="wave-1",
            blocker_store=blocker_store,
            dispatcher=None,
        )
        assert isinstance(result, EscalationResult)
        assert result.blocker.id is not None
        assert result.blocker.issue_number == 42
        assert result.blocker.status == BlockerStatus.PARKED

        parked = blocker_store.list_parked(1)
        assert len(parked) == 1
        assert parked[0].issue_number == 42

    def test_sends_immediate_notification(self, blocker_store: BlockerStore) -> None:
        record = _make_blocker_record()
        dispatcher = _mock_dispatcher()

        result = escalate(
            blocker_record=record,
            run_id=1,
            wave_name="wave-1",
            blocker_store=blocker_store,
            dispatcher=dispatcher,
        )

        dispatcher.send.assert_called_once()
        call_args = dispatcher.send.call_args
        assert call_args[0][2] == MessageKind.INSTANT
        assert "#42" in call_args[0][0]
        assert result.notification is not None
        assert result.notification.all_succeeded

    def test_notification_failure_does_not_fail_escalation(
        self, blocker_store: BlockerStore
    ) -> None:
        record = _make_blocker_record()
        dispatcher = MagicMock(spec=Dispatcher)
        dispatcher.send.side_effect = RuntimeError("Network error")

        result = escalate(
            blocker_record=record,
            run_id=1,
            wave_name="wave-1",
            blocker_store=blocker_store,
            dispatcher=dispatcher,
        )

        assert result.blocker.id is not None
        assert result.blocker.status == BlockerStatus.PARKED
        assert result.notification is None
        assert result.notification_error == "Network error"

    def test_no_dispatcher_still_records(self, blocker_store: BlockerStore) -> None:
        record = _make_blocker_record()
        result = escalate(
            blocker_record=record,
            run_id=1,
            wave_name="wave-1",
            blocker_store=blocker_store,
            dispatcher=None,
        )
        assert result.blocker.id is not None
        assert result.notification is None
        assert result.notification_error == ""

    def test_stuck_agent_type(self, blocker_store: BlockerStore) -> None:
        record = _make_blocker_record(reason="Stuck: 3 checkpoints without producing a PR")
        result = escalate(
            blocker_record=record,
            run_id=1,
            wave_name="wave-1",
            blocker_store=blocker_store,
            dispatcher=None,
            blocker_type=BlockerType.STUCK_AGENT,
        )
        assert result.blocker.blocker_type == BlockerType.STUCK_AGENT

    def test_notification_body_includes_wave_and_reason(
        self, blocker_store: BlockerStore
    ) -> None:
        record = _make_blocker_record(issue_number=7, reason="Spec unclear")
        dispatcher = _mock_dispatcher()

        escalate(
            blocker_record=record,
            run_id=1,
            wave_name="wave-3",
            blocker_store=blocker_store,
            dispatcher=dispatcher,
            blocker_type=BlockerType.MISSING_SPEC,
        )

        body = dispatcher.send.call_args[0][1]
        assert "wave-3" in body
        assert "#7" in body
        assert "Spec unclear" in body
        assert "missing_spec" in body

    def test_idempotent_escalation(self, blocker_store: BlockerStore) -> None:
        record = _make_blocker_record()
        r1 = escalate(
            blocker_record=record,
            run_id=1,
            wave_name="wave-1",
            blocker_store=blocker_store,
            dispatcher=None,
        )
        r2 = escalate(
            blocker_record=record,
            run_id=1,
            wave_name="wave-1",
            blocker_store=blocker_store,
            dispatcher=None,
        )
        assert r1.blocker.id == r2.blocker.id
        assert len(blocker_store.list_parked(1)) == 1


class TestBlockerTypeForOutcome:
    def test_parked_stuck_maps_to_stuck_agent(self) -> None:
        assert blocker_type_for_outcome("parked_stuck") == BlockerType.STUCK_AGENT

    def test_parked_fix_bound_maps_to_other(self) -> None:
        assert blocker_type_for_outcome("parked_fix_bound") == BlockerType.OTHER

    def test_error_maps_to_other(self) -> None:
        assert blocker_type_for_outcome("error") == BlockerType.OTHER

    def test_unknown_maps_to_other(self) -> None:
        assert blocker_type_for_outcome("something_else") == BlockerType.OTHER
