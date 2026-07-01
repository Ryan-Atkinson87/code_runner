from __future__ import annotations

import pytest

from app.personas.composer import compose_persona
from app.personas.models import ComposedPersona, Overlay, PersonaType
from app.profile.schema import ExecutionProfile, PersonaEntry
from app.renderer import AgentsRenderer, ClaudeRenderer, get_renderer
from app.renderer.base import (
    RenderedOutput,
    applies_to_provider,
    filter_skills_for_provider,
)
from app.renderer.pipeline import compose_and_render
from app.skills.loader import _parse_skill_file
from app.skills.models import Skill, SkillExecutor, SkillStage


def _skill(
    skill_id: str,
    stage: SkillStage = SkillStage.IMPLEMENT,
    specialities: list[str] | None = None,
    executor: SkillExecutor = "ai",
    applies_to: str | list[str] = "neutral",
    body: str = "",
) -> Skill:
    return Skill(
        id=skill_id,
        stage=stage,
        executor=executor,
        specialities=specialities or [],
        applies_to=applies_to,
        body=body or f"Body of {skill_id}",
    )


BASE_PROMPTS: dict[PersonaType, str] = {
    PersonaType.PLANNER: "You are a planner.",
    PersonaType.IMPLEMENTOR: "You are an implementor.",
    PersonaType.REVIEWER: "You are a reviewer.",
    PersonaType.QA_REVIEWER: "You are a QA reviewer.",
    PersonaType.TECH_LEAD: "You are the tech lead.",
}


def _backend_implementor(skills: list[Skill] | None = None) -> ComposedPersona:
    return compose_persona(
        PersonaType.IMPLEMENTOR,
        "backend",
        BASE_PROMPTS,
        [Overlay(speciality="backend", body="Focus on Python.")],
        skills or [],
    )


class TestAppliesToProvider:
    def test_neutral_matches_any(self) -> None:
        s = _skill("x", applies_to="neutral")
        assert applies_to_provider(s, "claude")
        assert applies_to_provider(s, "codex")
        assert applies_to_provider(s, "gemini")

    def test_exact_string_match(self) -> None:
        s = _skill("x", applies_to="claude")
        assert applies_to_provider(s, "claude")
        assert not applies_to_provider(s, "codex")

    def test_list_contains(self) -> None:
        s = _skill("x", applies_to=["claude", "codex"])
        assert applies_to_provider(s, "claude")
        assert applies_to_provider(s, "codex")
        assert not applies_to_provider(s, "gemini")


class TestFilterSkillsForProvider:
    def test_excludes_wrong_provider(self) -> None:
        skills = [
            _skill("neutral-skill"),
            _skill("codex-only", applies_to="codex"),
            _skill("claude-only", applies_to="claude"),
        ]
        result = filter_skills_for_provider(skills, "claude")
        ids = [s.id for s in result]
        assert "neutral-skill" in ids
        assert "claude-only" in ids
        assert "codex-only" not in ids

    def test_empty_list(self) -> None:
        assert filter_skills_for_provider([], "claude") == []


class TestRenderedOutput:
    def test_write_to_creates_files(self, tmp_path: object) -> None:
        import pathlib

        wd = pathlib.Path(str(tmp_path))
        output = RenderedOutput(
            files={
                "CLAUDE.md": "# test\n",
                ".claude/skills/my-skill/SKILL.md": "---\nid: my-skill\n---\nbody\n",
            }
        )
        written = output.write_to(wd)
        assert len(written) == 2
        assert (wd / "CLAUDE.md").read_text() == "# test\n"
        assert (wd / ".claude/skills/my-skill/SKILL.md").exists()

    def test_write_to_creates_parent_dirs(self, tmp_path: object) -> None:
        import pathlib

        wd = pathlib.Path(str(tmp_path))
        output = RenderedOutput(files={"deep/nested/dir/file.txt": "content"})
        output.write_to(wd)
        assert (wd / "deep/nested/dir/file.txt").read_text() == "content"

    def test_empty_files(self, tmp_path: object) -> None:
        import pathlib

        wd = pathlib.Path(str(tmp_path))
        output = RenderedOutput(files={})
        written = output.write_to(wd)
        assert written == []


