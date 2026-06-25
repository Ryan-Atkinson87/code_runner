from __future__ import annotations

import pytest

from app.personas.composer import (
    PersonaCompositionError,
    compose_persona,
    filter_skills_for_persona,
)
from app.personas.models import ComposedPersona, Overlay, PersonaType
from app.skills.models import Skill, SkillExecutor, SkillStage


def _skill(
    skill_id: str,
    stage: SkillStage = SkillStage.IMPLEMENT,
    specialities: list[str] | None = None,
    executor: SkillExecutor = "ai",
) -> Skill:
    return Skill(
        id=skill_id,
        stage=stage,
        executor=executor,
        specialities=specialities or [],
        body=f"Body of {skill_id}",
    )


BASE_PROMPTS: dict[PersonaType, str] = {
    PersonaType.PLANNER: "You are a planner.",
    PersonaType.IMPLEMENTOR: "You are an implementor.",
    PersonaType.REVIEWER: "You are a reviewer.",
    PersonaType.QA_REVIEWER: "You are a QA reviewer.",
    PersonaType.TECH_LEAD: "You are the tech lead.",
}


class TestPersonaType:
    def test_all_five_types(self) -> None:
        assert len(PersonaType) == 5
        assert set(PersonaType) == {
            PersonaType.PLANNER,
            PersonaType.IMPLEMENTOR,
            PersonaType.REVIEWER,
            PersonaType.QA_REVIEWER,
            PersonaType.TECH_LEAD,
        }

    def test_string_values(self) -> None:
        assert PersonaType.QA_REVIEWER == "qa-reviewer"
        assert PersonaType.TECH_LEAD == "tech-lead"


class TestOverlay:
    def test_minimal(self) -> None:
        overlay = Overlay(speciality="backend")
        assert overlay.speciality == "backend"
        assert overlay.body == ""

    def test_with_body(self) -> None:
        overlay = Overlay(
            speciality="frontend",
            description="Frontend focus",
            body="Use React and Vite.",
        )
        assert overlay.body == "Use React and Vite."


class TestFilterSkillsForPersona:
    def test_implementor_backend_excludes_accessibility(self) -> None:
        skills = [
            _skill("coding", SkillStage.IMPLEMENT, []),
            _skill("wcag", SkillStage.IMPLEMENT, ["accessibility"]),
            _skill("api-check", SkillStage.CONTRACT_VERIFY, ["backend"]),
        ]
        result = filter_skills_for_persona(skills, PersonaType.IMPLEMENTOR, "backend")
        ids = [s.id for s in result]
        assert "coding" in ids
        assert "api-check" in ids
        assert "wcag" not in ids

    def test_qa_reviewer_accessibility_includes_accessibility(self) -> None:
        skills = [
            _skill("wcag", SkillStage.QA, ["accessibility"]),
            _skill("responsive", SkillStage.QA, ["responsiveness"]),
            _skill("general-qa", SkillStage.QA, []),
        ]
        result = filter_skills_for_persona(skills, PersonaType.QA_REVIEWER, "accessibility")
        ids = [s.id for s in result]
        assert "wcag" in ids
        assert "general-qa" in ids
        assert "responsive" not in ids

    def test_neutral_skills_included_for_any_speciality(self) -> None:
        skills = [_skill("universal", SkillStage.IMPLEMENT, [])]
        result = filter_skills_for_persona(skills, PersonaType.IMPLEMENTOR, "anything")
        assert len(result) == 1

    def test_stage_mismatch_excluded(self) -> None:
        skills = [_skill("plan-skill", SkillStage.PLAN, [])]
        result = filter_skills_for_persona(skills, PersonaType.IMPLEMENTOR, "backend")
        assert len(result) == 0

    def test_cross_cutting_always_included(self) -> None:
        skills = [_skill("blocker", SkillStage.CROSS_CUTTING, [])]
        result = filter_skills_for_persona(skills, PersonaType.REVIEWER, "backend")
        assert len(result) == 1

    def test_escalate_always_included(self) -> None:
        skills = [_skill("escalation", SkillStage.ESCALATE, [])]
        result = filter_skills_for_persona(skills, PersonaType.IMPLEMENTOR, "frontend")
        assert len(result) == 1

    def test_engine_executor_excluded(self) -> None:
        skills = [_skill("engine-only", SkillStage.IMPLEMENT, [], executor="engine")]
        result = filter_skills_for_persona(skills, PersonaType.IMPLEMENTOR, "backend")
        assert len(result) == 0

    def test_planner_gets_plan_skills(self) -> None:
        skills = [
            _skill("planning", SkillStage.PLAN, []),
            _skill("coding", SkillStage.IMPLEMENT, []),
        ]
        result = filter_skills_for_persona(skills, PersonaType.PLANNER, "backend")
        ids = [s.id for s in result]
        assert "planning" in ids
        assert "coding" not in ids

    def test_reviewer_gets_review_skills(self) -> None:
        skills = [
            _skill("code-review", SkillStage.REVIEW, []),
            _skill("testing", SkillStage.TEST, []),
        ]
        result = filter_skills_for_persona(skills, PersonaType.REVIEWER, "backend")
        ids = [s.id for s in result]
        assert "code-review" in ids
        assert "testing" not in ids

    def test_tech_lead_gets_plan_implement_integrate(self) -> None:
        skills = [
            _skill("plan", SkillStage.PLAN, []),
            _skill("impl", SkillStage.IMPLEMENT, []),
            _skill("integ", SkillStage.INTEGRATE, []),
            _skill("review", SkillStage.REVIEW, []),
        ]
        result = filter_skills_for_persona(skills, PersonaType.TECH_LEAD, "backend")
        ids = [s.id for s in result]
        assert "plan" in ids
        assert "impl" in ids
        assert "integ" in ids
        assert "review" not in ids

    def test_implementor_gets_test_and_contract_verify(self) -> None:
        skills = [
            _skill("impl", SkillStage.IMPLEMENT, []),
            _skill("test", SkillStage.TEST, []),
            _skill("contract", SkillStage.CONTRACT_VERIFY, []),
        ]
        result = filter_skills_for_persona(skills, PersonaType.IMPLEMENTOR, "backend")
        assert len(result) == 3

    def test_multiple_specialities_on_skill(self) -> None:
        skills = [_skill("multi", SkillStage.IMPLEMENT, ["backend", "frontend"])]
        assert len(filter_skills_for_persona(skills, PersonaType.IMPLEMENTOR, "backend")) == 1
        assert len(filter_skills_for_persona(skills, PersonaType.IMPLEMENTOR, "frontend")) == 1
        assert len(filter_skills_for_persona(skills, PersonaType.IMPLEMENTOR, "security")) == 0

    def test_empty_skills_list(self) -> None:
        result = filter_skills_for_persona([], PersonaType.IMPLEMENTOR, "backend")
        assert result == []


