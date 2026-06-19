from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from app.skills.models import Skill


class PersonaType(StrEnum):
    PLANNER = "planner"
    IMPLEMENTOR = "implementor"
    REVIEWER = "reviewer"
    QA_REVIEWER = "qa-reviewer"
    TECH_LEAD = "tech-lead"


class Overlay(BaseModel):
    """Speciality overlay — structured like a skill (metadata + body).

    Adding a speciality is writing an overlay, not a new agent (Spec §17.4).
    """

    speciality: str
    description: str = ""
    body: str = ""


class ComposedPersona(BaseModel):
    """A fully composed persona ready for provider rendering (Spec §17.4).

    Composition produces an instruction set — it does not hold session
    state. Each composed persona maps to exactly one fresh provider
    session per task (§4.3).
    """

    persona_type: PersonaType
    speciality: str
    system_prompt: str
    skills: list[Skill] = Field(default_factory=list)