class TestClaudeRenderer:
    def test_renders_claude_md_at_root(self) -> None:
        persona = _backend_implementor()
        renderer = ClaudeRenderer()
        output = renderer.render(persona)
        assert "CLAUDE.md" in output.files
        content = output.files["CLAUDE.md"]
        assert "implementor × backend" in content
        assert "You are an implementor." in content
        assert "Engine contract" in content

    def test_system_prompt_in_claude_md(self) -> None:
        persona = _backend_implementor()
        renderer = ClaudeRenderer()
        output = renderer.render(persona)
        content = output.files["CLAUDE.md"]
        assert "Focus on Python." in content

    def test_stage_skills_as_skill_files(self) -> None:
        skills = [
            _skill("workflow-testing", SkillStage.TEST),
            _skill("workflow-coding", SkillStage.IMPLEMENT, ["backend"]),
        ]
        persona = _backend_implementor(skills)
        renderer = ClaudeRenderer()
        output = renderer.render(persona)
        assert ".claude/skills/workflow-testing/SKILL.md" in output.files
        assert ".claude/skills/workflow-coding/SKILL.md" in output.files

    def test_cross_cutting_inline_in_claude_md(self) -> None:
        skills = [
            _skill("boundaries", SkillStage.CROSS_CUTTING, body="Never leave the repo."),
            _skill("coding", SkillStage.IMPLEMENT),
        ]
        persona = _backend_implementor(skills)
        renderer = ClaudeRenderer()
        output = renderer.render(persona)
        content = output.files["CLAUDE.md"]
        assert "Cross-cutting rules" in content
        assert "Never leave the repo." in content
        assert ".claude/skills/boundaries/SKILL.md" not in output.files
        assert ".claude/skills/coding/SKILL.md" in output.files

    def test_engine_executor_skills_excluded(self) -> None:
        skills = [
            _skill("ai-skill", SkillStage.IMPLEMENT, executor="ai"),
            _skill("engine-skill", SkillStage.IMPLEMENT, executor="engine"),
        ]
        persona = _backend_implementor(skills)
        renderer = ClaudeRenderer()
        output = renderer.render(persona)
        assert ".claude/skills/ai-skill/SKILL.md" in output.files
        assert ".claude/skills/engine-skill/SKILL.md" not in output.files
        assert "engine-skill" not in output.files["CLAUDE.md"]

    def test_provider_tagged_skill_filtered_out(self) -> None:
        skills = [
            _skill("codex-sandbox", SkillStage.IMPLEMENT, applies_to="codex"),
            _skill("claude-perms", SkillStage.IMPLEMENT, applies_to="claude"),
        ]
        persona = _backend_implementor(skills)
        renderer = ClaudeRenderer()
        output = renderer.render(persona)
        assert ".claude/skills/claude-perms/SKILL.md" in output.files
        assert ".claude/skills/codex-sandbox/SKILL.md" not in output.files

    def test_neutral_skill_included(self) -> None:
        skills = [_skill("universal", SkillStage.IMPLEMENT, applies_to="neutral")]
        persona = _backend_implementor(skills)
        renderer = ClaudeRenderer()
        output = renderer.render(persona)
        assert ".claude/skills/universal/SKILL.md" in output.files

    def test_backend_persona_excludes_accessibility_skills(self) -> None:
        skills = [
            _skill("coding", SkillStage.IMPLEMENT, []),
            _skill("wcag", SkillStage.IMPLEMENT, ["accessibility"]),
            _skill("api-check", SkillStage.CONTRACT_VERIFY, ["backend"]),
        ]
        persona = _backend_implementor(skills)
        renderer = ClaudeRenderer()
        output = renderer.render(persona)
        all_content = "\n".join(output.files.values())
        assert "coding" in all_content
        assert "api-check" in all_content
        assert "wcag" not in all_content

    def test_no_skills_renders_only_claude_md(self) -> None:
        persona = _backend_implementor()
        renderer = ClaudeRenderer()
        output = renderer.render(persona)
        assert len(output.files) == 1
        assert "CLAUDE.md" in output.files

    def test_persona_without_speciality(self) -> None:
        persona = compose_persona(PersonaType.PLANNER, "", BASE_PROMPTS, [], [])
        renderer = ClaudeRenderer()
        output = renderer.render(persona)
        content = output.files["CLAUDE.md"]
        assert "# planner" in content
        assert "×" not in content

    def test_escalate_skills_as_skill_files(self) -> None:
        skills = [_skill("blocker-detect", SkillStage.ESCALATE)]
        persona = _backend_implementor(skills)
        renderer = ClaudeRenderer()
        output = renderer.render(persona)
        assert ".claude/skills/blocker-detect/SKILL.md" in output.files

    def test_skill_file_round_trips_through_loader(self, tmp_path: object) -> None:
        import pathlib

        wd = pathlib.Path(str(tmp_path))
        skill = _skill(
            "test-skill",
            SkillStage.IMPLEMENT,
            specialities=["backend"],
            body="Do the thing.",
        )
        persona = _backend_implementor([skill])
        renderer = ClaudeRenderer()
        output = renderer.render(persona)
        output.write_to(wd)

        reloaded = _parse_skill_file(wd / ".claude/skills/test-skill/SKILL.md")
        assert reloaded.id == "test-skill"
        assert reloaded.stage == SkillStage.IMPLEMENT
        assert reloaded.executor == "ai"
        assert reloaded.body == "Do the thing."

    def test_skill_file_preserves_applies_to_list(self, tmp_path: object) -> None:
        import pathlib

        wd = pathlib.Path(str(tmp_path))
        skill = _skill(
            "multi-provider",
            SkillStage.IMPLEMENT,
            applies_to=["claude", "codex"],
            body="Works on both.",
        )
        persona = _backend_implementor([skill])
        renderer = ClaudeRenderer()
        output = renderer.render(persona)
        output.write_to(wd)

        reloaded = _parse_skill_file(wd / ".claude/skills/multi-provider/SKILL.md")
        assert reloaded.applies_to == ["claude", "codex"]