class TestComposePersona:
    def test_basic_composition(self) -> None:
        result = compose_persona(
            PersonaType.IMPLEMENTOR,
            "backend",
            BASE_PROMPTS,
            [],
            [],
        )
        assert isinstance(result, ComposedPersona)
        assert result.persona_type == PersonaType.IMPLEMENTOR
        assert result.speciality == "backend"
        assert "You are an implementor." in result.system_prompt

    def test_overlay_appended(self) -> None:
        overlays = [
            Overlay(speciality="backend", body="Focus on Python and FastAPI."),
            Overlay(speciality="frontend", body="Focus on React and Vite."),
        ]
        result = compose_persona(
            PersonaType.IMPLEMENTOR,
            "backend",
            BASE_PROMPTS,
            overlays,
            [],
        )
        assert "You are an implementor." in result.system_prompt
        assert "Focus on Python and FastAPI." in result.system_prompt

    def test_wrong_overlay_not_included(self) -> None:
        overlays = [Overlay(speciality="frontend", body="React stuff")]
        result = compose_persona(
            PersonaType.IMPLEMENTOR,
            "backend",
            BASE_PROMPTS,
            overlays,
            [],
        )
        assert "React stuff" not in result.system_prompt

    def test_skills_filtered(self) -> None:
        skills = [
            _skill("coding", SkillStage.IMPLEMENT, []),
            _skill("wcag", SkillStage.IMPLEMENT, ["accessibility"]),
        ]
        result = compose_persona(
            PersonaType.IMPLEMENTOR,
            "backend",
            BASE_PROMPTS,
            [],
            skills,
        )
        ids = [s.id for s in result.skills]
        assert "coding" in ids
        assert "wcag" not in ids

    def test_unknown_type_errors(self) -> None:
        with pytest.raises(PersonaCompositionError, match="No base prompt"):
            compose_persona(
                PersonaType.IMPLEMENTOR,
                "backend",
                {},
                [],
                [],
            )

    def test_no_overlay_still_works(self) -> None:
        result = compose_persona(
            PersonaType.REVIEWER,
            "security",
            BASE_PROMPTS,
            [],
            [],
        )
        assert result.system_prompt == "You are a reviewer."

    def test_full_composition(self) -> None:
        overlays = [Overlay(speciality="backend", body="Python/FastAPI specialist.")]
        skills = [
            _skill("workflow-testing", SkillStage.TEST, []),
            _skill("workflow-coding", SkillStage.IMPLEMENT, ["backend"]),
            _skill("wcag-check", SkillStage.QA, ["accessibility"]),
            _skill("blocker-escalation", SkillStage.ESCALATE, []),
        ]
        result = compose_persona(
            PersonaType.IMPLEMENTOR,
            "backend",
            BASE_PROMPTS,
            overlays,
            skills,
        )
        assert result.persona_type == PersonaType.IMPLEMENTOR
        assert result.speciality == "backend"
        assert "You are an implementor." in result.system_prompt
        assert "Python/FastAPI specialist." in result.system_prompt
        skill_ids = [s.id for s in result.skills]
        assert "workflow-testing" in skill_ids
        assert "workflow-coding" in skill_ids
        assert "blocker-escalation" in skill_ids
        assert "wcag-check" not in skill_ids

    def test_composed_persona_has_no_session_state(self) -> None:
        compose_persona(
            PersonaType.IMPLEMENTOR,
            "backend",
            BASE_PROMPTS,
            [],
            [],
        )
        fields = set(ComposedPersona.model_fields.keys())
        assert fields == {"persona_type", "speciality", "system_prompt", "skills"}


class TestComposedPersona:
    def test_serializes_cleanly(self) -> None:
        persona = ComposedPersona(
            persona_type=PersonaType.IMPLEMENTOR,
            speciality="backend",
            system_prompt="You are an implementor.",
            skills=[_skill("test-skill", SkillStage.IMPLEMENT)],
        )
        data = persona.model_dump()
        assert data["persona_type"] == "implementor"
        assert data["speciality"] == "backend"
        assert len(data["skills"]) == 1
