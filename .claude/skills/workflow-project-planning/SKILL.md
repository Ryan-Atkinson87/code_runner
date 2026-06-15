---
name: workflow-project-planning
description: How to plan a new phase or milestone from scratch. Use this skill when a new milestone needs to be defined, when the current milestone completes and the next phase needs scoping, or when new requirements arrive that need translating into issues. Orchestrator only.
---

Planning produces GitHub issues. It does not produce code. All decisions about shape, contract, and behaviour must be traceable to the Specification.

## Step 1: Read the relevant Specification sections

Before creating anything, read the Specification sections relevant to this phase's scope — identify them by what the phase covers (e.g. config/schema work → Spec §16/§17; provider adapter work → Spec §3; git/PR engine and branch model → Spec §5/§7/§18; UI work → Spec §12; tracker sync → Spec §18.5/§9).

Also read **Spec §15 (Open items to resolve)** regardless of phase — check for unresolved decisions that affect this phase's scope.

If any open item directly affects the phase scope, do not plan issues for the affected work. Create a single blocker issue instead using `workflow-blocker-escalation`, then plan around it.

## Step 2: Define the milestone

Milestones = Spec §14 build phases (per `CLAUDE.md`). Confirm the milestone name matches the phase name in Spec §14, or document a refinement in `docs/BUILD_PLAN.md` if the phase needs splitting.

Create the milestone in this repo if it doesn't already exist. Set a due date if one has been agreed.

## Step 3: Derive technical tasks

From the Specification sections read in Step 1, produce a list of technical tasks for the phase. For each task:
- Confirm it is not already represented by an open issue
- Identify any dependencies on other issues in this repo (`Depends on: #N`)
- Identify any ordering constraints (e.g. a config loader must exist before code that reads it)

If a task is infrastructure/tooling/config rather than a feature or bugfix, it's a chore — label it accordingly in Step 4.

## Step 4: Create GitHub issues

For each task, create an issue:

**Title:** Imperative and specific. e.g. `Add project.yaml loader with Pydantic validation`, not `Config loader`

**Body must include:**
- Link to the relevant Specification section(s), e.g. "Spec §16.3"
- Acceptance criteria as a checkbox list, derived directly from the Specification
- Dependencies explicitly named: `Depends on: #[issue number]`
- Any constraints from Spec §15 Open Items that affect implementation

**Labels:** `enhancement`, `bug`, `chore`, `blocked` — create labels if they do not exist in the repo (per `CLAUDE.md`).

**Milestone:** Assign to the milestone created in Step 2.

**Build plan:** Immediately after creating the issue, add `- [ ] #<N> — <title>` under this
phase's "Issues" heading in `docs/BUILD_PLAN.md`, replacing the "Not yet planned" placeholder if
this is the first issue for the phase.

## Step 5: Sequence the issues

Order issues within the milestone by dependency. Add ordering notes to issue bodies where the sequence is not obvious from the dependency declarations alone.

Reorder the checklist rows in `docs/BUILD_PLAN.md` to match this sequence — `workflow-phase-issues` Step 3 uses the same dependency order.

## Step 6: Final check

For each new issue, confirm:
- It has a milestone (Step 2)
- It has at least one label (Step 4)
- Its dependencies, if any, are declared (`Depends on: #N`)
- It has a corresponding `- [ ] #N — Title` row under this phase in `docs/BUILD_PLAN.md`

No project board or per-issue Notion sync is needed (per `CLAUDE.md`) — `workflow-notion-sync` at this level is a no-op.
