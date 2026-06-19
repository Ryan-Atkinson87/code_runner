from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.config.schema import ProjectConfig
from app.profile.schema import ExecutionProfile
from app.providers.adapter import ProviderAdapter
from app.providers.types import EventKind, SessionOutcome, SessionResult, SessionRole


class ProposalOutcome(StrEnum):
    PROPOSED = "proposed"
    VALIDATION_ERROR = "validation_error"
    SESSION_ERROR = "session_error"


@dataclass
class ProfileProposal:
    raw_yaml: str
    profile: ExecutionProfile
    session: SessionResult


@dataclass
class ProfileGenerationResult:
    outcome: ProposalOutcome
    proposal: ProfileProposal | None = None
    error: str = ""


async def generate_proposal(
    project_config: ProjectConfig,
    repo_paths: list[Path],
    adapter: ProviderAdapter,
    model: str,
) -> ProfileGenerationResult:
    """Run a tech-lead session to propose an execution-profile.yaml.

    The proposal must validate against the ExecutionProfile schema
    before it is returned. The caller presents it for human
    confirmation before writing — see ``confirm_and_write``.
    """
    scan = _scan_repos(repo_paths)
    prompt = _build_proposal_prompt(project_config, scan)

    session = await adapter.run_session(
        workdir=repo_paths[0] if repo_paths else Path("."),
        role=SessionRole.ORCHESTRATOR,
        model=model,
        allowed_tools=[],
        prompt=prompt,
        context_files=[],
    )

    if session.outcome != SessionOutcome.COMPLETED:
        return ProfileGenerationResult(
            outcome=ProposalOutcome.SESSION_ERROR,
            error=f"Session ended with outcome: {session.outcome}",
        )

    text = _extract_text(session)
    raw_yaml = _extract_yaml(text)

    try:
        data = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        return ProfileGenerationResult(
            outcome=ProposalOutcome.VALIDATION_ERROR,
            error=f"Invalid YAML in proposal: {exc}",
        )

    if not isinstance(data, dict):
        return ProfileGenerationResult(
            outcome=ProposalOutcome.VALIDATION_ERROR,
            error=f"Expected YAML mapping, got {type(data).__name__}",
        )

    try:
        profile = ExecutionProfile.model_validate(data)
    except ValidationError as exc:
        return ProfileGenerationResult(
            outcome=ProposalOutcome.VALIDATION_ERROR,
            error=f"Profile validation failed:\n{exc}",
        )

    return ProfileGenerationResult(
        outcome=ProposalOutcome.PROPOSED,
        proposal=ProfileProposal(raw_yaml=raw_yaml, profile=profile, session=session),
    )


def confirm_and_write(proposal: ProfileProposal, output_path: Path) -> Path:
    """Write the confirmed profile to disk.

    This is the confirm-before-write gate: the caller must have
    presented the proposal for human confirmation before calling.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(proposal.raw_yaml, encoding="utf-8")
    return output_path


def needs_regeneration(
    current_profile_path: Path,
    project_config: ProjectConfig,
    repo_paths: list[Path],
) -> bool:
    """Detect whether a structural change warrants re-generating the profile.

    Checks for: repos declared in project.yaml that don't have a profile,
    new config files appearing (pyproject.toml, package.json, tsconfig.json),
    or the profile file not existing.
    """
    if not current_profile_path.exists():
        return True

    configured_repos = {r.name for r in project_config.repos}
    scanned_dirs = {p.name for p in repo_paths if p.is_dir()}
    if configured_repos - scanned_dirs:
        return True

    _STRUCTURAL_MARKERS = (
        "pyproject.toml",
        "package.json",
        "tsconfig.json",
        "Cargo.toml",
        "go.mod",
    )
    current_text = current_profile_path.read_text(encoding="utf-8")

    for path in repo_paths:
        for marker in _STRUCTURAL_MARKERS:
            marker_path = path / marker
            if marker_path.exists() and path.name not in current_text:
                return True

    return False


def _extract_text(session: SessionResult) -> str:
    parts = [e.content for e in session.events if e.kind == EventKind.OUTPUT and e.content]
    return "\n".join(parts)


def _extract_yaml(text: str) -> str:
    match = re.search(r"```ya?ml\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _scan_repos(repo_paths: list[Path]) -> str:
    parts: list[str] = []
    for path in repo_paths:
        if not path.is_dir():
            continue
        parts.append(f"### {path.name}\n\n")
        for entry in sorted(path.iterdir()):
            if entry.name.startswith(".") and entry.name != ".github":
                continue
            suffix = "/" if entry.is_dir() else ""
            parts.append(f"  {entry.name}{suffix}\n")
        for cfg in ("pyproject.toml", "package.json", "tsconfig.json"):
            cfg_path = path / cfg
            if cfg_path.exists():
                content = cfg_path.read_text(encoding="utf-8")[:2000]
                parts.append(f"\n#### {cfg}\n```\n{content}\n```\n")
    return "".join(parts)


def _build_proposal_prompt(project_config: ProjectConfig, scan: str) -> str:
    repos_desc = ", ".join(r.name for r in project_config.repos)
    return (
        "You are the tech-lead persona. Propose an execution-profile.yaml "
        "for this project.\n\n"
        "Based on the project configuration and repo scan below, determine:\n"
        "- Which persona compositions to instantiate (type x speciality)\n"
        "- Which stages run AI vs engine\n"
        "- Routing (which persona handles which repo)\n"
        "- QA specialities that apply\n"
        "- Any project-specific skill overrides\n\n"
        "Output the profile as a YAML code block (```yaml ... ```).\n\n"
        f"## Project: {project_config.project.name}\n\n"
        f"Repos: {repos_desc}\n"
        f"Provider: {project_config.provider.default}\n\n"
        f"## Repo scan\n\n{scan}"
    )
