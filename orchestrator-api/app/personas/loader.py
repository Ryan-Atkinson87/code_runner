from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.personas.models import Overlay, PersonaType

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)", re.DOTALL)


class PersonaContentLoadError(Exception):
    pass


def load_base_prompts(directory: Path) -> dict[PersonaType, str]:
    """Load per-persona-type base system prompts from ``<type>.md`` files.

    Unlike skills and overlays, base prompts carry no frontmatter (Spec
    §17.4) — the whole file is the prompt text. A project need not define
    every persona type; ``compose_persona`` raises for any type actually
    used that has none.
    """
    if not directory.is_dir():
        raise PersonaContentLoadError(f"Base-prompt directory does not exist: {directory}")

    prompts: dict[PersonaType, str] = {}
    for persona_type in PersonaType:
        path = directory / f"{persona_type.value}.md"
        if path.is_file():
            prompts[persona_type] = path.read_text(encoding="utf-8").strip()

    return prompts


def _parse_overlay_file(path: Path) -> Overlay:
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise PersonaContentLoadError(
            f"{path}: missing YAML frontmatter (expected ---\\n...\\n---)"
        )

    raw_yaml = match.group(1)
    body = match.group(2).strip()

    try:
        meta = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        raise PersonaContentLoadError(f"{path}: invalid YAML frontmatter: {exc}") from exc

    if not isinstance(meta, dict):
        kind = type(meta).__name__
        raise PersonaContentLoadError(f"{path}: frontmatter must be a YAML mapping, got {kind}")

    meta["body"] = body

    try:
        return Overlay.model_validate(meta)
    except ValidationError as exc:
        raise PersonaContentLoadError(f"{path}: invalid overlay metadata: {exc}") from exc


def load_overlays(directory: Path) -> list[Overlay]:
    """Load all overlays from a directory of ``<speciality>/OVERLAY.md`` subdirs."""
    if not directory.is_dir():
        raise PersonaContentLoadError(f"Overlay directory does not exist: {directory}")

    overlays: list[Overlay] = []
    for child in sorted(directory.iterdir()):
        overlay_file = child / "OVERLAY.md" if child.is_dir() else None
        if overlay_file and overlay_file.is_file():
            overlays.append(_parse_overlay_file(overlay_file))

    return overlays
