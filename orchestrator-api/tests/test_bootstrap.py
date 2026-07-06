from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

import app.bootstrap as bootstrap
from app.bootstrap import build_dependencies, should_bootstrap
from app.config.schema import ProjectConfig
from app.engine.run_manager import RunController
from app.github.client import GitHubClient
from app.main import create_app
from app.personas.loader import load_base_prompts, load_overlays
from app.secrets.resolver import SecretResolutionError
from app.settings import Settings
from app.skills.loader import load_skills_from_directory

_FIXTURE = Path(__file__).parent / "fixtures" / "minimal_project.yaml"
_ph = PasswordHasher()
_TEST_PASSWORD = "hunter2"
_TEST_HASH = _ph.hash(_TEST_PASSWORD)


@pytest.fixture
def secrets_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_PAT", "test-pat")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("NOTION_TOKEN", "test-notion")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "test-chat")


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        project_config_path=str(_FIXTURE),
        db_path=str(tmp_path / "state.db"),
    )


class TestShouldBootstrap:
    def test_false_when_unconfigured(self) -> None:
        assert should_bootstrap(Settings()) is False

    def test_false_when_only_db_path_set(self, tmp_path: Path) -> None:
        assert should_bootstrap(Settings(db_path=str(tmp_path / "state.db"))) is False

    def test_true_when_both_paths_set(self, tmp_path: Path) -> None:
        assert should_bootstrap(_settings(tmp_path)) is True


@pytest.mark.usefixtures("secrets_env")
class TestBuildDependencies:
    def test_constructs_real_wired_instances(self, tmp_path: Path) -> None:
        built = build_dependencies(_settings(tmp_path))

        assert isinstance(built.project_config, ProjectConfig)
        assert built.project_config.project.name == "My Tool"
        assert isinstance(built.github_client, GitHubClient)
        assert isinstance(built.run_controller, RunController)
        assert built.run_controller.project_name == "My Tool"
        assert built.run_controller.get_active_run() is None

        conn = sqlite3.connect(str(tmp_path / "state.db"))
        try:
            tables = {
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        finally:
            conn.close()
        assert "runs" in tables

    def test_missing_secret_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_PAT", raising=False)
        with pytest.raises(SecretResolutionError):
            build_dependencies(_settings(tmp_path))


@pytest.mark.usefixtures("secrets_env")
class TestCreateAppBootstrapWiring:
    def test_config_endpoint_boots_functional_not_stubbed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AUTH_PASSWORD_HASH", _TEST_HASH)

        app = create_app(_settings(tmp_path))
        client = TestClient(app, base_url="https://testserver")
        client.post("/login", json={"password": _TEST_PASSWORD})

        response = client.get("/config")

        assert response.status_code == 200
        assert response.json()["project_name"] == "My Tool"

    def test_run_status_boots_functional_not_stubbed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AUTH_PASSWORD_HASH", _TEST_HASH)

        app = create_app(_settings(tmp_path))
        client = TestClient(app, base_url="https://testserver")
        client.post("/login", json={"password": _TEST_PASSWORD})

        response = client.get("/runs/status")

        assert response.status_code == 200
        assert response.json() == {"active": False, "run": None}

    def test_start_run_boots_functional_not_stubbed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AUTH_PASSWORD_HASH", _TEST_HASH)

        app = create_app(_settings(tmp_path))
        client = TestClient(app, base_url="https://testserver")
        client.post("/login", json={"password": _TEST_PASSWORD})

        response = client.post("/runs/start", json={"wave": "Trivial milestone"})

        assert response.status_code == 201
        body = response.json()
        assert body["project"] == "My Tool"
        assert body["status"] == "running"


@pytest.mark.usefixtures("secrets_env")
class TestWaveRunFnLoadsCanonicalContent:
    """Guards against #250's regression: run_wave must receive the real
    canonical skills/base_prompts/overlays, not the empty placeholders
    build_dependencies shipped with before the canonical set existed.
    """

    @pytest.mark.anyio
    async def test_wave_run_fn_passes_real_canonical_content_to_run_wave(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        async def _fake_run_wave(**kwargs: Any) -> None:
            captured.update(kwargs)

        monkeypatch.setattr(bootstrap, "read_wave", lambda *a, **kw: object())
        monkeypatch.setattr(bootstrap, "load_execution_profile", lambda *a, **kw: object())
        monkeypatch.setattr(bootstrap, "get_adapter", lambda *a, **kw: object())
        monkeypatch.setattr(bootstrap, "run_wave", AsyncMock(side_effect=_fake_run_wave))

        built = build_dependencies(_settings(tmp_path))
        await built.wave_run_fn(1, "Trivial milestone", "claude")

        canonical = bootstrap._CANONICAL_DIR
        assert captured["skills"] == load_skills_from_directory(canonical / "skills")
        assert captured["base_prompts"] == load_base_prompts(canonical / "prompts")
        assert captured["overlays"] == load_overlays(canonical / "overlays")
        assert captured["skills"], "canonical skills must not be empty"
        assert captured["base_prompts"], "canonical base prompts must not be empty"
        assert captured["overlays"], "canonical overlays must not be empty"
