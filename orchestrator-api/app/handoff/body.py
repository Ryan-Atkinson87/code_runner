from __future__ import annotations

from app.gates.runner import GateRunResult, GateStatus
from app.handoff.models import HandoffInput


def _gate_label(gate_name: str) -> str:
    labels = {
        "test": "Tests pass",
        "lint": "Lint clean",
        "typecheck": "Typecheck clean",
    }
    return labels.get(gate_name, gate_name)


def engine_checks_from_gates(gate_results: list[GateRunResult]) -> list[str]:
    """Extract engine-verified check labels from gate run results.

    Only passed gates are included — failed/skipped/not-established gates
    are omitted from the pre-checked list.
    """
    checks: list[str] = []
    seen: set[str] = set()
    for run in gate_results:
        for gate in run.results:
            if gate.status == GateStatus.PASSED and gate.name not in seen:
                seen.add(gate.name)
                label = _gate_label(gate.name)
                checks.append(label)
    return checks


def assemble_pr_body(handoff: HandoffInput) -> str:
    """Assemble the structured PR body per Spec §5.4 step 3."""
    sections: list[str] = []

    sections.append(f"## Summary\n\n{handoff.summary}")

    if handoff.issue_notes:
        lines = [f"- Issue: #{n.number} — {n.summary}" for n in handoff.issue_notes]
        sections.append("## Issues\n\n" + "\n".join(lines))

    if handoff.engine_checks:
        lines = [f"- [x] {check}" for check in handoff.engine_checks]
        sections.append("## Engine-verified checks\n\n" + "\n".join(lines))

    if handoff.human_checks:
        lines = [f"- [ ] {check}" for check in handoff.human_checks]
        sections.append("## Human review checklist\n\n" + "\n".join(lines))

    if handoff.parked_blockers:
        lines = [f"- **#{b.issue_number}:** {b.reason}" for b in handoff.parked_blockers]
        sections.append("## Parked blockers\n\n" + "\n".join(lines))

    sections.append("---\n\n> CI must pass before merging.")

    return "\n\n".join(sections)
