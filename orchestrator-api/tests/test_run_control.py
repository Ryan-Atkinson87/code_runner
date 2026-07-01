from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.auth import router as auth_router_mod
from app.auth.rate_limit import RateLimiter
from app.auth.sessions import SessionStore
from app.engine.run_manager import RunControlError, RunController, RunNotFoundError, RunStatus
from app.github.models import Milestone
from app.main import create_app
from app.settings import Settings

_ph = PasswordHasher()
_TEST_PASSWORD = "hunter2"
_TEST_HASH = _ph.hash(_TEST_PASSWORD)


@pytest.fixture()
def db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    from app.db.migrations import ALL_MIGRATIONS

    for migration_cls in ALL_MIGRATIONS:
        migration = migration_cls()
        migration.apply(conn)
    conn.commit()
    return conn


@pytest.fixture()
def mock_github() -> MagicMock:
    client = MagicMock()
    client.list_milestones.return_value = [
        Milestone(number=1, title="Foundations", state="closed"),
        Milestone(number=2, title="Git/PR engine", state="closed"),
        Milestone(number=6, title="Observability + UI", state="open"),
    ]
    return client


@pytest.fixture()
def controller(db_conn: sqlite3.Connection, mock_github: MagicMock) -> RunController:
    return RunController(
        conn=db_conn,
        github_client=mock_github,
        project_name="test-project",
        repo_name="test-repo",
    )


@pytest.fixture()
def authed_client(monkeypatch: pytest.MonkeyPatch, controller: RunController) -> TestClient:
    monkeypatch.setenv("AUTH_PASSWORD_HASH", _TEST_HASH)
    monkeypatch.setattr(auth_router_mod, "_login_limiter", RateLimiter())
    app = create_app(
        Settings(),
        session_store=SessionStore(),
        run_controller=controller,
    )
    client = TestClient(app, base_url="https://testserver")
    client.post("/login", json={"password": _TEST_PASSWORD})
    return client


@pytest.fixture()
def unauthed_client(monkeypatch: pytest.MonkeyPatch, controller: RunController) -> TestClient:
    monkeypatch.setattr(auth_router_mod, "_login_limiter", RateLimiter())
    app = create_app(
        Settings(),
        session_store=SessionStore(),
        run_controller=controller,
    )
    return TestClient(app, base_url="https://testserver")


class TestAuthGuard:
    def test_waves_rejected_unauthenticated(self, unauthed_client: TestClient) -> None:
        assert unauthed_client.get("/runs/waves").status_code == 401

    def test_status_rejected_unauthenticated(self, unauthed_client: TestClient) -> None:
        assert unauthed_client.get("/runs/status").status_code == 401

    def test_start_rejected_unauthenticated(self, unauthed_client: TestClient) -> None:
        resp = unauthed_client.post("/runs/start", json={"wave": "test"})
        assert resp.status_code == 401

    def test_stop_rejected_unauthenticated(self, unauthed_client: TestClient) -> None:
        assert unauthed_client.post("/runs/1/stop").status_code == 401

    def test_pause_rejected_unauthenticated(self, unauthed_client: TestClient) -> None:
        assert unauthed_client.post("/runs/1/pause").status_code == 401

    def test_resume_rejected_unauthenticated(self, unauthed_client: TestClient) -> None:
        assert unauthed_client.post("/runs/1/resume").status_code == 401


class TestListWaves:
    def test_returns_milestones(self, authed_client: TestClient, mock_github: MagicMock) -> None:
        resp = authed_client.get("/runs/waves")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["waves"]) == 3
        assert data["waves"][2]["name"] == "Observability + UI"
        assert data["waves"][2]["state"] == "open"
        mock_github.list_milestones.assert_called_once_with("test-repo", state="all")


