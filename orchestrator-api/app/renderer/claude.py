from __future__ import annotations

import yaml

from app.personas.models import ComposedPersona
from app.renderer.base import InstructionRenderer, RenderedOutput, filter_skills_for_provider
from app.skills.models import Skill, SkillStage

_ENGINE_CONTRACT = """\
## Engine contract

The deterministic engine handles the following — do not replicate these:

- **Git operations:** branch creation/deletion, merge, rebase, push.
- **Test/lint/typecheck gating:** runs gates and routes failures back to you.
- **Issue selection:** dependency-order wave assembly and scheduling.
- **PR mechanics:** feature-branch PRs, hand-off PRs, review state.
- **Tracker sync:** GitHub board, Notion, Social Media Context.
- **Usage monitoring:** meters, pause/resume, concurrency cap step-down.

Focus on the task given in your prompt. The engine will tell you when
a gate fails and feed the output back for you to fix."""


class ClaudeRenderer(InstructionRenderer):
    """Render instruction files in Claude Code's expected layout.

    Produces ``CLAUDE.md`` at the repo root (system prompt + engine
    contract + cross-cutting rules) and per-skill files under
    ``.claude/skills/<id>/SKILL.md``.
    """

    @property
    def provider(self) -> str:
        return "claude"

    def render(self, persona: ComposedPersona) -> RenderedOutput:
        skills = filter_skills_for_provider(persona.skills, self.provider)

        cross_cutting: list[Skill] = []
        stage_skills: list[Skill] = []
        for skill in skills:
            if skill.stage == SkillStage.CROSS_CUTTING:
                cross_cutting.append(skill)
            else:
                stage_skills.append(skill)

        files: dict[str, str] = {}
        files["CLAUDE.md"] = _render_claude_md(persona, cross_cutting)

        for skill in stage_skills:
            rel_path = f".claude/skills/{skill.id}/SKILL.md"
            files[rel_path] = _render_skill_file(skill)

        return RenderedOutput(files=files)


def _render_claude_md(persona: ComposedPersona, cross_cutting_skills: list[Skill]) -> str:
    parts: list[str] = []

    label = str(persona.persona_type)
    if persona.speciality:
        label = f"{persona.persona_type} × {persona.speciality}"
    parts.append(f"# {label}")

    parts.append(persona.system_prompt)
    parts.append(_ENGINE_CONTRACT)

    if cross_cutting_skills:
        parts.append("## Cross-cutting rules")
        for skill in cross_cutting_skills:
            if skill.body:
                parts.append(f"### {skill.id}\n\n{skill.body}")

    return "\n\n".join(parts) + "\n"


def _render_skill_file(skill: Skill) -> str:
    meta: dict[str, object] = {
        "id": skill.id,
        "stage": str(skill.stage),
        "executor": skill.executor,
        "applies_to": skill.applies_to,
    }
    if skill.specialities:
        meta["specialities"] = skill.specialities
    if skill.description:
        meta["description"] = skill.description

    frontmatter = yaml.dump(meta, default_flow_style=False, sort_keys=False).rstrip()
    parts = [f"---\n{frontmatter}\n---"]
    if skill.body:
        parts.append(skill.body)
    return "\n".join(parts) + "\n"
