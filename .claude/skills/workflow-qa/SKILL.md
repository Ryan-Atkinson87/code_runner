---
name: workflow-qa
description: End-to-end QA run against a completed milestone. Use this skill after all issues in a milestone are closed and before the milestone is marked complete. Orchestrator only.
---

QA runs against the local Docker Compose stack built from `main` — not a feature branch, and not against mocks. All milestone work has already merged by this point (each PR closed its issue directly via `Closes #N`).

**Division of responsibility:**
- **Orchestrator verifies**: anything reachable via the API (`docs/api.md`), CLI, filesystem, git, or SQLite state — status codes, response shapes, error contracts, created branches/PRs, state-store rows, log output. These go into the milestone summary as already-checked, not as open checkboxes.
- **Human verifies**: anything that requires eyes on a real browser (visual layout, UX flows, keyboard/focus behaviour) or a real external service (an actual Telegram message arriving, an actual GitHub PR appearing as expected, an actual Notion page update visible, real AI provider session behaviour that can't be fully simulated). Only these go into the milestone summary as open checkboxes.
- If a milestone has no UI changes and no externally-observable integrations, there may be nothing for the human to check. Omit the human checklist entirely in that case.

## Step 1: Verify the environment is running

Apply `workflow-deployment-verification` first if it hasn't already been run for this milestone — it confirms the stack is healthy and running the latest `main` before testing begins.

Do not start or stop services yourself beyond what `workflow-deployment-verification` already covers.

## Step 2: Identify the scope

List every issue closed in this milestone and what it added or changed. Group by area, using Specification §12 categories where the change is UI-facing (run control, live progress, usage monitor, blocker list, PR surfacing, efficiency reports, notifications, config view), and by component where it's backend-only (provider adapters, git/PR engine, tracker sync, config loaders, etc.).

Only test what was added or changed in this milestone. Regression testing of untouched areas is out of scope unless a change could plausibly have affected them.

## Step 3: Happy path testing

For each area in scope, derive the happy path from its issues' acceptance criteria and exercise it:

- **HTTP/SSE endpoints**: call them directly (curl/httpie) against `docs/api.md` — verify status codes, response shapes, and that the error contract matches the documentation
- **UI screens**: orchestrator verifies the underlying API calls directly (as above); human verifies the rendered screen in browser (open checkbox)
- **Deterministic engine components with no HTTP surface** (e.g. git/PR engine, wave-loop sequencing, tracker sync): exercise via their CLI entrypoint or test harness; orchestrator verifies the resulting state directly — branches created, PR bodies, SQLite rows, files written
- **Provider adapter behaviour**: orchestrator verifies the adapter's deterministic surface (inputs/outputs, error handling); a live AI session round-trip, if not already covered by automated tests, is a human-checked item

## Step 4: Error state testing

For each area in scope, test the primary failure paths implied by its acceptance criteria, e.g.:
- Invalid or missing input to an endpoint → expected `4xx` and error body shape
- An operation that depends on an unmet precondition (missing secret, unmet `Depends on:`, failing test) → expected blocker/error behaviour, not a silent no-op or crash
- A provider/API call that fails or times out → expected retry/error-surfacing behaviour, not a swallowed exception

## Step 5: Log findings

For each failure found, create a GitHub issue in this repo:

**Title:** `[QA] [milestone name] — [one line description of failure]`

**Body must include:**
- Steps to reproduce (numbered, exact)
- Expected behaviour (reference the Specification or issue acceptance criteria)
- Actual behaviour
- Environment (command/endpoint, any relevant state)
- Severity: `critical` (blocks the milestone), `major` (significant impact), `minor` (cosmetic or edge case)

Assign the issue to the current milestone. Add a `bug` label. Apply `workflow-notion-sync` (a no-op at this level — see that skill).

## Step 6: Determine milestone outcome

- If any `critical` bugs are found, the milestone is not complete. Assign the bugs to the relevant implementor and do not apply `workflow-milestone-completion` until they are resolved.
- If only `major` or `minor` bugs are found, use judgement: majors should be fixed before completion, minors can be tracked as follow-up issues in the next milestone.
- If no bugs are found, apply `workflow-milestone-completion`.
