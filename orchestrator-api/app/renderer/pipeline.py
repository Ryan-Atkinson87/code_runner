from __future__ import annotations

from app.personas.composer import compose_persona
from app.personas.models import Overlay, PersonaType
from app.profile.schema import ExecutionProfile
from app.renderer.base import InstructionRenderer, RenderedOutput
from app.renderer.claude import ClaudeRenderer
from app.skills.models import Skill


def _get_renderer(provider: str) -> InstructionRenderer:
    if provider == "claude":
        return ClaudeRenderer()
    raise NotImplementedError(
        f"Instruction renderer for provider '{provider}' is not yet implemented (Phase 7)"
    )


def compose_and_render(
    profile: ExecutionProfile,
    skills: list[Skill],
    base_prompts: dict[PersonaType, str],
    overlays: list[Overlay],
    provider: str,
) -> dict[str, RenderedOutput]:
    """Full rendering pipeline: profile -> compose each persona -> render.

    Returns a mapping of persona key -> RenderedOutput. The engine
    writes a specific persona's output to disk before each session.
    """
    renderer = _get_renderer(provider)
    result: dict[str, RenderedOutput] = {}

    for entry in profile.personas:
        persona = compose_persona(
            persona_type=PersonaType(entry.type),
            speciality=entry.speciality or "",
            base_prompts=base_prompts,
            overlays=overlays,
            skills=skills,
        )
        output = renderer.render(persona)
        result[entry.key] = output

    return result