class TestStartRun:
    def test_starts_successfully(self, authed_client: TestClient) -> None:
        resp = authed_client.post(
            "/runs/start", json={"wave": "Observability + UI", "provider": "claude"}
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "running"
        assert data["wave"] == "Observability + UI"
        assert data["provider"] == "claude"
        assert data["project"] == "test-project"

    def test_defaults_to_claude_provider(self, authed_client: TestClient) -> None:
        resp = authed_client.post("/runs/start", json={"wave": "test-wave"})
        assert resp.status_code == 201
        assert resp.json()["provider"] == "claude"

    def test_rejects_empty_wave(self, authed_client: TestClient) -> None:
        resp = authed_client.post("/runs/start", json={"wave": ""})
        assert resp.status_code == 422

    def test_rejects_invalid_provider(self, authed_client: TestClient) -> None:
        resp = authed_client.post("/runs/start", json={"wave": "test", "provider": "invalid"})
        assert resp.status_code == 422

    def test_conflict_when_already_running(self, authed_client: TestClient) -> None:
        authed_client.post("/runs/start", json={"wave": "wave-1"})
        resp = authed_client.post("/runs/start", json={"wave": "wave-2"})
        assert resp.status_code == 409


class TestStopRun:
    def test_not_found_returns_404(self, authed_client: TestClient) -> None:
        resp = authed_client.post("/runs/999/stop")
        assert resp.status_code == 404

    def test_stops_running(self, authed_client: TestClient) -> None:
        start = authed_client.post("/runs/start", json={"wave": "test"})
        run_id = start.json()["run_id"]

        resp = authed_client.post(f"/runs/{run_id}/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "stopped"

    def test_stops_paused(self, authed_client: TestClient) -> None:
        start = authed_client.post("/runs/start", json={"wave": "test"})
        run_id = start.json()["run_id"]
        authed_client.post(f"/runs/{run_id}/pause")

        resp = authed_client.post(f"/runs/{run_id}/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "stopped"

    def test_conflict_when_already_stopped(self, authed_client: TestClient) -> None:
        start = authed_client.post("/runs/start", json={"wave": "test"})
        run_id = start.json()["run_id"]
        authed_client.post(f"/runs/{run_id}/stop")

        resp = authed_client.post(f"/runs/{run_id}/stop")
        assert resp.status_code == 409


class TestPauseRun:
    def test_not_found_returns_404(self, authed_client: TestClient) -> None:
        resp = authed_client.post("/runs/999/pause")
        assert resp.status_code == 404

    def test_pauses_running(self, authed_client: TestClient) -> None:
        start = authed_client.post("/runs/start", json={"wave": "test"})
        run_id = start.json()["run_id"]

        resp = authed_client.post(f"/runs/{run_id}/pause")
        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"

    def test_conflict_when_not_running(self, authed_client: TestClient) -> None:
        start = authed_client.post("/runs/start", json={"wave": "test"})
        run_id = start.json()["run_id"]
        authed_client.post(f"/runs/{run_id}/stop")

        resp = authed_client.post(f"/runs/{run_id}/pause")
        assert resp.status_code == 409


class TestResumeRun:
    def test_not_found_returns_404(self, authed_client: TestClient) -> None:
        resp = authed_client.post("/runs/999/resume")
        assert resp.status_code == 404

    def test_resumes_paused(self, authed_client: TestClient) -> None:
        start = authed_client.post("/runs/start", json={"wave": "test"})
        run_id = start.json()["run_id"]
        authed_client.post(f"/runs/{run_id}/pause")

        resp = authed_client.post(f"/runs/{run_id}/resume")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

    def test_conflict_when_not_paused(self, authed_client: TestClient) -> None:
        start = authed_client.post("/runs/start", json={"wave": "test"})
        run_id = start.json()["run_id"]

        resp = authed_client.post(f"/runs/{run_id}/resume")
        assert resp.status_code == 409


class TestRunStatus:
    def test_no_active_run(self, authed_client: TestClient) -> None:
        resp = authed_client.get("/runs/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is False
        assert data["run"] is None

    def test_active_run(self, authed_client: TestClient) -> None:
        authed_client.post("/runs/start", json={"wave": "test"})
        resp = authed_client.get("/runs/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is True
        assert data["run"]["status"] == "running"

    def test_after_stop_shows_inactive(self, authed_client: TestClient) -> None:
        start = authed_client.post("/runs/start", json={"wave": "test"})
        run_id = start.json()["run_id"]
        authed_client.post(f"/runs/{run_id}/stop")

        resp = authed_client.get("/runs/status")
        assert resp.status_code == 200
        assert resp.json()["active"] is False

    def test_status_returns_correct_provider(self, authed_client: TestClient) -> None:
        authed_client.post("/runs/start", json={"wave": "test-wave", "provider": "claude"})
        resp = authed_client.get("/runs/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is True
        assert data["run"]["provider"] == "claude"


class TestRunController:
    def test_start_creates_db_record(
        self, controller: RunController, db_conn: sqlite3.Connection
    ) -> None:
        state = controller.start_run("proj", "wave-1", "claude")
        row = db_conn.execute(
            "SELECT project, milestone, status FROM runs WHERE id = ?",
            (state.run_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == "proj"
        assert row[1] == "wave-1"
        assert row[2] == "running"

    def test_stop_updates_status(self, controller: RunController) -> None:
        state = controller.start_run("proj", "wave-1", "claude")
        stopped = controller.stop_run(state.run_id)
        assert stopped.status == RunStatus.STOPPED

    def test_pause_resume_cycle(self, controller: RunController) -> None:
        state = controller.start_run("proj", "wave-1", "claude")
        paused = controller.pause_run(state.run_id)
        assert paused.status == RunStatus.PAUSED
        resumed = controller.resume_run(state.run_id)
        assert resumed.status == RunStatus.RUNNING

    def test_complete_run(self, controller: RunController) -> None:
        state = controller.start_run("proj", "wave-1", "claude")
        controller.complete_run(state.run_id)
        result = controller.get_status(state.run_id)
        assert result is not None
        assert result.status == RunStatus.COMPLETED

    def test_fail_run(self, controller: RunController) -> None:
        state = controller.start_run("proj", "wave-1", "claude")
        controller.fail_run(state.run_id)
        result = controller.get_status(state.run_id)
        assert result is not None
        assert result.status == RunStatus.FAILED

    def test_cannot_start_while_running(self, controller: RunController) -> None:
        controller.start_run("proj", "wave-1", "claude")
        with pytest.raises(RunControlError, match="already running"):
            controller.start_run("proj", "wave-2", "claude")

    def test_stop_nonexistent_raises(self, controller: RunController) -> None:
        with pytest.raises(RunNotFoundError, match="not found"):
            controller.stop_run(999)

    def test_list_waves(self, controller: RunController, mock_github: MagicMock) -> None:
        waves = controller.list_waves()
        assert len(waves) == 3
        assert waves[0]["name"] == "Foundations"
        mock_github.list_milestones.assert_called_once_with("test-repo", state="all")

    def test_list_waves_no_github(self, db_conn: sqlite3.Connection) -> None:
        ctrl = RunController(conn=db_conn)
        assert ctrl.list_waves() == []

    def test_provider_persisted_to_db(
        self, controller: RunController, db_conn: sqlite3.Connection
    ) -> None:
        state = controller.start_run("proj", "wave-1", "claude")
        row = db_conn.execute(
            "SELECT provider FROM runs WHERE id = ?",
            (state.run_id,),
        ).fetchone()
        assert row is not None
        assert row[0] == "claude"

    def test_get_status_returns_provider(self, controller: RunController) -> None:
        state = controller.start_run("proj", "wave-1", "claude")
        fetched = controller.get_status(state.run_id)
        assert fetched is not None
        assert fetched.provider == "claude"

    def test_can_start_after_stop(self, controller: RunController) -> None:
        state = controller.start_run("proj", "wave-1", "claude")
        controller.stop_run(state.run_id)
        new_state = controller.start_run("proj", "wave-2", "claude")
        assert new_state.status == RunStatus.RUNNING

    def test_recovers_running_run_on_restart(self, db_conn: sqlite3.Connection) -> None:
        original = RunController(conn=db_conn, project_name="proj", repo_name="repo")
        state = original.start_run("proj", "wave-1", "claude")

        restarted = RunController(conn=db_conn, project_name="proj", repo_name="repo")
        active = restarted.get_active_run()
        assert active is not None
        assert active.run_id == state.run_id
        assert active.status == RunStatus.RUNNING

    def test_recovers_paused_run_on_restart(self, db_conn: sqlite3.Connection) -> None:
        original = RunController(conn=db_conn, project_name="proj", repo_name="repo")
        state = original.start_run("proj", "wave-1", "claude")
        original.pause_run(state.run_id)

        restarted = RunController(conn=db_conn, project_name="proj", repo_name="repo")
        active = restarted.get_active_run()
        assert active is not None
        assert active.run_id == state.run_id
        assert active.status == RunStatus.PAUSED

    def test_no_recovery_when_run_stopped(self, db_conn: sqlite3.Connection) -> None:
        original = RunController(conn=db_conn, project_name="proj", repo_name="repo")
        state = original.start_run("proj", "wave-1", "claude")
        original.stop_run(state.run_id)

        restarted = RunController(conn=db_conn, project_name="proj", repo_name="repo")
        assert restarted.get_active_run() is None

    def test_active_task_property_initially_none(self, controller: RunController) -> None:
        assert controller.active_task is None

    def test_set_active_task_exposed_via_property(self, controller: RunController) -> None:
        import asyncio

        async def _noop() -> None:
            pass

        async def _run() -> None:
            task = asyncio.create_task(_noop())
            controller.set_active_task(task)
            assert controller.active_task is task
            await task

        asyncio.run(_run())


class TestMonitorSwitch:
    @pytest.fixture()
    def mock_monitor(self) -> MagicMock:
        m = MagicMock()
        m.reader = MagicMock()
        return m

    @pytest.fixture()
    def authed_client_with_monitor(
        self,
        monkeypatch: pytest.MonkeyPatch,
        controller: RunController,
        mock_monitor: MagicMock,
    ) -> TestClient:
        monkeypatch.setenv("AUTH_PASSWORD_HASH", _TEST_HASH)
        monkeypatch.setattr(auth_router_mod, "_login_limiter", RateLimiter())
        app = create_app(
            Settings(),
            session_store=SessionStore(),
            run_controller=controller,
            usage_monitor=mock_monitor,  # type: ignore[arg-type]
        )
        client = TestClient(app, base_url="https://testserver")
        client.post("/login", json={"password": _TEST_PASSWORD})
        return client

    def test_switch_reader_called_on_start(
        self, authed_client_with_monitor: TestClient, mock_monitor: MagicMock
    ) -> None:
        authed_client_with_monitor.post(
            "/runs/start", json={"wave": "test-wave", "provider": "codex"}
        )
        mock_monitor.switch_reader.assert_called_once()
        call_args = mock_monitor.switch_reader.call_args
        assert call_args[0][1] == "codex"

    def test_switch_reader_uses_correct_provider(
        self, authed_client_with_monitor: TestClient, mock_monitor: MagicMock
    ) -> None:
        authed_client_with_monitor.post("/runs/start", json={"wave": "test", "provider": "gemini"})
        provider_arg = mock_monitor.switch_reader.call_args[0][1]
        assert provider_arg == "gemini"


class TestWaveDispatch:
    @pytest.fixture()
    def authed_client_with_dispatch(
        self,
        monkeypatch: pytest.MonkeyPatch,
        controller: RunController,
    ) -> tuple[TestClient, AsyncMock]:
        monkeypatch.setenv("AUTH_PASSWORD_HASH", _TEST_HASH)
        monkeypatch.setattr(auth_router_mod, "_login_limiter", RateLimiter())
        mock_fn: AsyncMock = AsyncMock()
        app = create_app(
            Settings(),
            session_store=SessionStore(),
            run_controller=controller,
            wave_run_fn=mock_fn,
        )
        client = TestClient(app, base_url="https://testserver")
        client.post("/login", json={"password": _TEST_PASSWORD})
        return client, mock_fn

    def test_active_task_set_after_start(
        self,
        authed_client_with_dispatch: tuple[TestClient, AsyncMock],
        controller: RunController,
    ) -> None:
        client, _ = authed_client_with_dispatch
        resp = client.post("/runs/start", json={"wave": "test", "provider": "claude"})
        assert resp.status_code == 201
        assert controller.active_task is not None

    def test_dispatch_not_called_without_wave_fn(
        self, authed_client: TestClient, controller: RunController
    ) -> None:
        resp = authed_client.post("/runs/start", json={"wave": "test"})
        assert resp.status_code == 201
        assert controller.active_task is None
