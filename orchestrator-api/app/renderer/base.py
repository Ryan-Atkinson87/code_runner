from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, Field

from app.personas.models import ComposedPersona
from app.skills.models import Skill


class RenderedOutput(BaseModel):
    """In-memory representation of rendered instruction files.

    Separates generation from I/O so tests can inspect content
    without touching the filesystem.
    """

    files: dict[str, str] = Field(default_factory=dict)

    def write_to(self, workdir: Path) -> list[Path]:
        """Write all rendered files into the working directory."""
        written: list[Path] = []
        for rel_path, content in self.files.items():
            full = workdir / rel_path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")
            written.append(full)
        return written


def applies_to_provider(skill: Skill, provider: str) -> bool:
    if skill.applies_to == "neutral":
        return True
    if isinstance(skill.applies_to, str):
        return skill.applies_to == provider
    return provider in skill.applies_to


def filter_skills_for_provider(skills: list[Skill], provider: str) -> list[Skill]:
    return [s for s in skills if applies_to_provider(s, provider)]


class InstructionRenderer(ABC):
    """Base class for provider-specific instruction file renderers."""

    @property
    @abstractmethod
    def provider(self) -> str: ...

    @abstractmethod
    def render(self, persona: ComposedPersona) -> RenderedOutput: ...
