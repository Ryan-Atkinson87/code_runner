from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


def test_health_returns_200() -> None:
    app = create_app(Settings())
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "orchestrator-api"


def test_create_app_uses_default_settings() -> None:
    app = create_app()
    assert app.title == "orchestrator-api"
