from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from app.profile.schema import ExecutionProfile


class ProfileLoadError(Exception):
    pass


def load_execution_profile(path: str | Path) -> ExecutionProfile:
    """Load and validate an execution-profile.yaml file.

    Follows the same fail-fast pattern as the project.yaml loader:
    a malformed profile errors before any wave begins.
    """
    path = Path(path)
    if not path.exists():
        raise ProfileLoadError(f"Execution profile not found: {path}")

    raw = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ProfileLoadError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(data, dict):
        actual = type(data).__name__
        raise ProfileLoadError(f"Expected a YAML mapping at top level in {path}, got {actual}")

    try:
        return ExecutionProfile.model_validate(data)
    except ValidationError as exc:
        raise ProfileLoadError(f"Profile validation failed for {path}:\n{exc}") from exc