class TestAgentsRenderer:
    def test_renders_agents_md_at_root(self) -> None:
        persona = _backend_implementor()
        renderer = AgentsRenderer("codex")
        output = renderer.render(persona)
        assert "AGENTS.md" in output.files
        assert len(output.files) == 1

    def test_agents_md_contains_persona_header_and_prompt(self) -> None:
        persona = _backend_implementor()
        renderer = AgentsRenderer("codex")
        output = renderer.render(persona)
        content = output.files["AGENTS.md"]
        assert "implementor × backend" in content
        assert "You are an implementor." in content

    def test_agents_md_contains_engine_contract(self) -> None:
        persona = _backend_implementor()
        renderer = AgentsRenderer("codex")
        output = renderer.render(persona)
        assert "Engine contract" in output.files["AGENTS.md"]

    def test_stage_skills_inlined_not_as_files(self) -> None:
        skills = [_skill("workflow-testing", SkillStage.TEST, body="Run tests.")]
        persona = _backend_implementor(skills)
        renderer = AgentsRenderer("codex")
        output = renderer.render(persona)
        assert "AGENTS.md" in output.files
        assert len(output.files) == 1
        assert "workflow-testing" in output.files["AGENTS.md"]
        assert "Run tests." in output.files["AGENTS.md"]

    def test_cross_cutting_inlined_under_own_section(self) -> None:
        skills = [
            _skill("boundaries", SkillStage.CROSS_CUTTING, body="Stay in bounds."),
            _skill("coding", SkillStage.IMPLEMENT, body="Write code."),
        ]
        persona = _backend_implementor(skills)
        renderer = AgentsRenderer("gemini")
        output = renderer.render(persona)
        content = output.files["AGENTS.md"]
        assert "Cross-cutting rules" in content
        assert "Stay in bounds." in content
        assert "Skills" in content
        assert "Write code." in content

    def test_engine_executor_skills_excluded(self) -> None:
        skills = [
            _skill("ai-skill", SkillStage.IMPLEMENT, executor="ai", body="Do this."),
            _skill("engine-skill", SkillStage.IMPLEMENT, executor="engine", body="Engine only."),
        ]
        persona = _backend_implementor(skills)
        renderer = AgentsRenderer("codex")
        output = renderer.render(persona)
        content = output.files["AGENTS.md"]
        assert "ai-skill" in content
        assert "engine-skill" not in content

    def test_provider_tagged_skills_filtered(self) -> None:
        skills = [
            _skill("codex-rule", SkillStage.IMPLEMENT, applies_to="codex", body="Codex only."),
            _skill("claude-rule", SkillStage.IMPLEMENT, applies_to="claude", body="Claude only."),
            _skill("shared", SkillStage.IMPLEMENT, applies_to="neutral", body="Shared."),
        ]
        persona = _backend_implementor(skills)
        renderer = AgentsRenderer("codex")
        output = renderer.render(persona)
        content = output.files["AGENTS.md"]
        assert "Codex only." in content
        assert "Claude only." not in content
        assert "Shared." in content

    def test_gemini_filters_codex_skills(self) -> None:
        skills = [
            _skill("codex-rule", SkillStage.IMPLEMENT, applies_to="codex", body="Codex only."),
            _skill("gemini-rule", SkillStage.IMPLEMENT, applies_to="gemini", body="Gemini only."),
        ]
        persona = _backend_implementor(skills)
        renderer = AgentsRenderer("gemini")
        output = renderer.render(persona)
        content = output.files["AGENTS.md"]
        assert "Gemini only." in content
        assert "Codex only." not in content

    def test_no_skills_renders_only_agents_md(self) -> None:
        persona = _backend_implementor()
        renderer = AgentsRenderer("codex")
        output = renderer.render(persona)
        assert len(output.files) == 1
        assert "AGENTS.md" in output.files

    def test_persona_without_speciality(self) -> None:
        persona = compose_persona(PersonaType.PLANNER, "", BASE_PROMPTS, [], [])
        renderer = AgentsRenderer("gemini")
        output = renderer.render(persona)
        content = output.files["AGENTS.md"]
        assert "# planner" in content
        assert "×" not in content

    def test_codex_and_gemini_produce_identical_structure(self) -> None:
        skills = [
            _skill("shared", SkillStage.IMPLEMENT, applies_to="neutral", body="Works everywhere.")
        ]
        persona = _backend_implementor(skills)
        codex_output = AgentsRenderer("codex").render(persona)
        gemini_output = AgentsRenderer("gemini").render(persona)
        assert codex_output.files["AGENTS.md"] == gemini_output.files["AGENTS.md"]

    def test_no_claude_skill_files_produced(self) -> None:
        skills = [_skill("my-skill", SkillStage.IMPLEMENT, body="Do it.")]
        persona = _backend_implementor(skills)
        renderer = AgentsRenderer("codex")
        output = renderer.render(persona)
        assert not any(k.startswith(".claude/") for k in output.files)


