from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from app.blockers.models import BlockerType
from app.blockers.store import BlockerStore
from app.db.store import StateStore
from app.notifications.telegram_commands import (
    CommandKind,
    CommandRouter,
)
from app.notifications.telegram_inbound import (
    TelegramInbound,
    TelegramInboundError,
)
from app.usage.models import Meter
from app.usage.pause import UsagePauseManager
from app.usage.policy import UsagePolicy


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
def conn(state_store: StateStore):  # noqa: ANN201
    return state_store.conn


@pytest.fixture()
def pause_manager(conn) -> UsagePauseManager:  # noqa: ANN001
    return UsagePauseManager(conn)


@pytest.fixture()
def usage_policy() -> UsagePolicy:
    return UsagePolicy()


@pytest.fixture()
def blocker_store(conn) -> BlockerStore:  # noqa: ANN001
    return BlockerStore(conn)


@pytest.fixture()
def router(
    conn,  # noqa: ANN001
    pause_manager: UsagePauseManager,
    usage_policy: UsagePolicy,
    blocker_store: BlockerStore,
) -> CommandRouter:
    return CommandRouter(
        conn=conn,
        pause_manager=pause_manager,
        usage_policy=usage_policy,
        blocker_store=blocker_store,
    )


class TestCommandStatus:
    def test_status_no_active_run(self, router: CommandRouter) -> None:
        result = router.handle("status", run_id=None)
        assert result.command == CommandKind.STATUS
        assert result.success
        assert "No active run" in result.reply

    def test_status_active_run(self, router: CommandRouter) -> None:
        result = router.handle("status", run_id=1)
        assert result.command == CommandKind.STATUS
        assert result.success
        assert "Run #1" in result.reply
        assert "running" in result.reply
        assert "test-project" in result.reply

    def test_status_shows_paused(
        self,
        router: CommandRouter,
        pause_manager: UsagePauseManager,
    ) -> None:
        pause_manager.set_paused(1, Meter(kind="manual", utilisation=0.0))
        result = router.handle("status", run_id=1)
        assert "Paused: yes" in result.reply

    def test_status_shows_override(
        self,
        router: CommandRouter,
        usage_policy: UsagePolicy,
    ) -> None:
        usage_policy.set_override(True)
        result = router.handle("status", run_id=1)
        assert "Override: active" in result.reply

    def test_status_shows_blockers(
        self,
        router: CommandRouter,
        blocker_store: BlockerStore,
    ) -> None:
        from app.blockers.models import Blocker

        blocker_store.record(
            Blocker(
                run_id=1,
                issue_number=42,
                blocker_type=BlockerType.MISSING_SPEC,
                reason="Spec ambiguous",
                needed_to_unblock="Clarification",
            )
        )
        result = router.handle("status", run_id=1)
        assert "Parked blockers: 1" in result.reply
        assert "#42" in result.reply

    def test_status_nonexistent_run(self, router: CommandRouter) -> None:
        result = router.handle("status", run_id=999)
        assert not result.success
        assert "not found" in result.reply


class TestCommandPause:
    def test_pause_active_run(
        self,
        router: CommandRouter,
        pause_manager: UsagePauseManager,
    ) -> None:
        result = router.handle("pause", run_id=1)
        assert result.command == CommandKind.PAUSE
        assert result.success
        assert "paused" in result.reply
        assert pause_manager.is_paused(1)

    def test_pause_no_active_run(self, router: CommandRouter) -> None:
        result = router.handle("pause", run_id=None)
        assert not result.success
        assert "No active run" in result.reply

    def test_pause_already_paused(
        self,
        router: CommandRouter,
        pause_manager: UsagePauseManager,
    ) -> None:
        pause_manager.set_paused(1, Meter(kind="manual", utilisation=0.0))
        result = router.handle("pause", run_id=1)
        assert result.success
        assert "already paused" in result.reply


class TestCommandResume:
    def test_resume_paused_run(
        self,
        router: CommandRouter,
        pause_manager: UsagePauseManager,
    ) -> None:
        pause_manager.set_paused(1, Meter(kind="manual", utilisation=0.0))
        result = router.handle("resume", run_id=1)
        assert result.command == CommandKind.RESUME
        assert result.success
        assert "resumed" in result.reply
        assert not pause_manager.is_paused(1)

    def test_resume_not_paused(self, router: CommandRouter) -> None:
        result = router.handle("resume", run_id=1)
        assert result.success
        assert "not paused" in result.reply

    def test_resume_no_active_run(self, router: CommandRouter) -> None:
        result = router.handle("resume", run_id=None)
        assert not result.success


class TestCommandOverride:
    def test_toggle_on(
        self, router: CommandRouter, usage_policy: UsagePolicy
    ) -> None:
        result = router.handle("override usage", run_id=1)
        assert result.command == CommandKind.OVERRIDE_USAGE
        assert result.success
        assert "activated" in result.reply
        assert usage_policy.override_active

    def test_toggle_off(
        self, router: CommandRouter, usage_policy: UsagePolicy
    ) -> None:
        usage_policy.set_override(True)
        result = router.handle("override usage", run_id=1)
        assert "deactivated" in result.reply
        assert not usage_policy.override_active

    def test_works_without_run(
        self, router: CommandRouter, usage_policy: UsagePolicy
    ) -> None:
        result = router.handle("override usage", run_id=None)
        assert result.success
        assert usage_policy.override_active


