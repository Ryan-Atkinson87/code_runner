import os
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.config.schema import ProjectConfig


class ConfigError(Exception):
    pass


def save_project_config(config: ProjectConfig, path: str | Path) -> None:
    path = Path(path)
    data = config.model_dump(by_alias=True)
    content = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def load_project_config(path: str | Path) -> ProjectConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")

    raw = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {path}: {e}") from e

    if not isinstance(data, dict):
        actual = type(data).__name__
        raise ConfigError(f"Expected a YAML mapping at top level in {path}, got {actual}")

    try:
        return ProjectConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"Config validation failed for {path}:\n{e}") from e
