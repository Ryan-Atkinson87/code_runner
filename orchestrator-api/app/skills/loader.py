from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.skills.models import Skill

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)", re.DOTALL)


class SkillLoadError(Exception):
    pass


def _parse_skill_file(path: Path) -> Skill:
    """Parse a SKILL.md file into a Skill model.

    The file must contain YAML frontmatter (delimited by ``---``) with
    at least ``id``, ``stage``, and ``executor``. Everything after the
    closing ``---`` is the Markdown body.
    """
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise SkillLoadError(f"{path}: missing YAML frontmatter (expected ---\\n...\\n---)")

    raw_yaml = match.group(1)
    body = match.group(2).strip()

    try:
        meta = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        raise SkillLoadError(f"{path}: invalid YAML frontmatter: {exc}") from exc

    if not isinstance(meta, dict):
        kind = type(meta).__name__
        raise SkillLoadError(f"{path}: frontmatter must be a YAML mapping, got {kind}")

    meta["body"] = body

    try:
        return Skill.model_validate(meta)
    except ValidationError as exc:
        raise SkillLoadError(f"{path}: invalid skill metadata: {exc}") from exc


def load_skills_from_directory(directory: Path) -> list[Skill]:
    """Load all skills from a directory of ``<skill-id>/SKILL.md`` subdirs."""
    if not directory.is_dir():
        raise SkillLoadError(f"Skill directory does not exist: {directory}")

    skills: list[Skill] = []
    for child in sorted(directory.iterdir()):
        skill_file = child / "SKILL.md" if child.is_dir() else None
        if skill_file and skill_file.is_file():
            skills.append(_parse_skill_file(skill_file))

    return skills


def merge_skills(base: list[Skill], overrides: list[Skill]) -> list[Skill]:
    """Merge per-project overrides into the tool-level base set.

    A per-project skill with the same ``id`` replaces the base skill
    entirely. New ids are appended.
    """
    merged: dict[str, Skill] = {s.id: s for s in base}
    for skill in overrides:
        merged[skill.id] = skill
    return list(merged.values())


def load_and_merge(
    base_dir: Path,
    project_dir: Path | None = None,
) -> list[Skill]:
    """Load the base skill set, optionally merging per-project overrides."""
    base = load_skills_from_directory(base_dir)

    if project_dir is not None and project_dir.is_dir():
        overrides = load_skills_from_directory(project_dir)
        return merge_skills(base, overrides)

    return base
