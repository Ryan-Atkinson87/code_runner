import pytest

from app.secrets.resolver import SecretResolutionError, resolve_secrets


def test_resolve_all_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_PAT", "ghp_abc123")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xyz")
    secrets_map = {
        "github_pat": "GITHUB_PAT",
        "anthropic_api_key": "ANTHROPIC_API_KEY",
    }
    result = resolve_secrets(secrets_map)
    assert result["github_pat"] == "ghp_abc123"
    assert result["anthropic_api_key"] == "sk-ant-xyz"


def test_resolve_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_VAR", raising=False)
    monkeypatch.delenv("ALSO_MISSING", raising=False)
    secrets_map = {
        "first": "MISSING_VAR",
        "second": "ALSO_MISSING",
    }
    with pytest.raises(SecretResolutionError, match="MISSING_VAR"):
        resolve_secrets(secrets_map)


def test_resolve_partial_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRESENT_VAR", "value")
    monkeypatch.delenv("ABSENT_VAR", raising=False)
    secrets_map = {
        "present": "PRESENT_VAR",
        "absent": "ABSENT_VAR",
    }
    with pytest.raises(SecretResolutionError, match="ABSENT_VAR"):
        resolve_secrets(secrets_map)


def test_resolve_empty_map() -> None:
    result = resolve_secrets({})
    assert result == {}


def test_error_message_includes_all_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("A_VAR", raising=False)
    monkeypatch.delenv("B_VAR", raising=False)
    secrets_map = {"a": "A_VAR", "b": "B_VAR"}
    with pytest.raises(SecretResolutionError) as exc_info:
        resolve_secrets(secrets_map)
    msg = str(exc_info.value)
    assert "A_VAR" in msg
    assert "B_VAR" in msg


def test_error_does_not_leak_resolved_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRESENT_VAR", "super-secret-value")
    monkeypatch.delenv("MISSING_VAR", raising=False)
    with pytest.raises(SecretResolutionError) as exc_info:
        resolve_secrets({"present": "PRESENT_VAR", "missing": "MISSING_VAR"})
    assert "super-secret-value" not in str(exc_info.value)
