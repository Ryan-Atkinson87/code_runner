from pathlib import Path

import pytest

from app.config.loader import ConfigError, load_project_config

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_minimal_example() -> None:
    cfg = load_project_config(FIXTURES / "minimal_project.yaml")
    assert cfg.project.name == "My Tool"
    assert cfg.project.root == "/projects/my-tool"
    assert cfg.integrations.github.owner == "my-user"
    assert len(cfg.repos) == 1
    assert cfg.repos[0].commands.test == "pnpm test"
    assert cfg.secrets["github_pat"] == "GITHUB_PAT"


def test_load_trive_example() -> None:
    cfg = load_project_config(FIXTURES / "trive_project.yaml")
    assert cfg.project.name == "Trive Services"
    assert len(cfg.repos) == 3
    assert cfg.repos[0].backend is True
    assert cfg.repos[1].backend is False
    assert cfg.provider.default == "claude"
    assert cfg.provider.models.planning == "claude-opus-4-8"
    assert cfg.limits.test_fix_attempts == 3
    assert cfg.limits.review_cycles == 2


def test_defaults_applied() -> None:
    cfg = load_project_config(FIXTURES / "minimal_project.yaml")
    assert cfg.branches.integration == "dev"
    assert cfg.branches.agent_pattern == "code-runner/<wave-slug>"
    assert cfg.branches.sync_strategy == "merge"
    assert cfg.waves.source == "milestone-name"
    assert cfg.provider.default == "claude"
    assert cfg.usage.threshold_percent == 80
    assert cfg.usage.peak_hour_throttle is True
    assert cfg.notifications.telegram is True
    assert cfg.notifications.email is False
    assert cfg.limits.test_fix_attempts == 3
    assert cfg.limits.review_cycles == 2


def test_missing_required_project_key(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("""
integrations:
  github:
    owner: x
repos:
  - name: r
secrets:
  github_pat: GITHUB_PAT
""")
    with pytest.raises(ConfigError, match="project"):
        load_project_config(p)


def test_missing_required_integrations_key(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("""
project:
  name: X
repos:
  - name: r
secrets:
  github_pat: GITHUB_PAT
""")
    with pytest.raises(ConfigError, match="integrations"):
        load_project_config(p)


def test_missing_required_repos_key(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("""
project:
  name: X
integrations:
  github:
    owner: x
secrets:
  github_pat: GITHUB_PAT
""")
    with pytest.raises(ConfigError, match="repos"):
        load_project_config(p)


def test_missing_required_secrets_key(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("""
project:
  name: X
integrations:
  github:
    owner: x
repos:
  - name: r
""")
    with pytest.raises(ConfigError, match="secrets"):
        load_project_config(p)


def test_invalid_yaml(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("{{{{invalid yaml")
    with pytest.raises(ConfigError, match="Invalid YAML"):
        load_project_config(p)


def test_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_project_config(tmp_path / "nope.yaml")


def test_non_mapping_yaml(tmp_path: Path) -> None:
    p = tmp_path / "list.yaml"
    p.write_text("- a\n- b\n")
    with pytest.raises(ConfigError, match="mapping"):
        load_project_config(p)


def test_secrets_are_string_names_only() -> None:
    cfg = load_project_config(FIXTURES / "minimal_project.yaml")
    for key, val in cfg.secrets.items():
        assert isinstance(key, str)
        assert isinstance(val, str)
        assert val.isupper() or "_" in val
