---
name: process-plan-milestone
description: End-to-end process for planning a new milestone. Covers reading the Specification, creating GitHub issues, and handing off to implementors. Orchestrator only. Run this at the start of every new milestone.
---

This is the single entry point for planning a milestone. Work through each step in order and do not skip ahead.

## Step 1: Review the build plan

Open `docs/BUILD_PLAN.md` and read it in full before doing anything else.

Confirm:
- The milestone you are about to plan appears in the phases table and the phases it depends on are marked `✅`
- No earlier phase this milestone depends on is still `⬜` or `🔄`, which would make this milestone premature
- The phase structure still reflects reality — if completed work has revealed new dependencies or changed the sequencing, update `docs/BUILD_PLAN.md` now before creating any issues

If the plan needs restructuring, update `docs/BUILD_PLAN.md` first, then proceed.

## Step 2: Read the Specification

Apply `workflow-project-planning` — it walks through reading the relevant Specification sections and Spec §15 (Open Items), and flags any unresolved decision that would block the phase.

Do not proceed to Step 3 if `workflow-project-planning` surfaces an open item that directly affects the milestone scope. Create a blocker issue first using `workflow-blocker-escalation`, then plan around it.

## Step 3: Create the milestone and issues

Continue following `workflow-project-planning` through to completion:
- Define the milestone using the Spec §14 phase name
- Create the milestone in this repo
- Derive technical tasks and create GitHub issues with acceptance criteria, Specification links, and `Depends on: #N` declarations
- Sequence issues by dependency order

## Step 4: Communicate readiness to implementors

Once all issues are created:
- Confirm the backend and/or frontend implementor agents (whichever have work in this milestone) know it's ready
- State which issues are immediately workable (no unmet dependencies) and which are blocked pending other in-repo issues
- Implementors start with `process-implement-milestone`