class TestCommandBlockerResponse:
    def test_resolve_parked_blocker(
        self,
        router: CommandRouter,
        blocker_store: BlockerStore,
    ) -> None:
        from app.blockers.models import Blocker

        blocker_store.record(
            Blocker(
                run_id=1,
                issue_number=42,
                blocker_type=BlockerType.MISSING_SPEC,
                reason="Spec ambiguous",
                needed_to_unblock="Clarification",
            )
        )
        result = router.handle("resolve #42 The answer is X", run_id=1)
        assert result.command == CommandKind.BLOCKER_RESPONSE
        assert result.success
        assert "resolved" in result.reply
        assert "The answer is X" in result.reply
        assert blocker_store.list_parked(1) == []

    def test_resolve_no_matching_blocker(self, router: CommandRouter) -> None:
        result = router.handle("resolve #99 Some text", run_id=1)
        assert not result.success
        assert "No parked blocker" in result.reply

    def test_resolve_no_run(self, router: CommandRouter) -> None:
        result = router.handle("resolve #42 text", run_id=None)
        assert not result.success

    def test_resolve_missing_response_text(self, router: CommandRouter) -> None:
        result = router.handle("resolve #42", run_id=1)
        assert not result.success
        assert "Usage:" in result.reply

    def test_resolve_invalid_issue_number(self, router: CommandRouter) -> None:
        result = router.handle("resolve #abc response", run_id=1)
        assert not result.success
        assert "Invalid issue number" in result.reply


class TestUnknownCommand:
    def test_unknown_command_gets_help(self, router: CommandRouter) -> None:
        result = router.handle("do something", run_id=1)
        assert result.command == CommandKind.UNKNOWN
        assert result.success
        assert "Available commands" in result.reply
        assert "status" in result.reply
        assert "pause" in result.reply

    def test_case_insensitive(self, router: CommandRouter) -> None:
        result = router.handle("STATUS", run_id=1)
        assert result.command == CommandKind.STATUS

    def test_whitespace_trimmed(self, router: CommandRouter) -> None:
        result = router.handle("  status  ", run_id=1)
        assert result.command == CommandKind.STATUS


class TestTelegramInbound:
    def test_poll_routes_and_replies(self, router: CommandRouter) -> None:
        mock_http = MagicMock(spec=httpx.Client)
        mock_http.get.return_value = httpx.Response(
            status_code=200,
            json={
                "ok": True,
                "result": [
                    {
                        "update_id": 100,
                        "message": {
                            "text": "status",
                            "chat": {"id": 12345},
                        },
                    }
                ],
            },
            request=httpx.Request("GET", "https://example.com"),
        )
        mock_http.post.return_value = httpx.Response(
            status_code=200,
            json={"ok": True},
            request=httpx.Request("POST", "https://example.com"),
        )

        inbound = TelegramInbound(
            token="test-token",
            chat_id="12345",
            router=router,
            run_id=1,
            _http=mock_http,
        )

        results = inbound.poll()
        assert len(results) == 1
        assert results[0].command == CommandKind.STATUS
        mock_http.post.assert_called_once()

    def test_ignores_wrong_chat_id(self, router: CommandRouter) -> None:
        mock_http = MagicMock(spec=httpx.Client)
        mock_http.get.return_value = httpx.Response(
            status_code=200,
            json={
                "ok": True,
                "result": [
                    {
                        "update_id": 100,
                        "message": {
                            "text": "status",
                            "chat": {"id": 99999},
                        },
                    }
                ],
            },
            request=httpx.Request("GET", "https://example.com"),
        )

        inbound = TelegramInbound(
            token="test-token",
            chat_id="12345",
            router=router,
            run_id=1,
            _http=mock_http,
        )

        results = inbound.poll()
        assert len(results) == 0
        mock_http.post.assert_not_called()

    def test_poll_error_raises(self, router: CommandRouter) -> None:
        mock_http = MagicMock(spec=httpx.Client)
        mock_http.get.return_value = httpx.Response(
            status_code=500,
            text="Internal Server Error",
            request=httpx.Request("GET", "https://example.com"),
        )

        inbound = TelegramInbound(
            token="test-token",
            chat_id="12345",
            router=router,
            run_id=1,
            _http=mock_http,
        )

        with pytest.raises(TelegramInboundError, match="500"):
            inbound.poll()

    def test_updates_offset(self, router: CommandRouter) -> None:
        mock_http = MagicMock(spec=httpx.Client)
        mock_http.get.return_value = httpx.Response(
            status_code=200,
            json={
                "ok": True,
                "result": [
                    {
                        "update_id": 100,
                        "message": {"text": "status", "chat": {"id": 12345}},
                    },
                    {
                        "update_id": 101,
                        "message": {"text": "pause", "chat": {"id": 12345}},
                    },
                ],
            },
            request=httpx.Request("GET", "https://example.com"),
        )
        mock_http.post.return_value = httpx.Response(
            status_code=200,
            json={"ok": True},
            request=httpx.Request("POST", "https://example.com"),
        )

        inbound = TelegramInbound(
            token="test-token",
            chat_id="12345",
            router=router,
            run_id=1,
            _http=mock_http,
        )

        results = inbound.poll()
        assert len(results) == 2
        assert inbound._offset == 102

    def test_reply_failure_does_not_crash(self, router: CommandRouter) -> None:
        mock_http = MagicMock(spec=httpx.Client)
        mock_http.get.return_value = httpx.Response(
            status_code=200,
            json={
                "ok": True,
                "result": [
                    {
                        "update_id": 100,
                        "message": {"text": "status", "chat": {"id": 12345}},
                    }
                ],
            },
            request=httpx.Request("GET", "https://example.com"),
        )
        mock_http.post.return_value = httpx.Response(
            status_code=500,
            text="error",
            request=httpx.Request("POST", "https://example.com"),
        )

        inbound = TelegramInbound(
            token="test-token",
            chat_id="12345",
            router=router,
            run_id=1,
            _http=mock_http,
        )

        results = inbound.poll()
        assert len(results) == 1
