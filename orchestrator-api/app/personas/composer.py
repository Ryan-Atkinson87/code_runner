from __future__ import annotations

from app.personas.models import ComposedPersona, Overlay, PersonaType
from app.skills.models import Skill, SkillStage

_TYPE_STAGES: dict[PersonaType, frozenset[SkillStage]] = {
    PersonaType.PLANNER: frozenset({SkillStage.PLAN}),
    PersonaType.IMPLEMENTOR: frozenset(
        {SkillStage.IMPLEMENT, SkillStage.TEST, SkillStage.CONTRACT_VERIFY}
    ),
    PersonaType.REVIEWER: frozenset({SkillStage.REVIEW}),
    PersonaType.QA_REVIEWER: frozenset({SkillStage.QA}),
    PersonaType.TECH_LEAD: frozenset({SkillStage.PLAN, SkillStage.IMPLEMENT, SkillStage.INTEGRATE}),
}

_ALWAYS_MATCH_STAGES: frozenset[SkillStage] = frozenset(
    {SkillStage.CROSS_CUTTING, SkillStage.ESCALATE}
)


class PersonaCompositionError(Exception):
    pass


def filter_skills_for_persona(
    skills: list[Skill],
    persona_type: PersonaType,
    speciality: str,
) -> list[Skill]:
    """Filter skills to those relevant for a given persona type and speciality.

    A skill is included if:
    1. Its ``stage`` matches the persona type's relevant stages (or is
       cross-cutting/escalate), AND
    2. Its ``specialities`` list is empty (neutral — applies to all
       specialities) OR contains the persona's speciality, AND
    3. Its ``executor`` is ``"ai"`` (engine-executor skills are not
       rendered into AI sessions — Spec §17.7).
    """
    relevant_stages = _TYPE_STAGES.get(persona_type, frozenset())
    matched: list[Skill] = []
    for skill in skills:
        if skill.executor != "ai":
            continue
        if skill.stage not in relevant_stages and skill.stage not in _ALWAYS_MATCH_STAGES:
            continue
        if skill.specialities and speciality not in skill.specialities:
            continue
        matched.append(skill)
    return matched


def compose_persona(
    persona_type: PersonaType,
    speciality: str,
    base_prompts: dict[PersonaType, str],
    overlays: list[Overlay],
    skills: list[Skill],
) -> ComposedPersona:
    """Compose a runnable persona from type × speciality (Spec §17.4).

    Args:
        persona_type: One of the fixed persona types.
        speciality: Open-ended speciality string (e.g. "backend", "frontend").
        base_prompts: Mapping of persona type to its base system prompt.
        overlays: Available speciality overlays.
        skills: Full skill set (will be filtered).

    Returns:
        A ``ComposedPersona`` with the assembled system prompt and
        the filtered skill list.

    Raises:
        PersonaCompositionError: If the persona type has no base prompt.
    """
    if persona_type not in base_prompts:
        raise PersonaCompositionError(f"No base prompt defined for persona type '{persona_type}'")

    parts = [base_prompts[persona_type]]

    overlay = next((o for o in overlays if o.speciality == speciality), None)
    if overlay:
        parts.append(overlay.body)

    filtered = filter_skills_for_persona(skills, persona_type, speciality)

    return ComposedPersona(
        persona_type=persona_type,
        speciality=speciality,
        system_prompt="\n\n".join(parts),
        skills=filtered,
    )
