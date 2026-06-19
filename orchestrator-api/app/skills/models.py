from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class SkillStage(StrEnum):
    PLAN = "plan"
    IMPLEMENT = "implement"
    TEST = "test"
    CONTRACT_VERIFY = "contract-verify"
    REVIEW = "review"
    QA = "qa"
    INTEGRATE = "integrate"
    ESCALATE = "escalate"
    CROSS_CUTTING = "cross-cutting"


SkillExecutor = Literal["ai", "engine"]


class Skill(BaseModel):
    """A single canonical skill (Spec §17.3).

    Provider-neutral rule unit: metadata + Markdown body. Composition
    into personas is handled downstream (#20); rendering is #22.
    """

    id: str
    stage: SkillStage
    executor: SkillExecutor
    applies_to: str | list[str] = "neutral"
    specialities: list[str] = Field(default_factory=list)
    description: str = ""
    body: str = ""
