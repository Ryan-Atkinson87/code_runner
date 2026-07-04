from __future__ import annotations

from pathlib import Path

import pytest

from app.personas.composer import compose_persona
from app.personas.loader import (
    PersonaContentLoadError,
    load_base_prompts,
    load_overlays,
)
from app.personas.models import PersonaType
from app.skills.loader import load_skills_from_directory

_CANONICAL = Path(__file__).parent.parent / "canonical"
_SKILLS_DIR = _CANONICAL / "skills"
_PROMPTS_DIR = _CANONICAL / "prompts"
_OVERLAYS_DIR = _CANONICAL / "overlays"


class TestLoadBasePrompts:
    def test_loads_all_five_persona_types(self) -> None:
        prompts = load_base_prompts(_PROMPTS_DIR)

        assert set(prompts) == set(PersonaType)
        for persona_type, text in prompts.items():
            assert text.strip(), f"{persona_type} prompt is empty"

    def test_missing_directory_raises(self, tmp_path: Path) -> None:
        with pytest.raises(PersonaContentLoadError):
            load_base_prompts(tmp_path / "does-not-exist")


class TestLoadOverlays:
    def test_loads_backend_overlay(self) -> None:
        overlays = load_overlays(_OVERLAYS_DIR)

        specialities = {o.speciality for o in overlays}
        assert "backend" in specialities
        backend = next(o for o in overlays if o.speciality == "backend")
        assert backend.body.strip()

    def test_missing_directory_raises(self, tmp_path: Path) -> None:
        with pytest.raises(PersonaContentLoadError):
            load_overlays(tmp_path / "does-not-exist")


class TestCanonicalSetComposesEndToEnd:
    def test_implementor_backend_composes_without_error(self) -> None:
        skills = load_skills_from_directory(_SKILLS_DIR)
        base_prompts = load_base_prompts(_PROMPTS_DIR)
        overlays = load_overlays(_OVERLAYS_DIR)

        persona = compose_persona(
            PersonaType.IMPLEMENTOR,
            "backend",
            base_prompts,
            overlays,
            skills,
        )

        assert persona.system_prompt.strip()
        assert any(s.id == "implement" for s in persona.skills)
        assert any(s.id == "cross-cutting-boundaries" for s in persona.skills)

    def test_reviewer_composes_without_error(self) -> None:
        skills = load_skills_from_directory(_SKILLS_DIR)
        base_prompts = load_base_prompts(_PROMPTS_DIR)
        overlays = load_overlays(_OVERLAYS_DIR)

        persona = compose_persona(
            PersonaType.REVIEWER,
            "backend",
            base_prompts,
            overlays,
            skills,
        )

        assert persona.system_prompt.strip()
        assert any(s.id == "review" for s in persona.skills)
