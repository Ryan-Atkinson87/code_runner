---
name: process-implement-milestone
description: End-to-end process for implementing all issues in a milestone. Entry point for any implementor agent starting work on a milestone. Handles issue sequencing, dependency checking, implementation, testing, and PR creation for every issue until the milestone is fully in review. Implementor agents only (backend, frontend).
---

This is the single entry point for implementing a milestone. Run it at the start of every session — including sessions with cleared context. It reads live state from GitHub each time, so it always picks up exactly where the milestone left off regardless of what happened in a previous session.

Do not pick up individual issues without running this process — it ensures issues are worked in the correct order and nothing is missed.

## Step 1: Environment check (backend only)

If you are the backend implementor and this is the first session of a new milestone, apply `workflow-env-verification` before touching any code. Confirm the local state store, `project.yaml`/`execution-profile.yaml`, required secrets, and the Docker Compose stack are all correct (whichever of these already exist at this stage of the build).

If you have run `workflow-env-verification` in a previous session for this milestone and nothing has changed locally, you may skip this step.

The frontend implementor always skips to Step 2.

## Step 2: Orient — apply `workflow-phase-issues`

**Run this step every time this process starts, including from a fresh or cleared context.**

Apply `workflow-phase-issues`. It reads the current state of issues in this milestone directly from GitHub, so it does not rely on any prior session memory. It will:
- List all open issues in the current milestone
- Classify each as not started, in progress with no PR (discarded per Spec §18.4), `In Review`, or `Blocked`
- Order remaining work by dependency
- Select the single next issue to work on

If `workflow-phase-issues` finds no open issues remaining, this milestone is complete — notify the orchestrator to run `process-close-milestone`.

## Step 3: Work the current issue

Work through the following steps in order for the issue selected in Step 2. Do not skip steps.

**3a. Dependency check**
Apply `workflow-dependency-check`. Confirm all in-repo dependencies are met or adequately mocked (frontend only). If any are unmet, apply `workflow-blocker-escalation` and return to Step 2 to pick the next unblocked issue.

**3b. Implement**
Implement against the acceptance criteria in the issue body. Reference the Specification for any detail not in the issue. Use the Read, Edit, and Write tools to modify files — never `sed`, `awk`, or shell redirects.

If implementation reveals work not covered by this or any other issue, apply `workflow-phase-issues` Step 5 (mid-milestone discoveries) before continuing.

**3c. Test**
Apply `workflow-testing`. Run the full suite for every area touched. Do not open a PR with a failing test. If failures cannot be resolved without a decision, apply `workflow-blocker-escalation`.

**3d. Contract check**
- Backend: apply `workflow-api-contract-verification` for every `ProviderAdapter` implementation, config schema, or endpoint added or changed.
- Frontend: apply `workflow-api-contract-verification` only when switching an endpoint from a mock to live. Skip this step if staying on a mock.

**3e. Open the PR**
Apply `workflow-pr-creation`. Work through the full checklist before opening. PRs target `main` with `Closes #N`.

**3f. Sync**
Apply `workflow-notion-sync` (a no-op for this project at the per-issue level — see that skill).

## Step 4: Repeat

Return to Step 2. `workflow-phase-issues` will read the updated state and select the next issue. Continue until all issues in the milestone are `Done` or `In Review`.

## Step 5: Notify the orchestrator

Once all remaining issues are `In Review` (every open PR exists), notify the orchestrator that the milestone is ready for review. The orchestrator will run `process-review-pr` for each open PR.