class TestGetRenderer:
    def test_claude(self) -> None:
        renderer = get_renderer("claude")
        assert isinstance(renderer, ClaudeRenderer)
        assert renderer.provider == "claude"

    def test_codex(self) -> None:
        renderer = get_renderer("codex")
        assert isinstance(renderer, AgentsRenderer)
        assert renderer.provider == "codex"

    def test_gemini(self) -> None:
        renderer = get_renderer("gemini")
        assert isinstance(renderer, AgentsRenderer)
        assert renderer.provider == "gemini"

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(NotImplementedError):
            get_renderer("unknown-provider")


class TestComposeAndRender:
    def test_full_pipeline(self) -> None:
        profile = ExecutionProfile(
            personas=[
                PersonaEntry(
                    type=PersonaType.IMPLEMENTOR,
                    speciality="backend",
                ),
                PersonaEntry(
                    type=PersonaType.REVIEWER,
                    speciality="backend",
                ),
            ]
        )
        skills = [
            _skill("coding", SkillStage.IMPLEMENT),
            _skill("code-review", SkillStage.REVIEW),
            _skill("boundaries", SkillStage.CROSS_CUTTING, body="Stay in lane."),
        ]
        result = compose_and_render(
            profile=profile,
            skills=skills,
            base_prompts=BASE_PROMPTS,
            overlays=[],
            provider="claude",
        )
        assert "implementor×backend" in result
        assert "reviewer×backend" in result

        impl_output = result["implementor×backend"]
        assert "CLAUDE.md" in impl_output.files
        assert ".claude/skills/coding/SKILL.md" in impl_output.files
        assert ".claude/skills/code-review/SKILL.md" not in impl_output.files

        review_output = result["reviewer×backend"]
        assert ".claude/skills/code-review/SKILL.md" in review_output.files
        assert ".claude/skills/coding/SKILL.md" not in review_output.files

    def test_pipeline_includes_cross_cutting_for_all(self) -> None:
        profile = ExecutionProfile(
            personas=[
                PersonaEntry(
                    type=PersonaType.IMPLEMENTOR,
                    speciality="backend",
                ),
                PersonaEntry(
                    type=PersonaType.REVIEWER,
                    speciality="backend",
                ),
            ]
        )
        skills = [
            _skill("boundaries", SkillStage.CROSS_CUTTING, body="Stay in lane."),
        ]
        result = compose_and_render(
            profile=profile,
            skills=skills,
            base_prompts=BASE_PROMPTS,
            overlays=[],
            provider="claude",
        )
        for key, output in result.items():
            assert "Stay in lane." in output.files["CLAUDE.md"], f"Missing for {key}"

    def test_pipeline_filters_provider_skills(self) -> None:
        profile = ExecutionProfile(
            personas=[
                PersonaEntry(
                    type=PersonaType.IMPLEMENTOR,
                    speciality="backend",
                ),
            ]
        )
        skills = [
            _skill("claude-rule", SkillStage.IMPLEMENT, applies_to="claude"),
            _skill("codex-rule", SkillStage.IMPLEMENT, applies_to="codex"),
        ]
        result = compose_and_render(
            profile=profile,
            skills=skills,
            base_prompts=BASE_PROMPTS,
            overlays=[],
            provider="claude",
        )
        output = result["implementor×backend"]
        assert ".claude/skills/claude-rule/SKILL.md" in output.files
        assert ".claude/skills/codex-rule/SKILL.md" not in output.files

    def test_pipeline_writes_to_disk(self, tmp_path: object) -> None:
        import pathlib

        wd = pathlib.Path(str(tmp_path))
        profile = ExecutionProfile(
            personas=[
                PersonaEntry(
                    type=PersonaType.IMPLEMENTOR,
                    speciality="backend",
                ),
            ]
        )
        skills = [_skill("coding", SkillStage.IMPLEMENT)]
        result = compose_and_render(
            profile=profile,
            skills=skills,
            base_prompts=BASE_PROMPTS,
            overlays=[],
            provider="claude",
        )
        output = result["implementor×backend"]
        written = output.write_to(wd)
        assert len(written) == 2
        assert (wd / "CLAUDE.md").exists()
        assert (wd / ".claude/skills/coding/SKILL.md").exists()

    def test_codex_pipeline_produces_agents_md(self) -> None:
        profile = ExecutionProfile(
            personas=[
                PersonaEntry(
                    type=PersonaType.IMPLEMENTOR,
                    speciality="backend",
                ),
            ]
        )
        skills = [
            _skill("coding", SkillStage.IMPLEMENT, body="Write code."),
            _skill("boundaries", SkillStage.CROSS_CUTTING, body="Stay in bounds."),
        ]
        result = compose_and_render(
            profile=profile,
            skills=skills,
            base_prompts=BASE_PROMPTS,
            overlays=[],
            provider="codex",
        )
        output = result["implementor×backend"]
        assert "AGENTS.md" in output.files
        assert "CLAUDE.md" not in output.files
        content = output.files["AGENTS.md"]
        assert "Write code." in content
        assert "Stay in bounds." in content

    def test_gemini_pipeline_produces_agents_md(self) -> None:
        profile = ExecutionProfile(
            personas=[
                PersonaEntry(
                    type=PersonaType.IMPLEMENTOR,
                    speciality="backend",
                ),
            ]
        )
        skills = [_skill("coding", SkillStage.IMPLEMENT, body="Write code.")]
        result = compose_and_render(
            profile=profile,
            skills=skills,
            base_prompts=BASE_PROMPTS,
            overlays=[],
            provider="gemini",
        )
        output = result["implementor×backend"]
        assert "AGENTS.md" in output.files
        assert "CLAUDE.md" not in output.files
