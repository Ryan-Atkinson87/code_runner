from __future__ import annotations

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


class AgentsRenderer(InstructionRenderer):
    """Render instruction files in AGENTS.md format for Codex and Gemini.

    Produces a single ``AGENTS.md`` at the repo root containing the system
    prompt, engine contract, cross-cutting rules, and all stage skills
    inlined — no provider-specific skill-file layout.
    """

    def __init__(self, provider: str) -> None:
        self._provider = provider

    @property
    def provider(self) -> str:
        return self._provider

    def render(self, persona: ComposedPersona) -> RenderedOutput:
        skills = filter_skills_for_provider(persona.skills, self.provider)

        cross_cutting: list[Skill] = []
        stage_skills: list[Skill] = []
        for skill in skills:
            if skill.stage == SkillStage.CROSS_CUTTING:
                cross_cutting.append(skill)
            else:
                stage_skills.append(skill)

        content = _render_agents_md(persona, cross_cutting, stage_skills)
        return RenderedOutput(files={"AGENTS.md": content})


def _render_agents_md(
    persona: ComposedPersona,
    cross_cutting: list[Skill],
    stage_skills: list[Skill],
) -> str:
    parts: list[str] = []

    label = str(persona.persona_type)
    if persona.speciality:
        label = f"{persona.persona_type} × {persona.speciality}"
    parts.append(f"# {label}")

    parts.append(persona.system_prompt)
    parts.append(_ENGINE_CONTRACT)

    if cross_cutting:
        parts.append("## Cross-cutting rules")
        for skill in cross_cutting:
            if skill.body:
                parts.append(f"### {skill.id}\n\n{skill.body}")

    if stage_skills:
        parts.append("## Skills")
        for skill in stage_skills:
            if skill.body:
                parts.append(f"### {skill.id}\n\n{skill.body}")

    return "\n\n".join(parts) + "\n"
