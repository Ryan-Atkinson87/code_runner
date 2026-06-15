---
name: workflow-dependency-check
description: Verify that all dependencies for an issue are satisfied before beginning implementation. Use this skill after picking up an issue and before writing any code. Implementor agents only (backend, frontend).
---

Starting implementation against an unmet dependency produces work that has to be redone. This skill takes a few minutes and prevents hours of rework.

## Step 1: Read the issue body

Find every dependency statement in the issue body, in the format `Depends on: #[issue number]`.

If there are no dependency declarations, skip to Step 4.

## Step 2: Check each declared dependency

For each declared dependency, check its state (per `workflow-phase-issues`):

| State | Meaning |
|---|---|
| `Done` (closed) | Dependency is met. The interface or component exists on `main`. |
| `In Review` (open PR) | Dependency is not yet merged. Check if an adequate mock/stub exists (frontend only). |
| Not started / `Blocked` | Dependency has not landed. You are almost certainly blocked. |

## Step 3: Assess whether a mock is adequate (frontend only)

If a backend dependency is not yet merged, check whether an API mock exists for the interface:
- Open the mocks directory in `<FRONTEND_PATH>`
- Find the mock for the relevant endpoint
- Apply `workflow-api-contract-verification` to confirm the mock matches `docs/api.md`
- If the mock exists and matches the contract, the dependency is adequately stubbed and you may proceed
- If the mock does not exist or does not match the contract, treat this as a blocker

**Backend:** mocks do not apply. All in-repo dependencies must be merged before work begins, unless the dependency is purely a documented contract (`docs/api.md` / Specification) that already exists independent of the other issue's implementation.

## Step 4: Check the documented contract

Even if no dependency is declared, check the relevant contract for everything your implementation will call or implement (`workflow-api-contract-verification`):
- `ProviderAdapter` interface, config schema, or HTTP/SSE endpoint
- Confirm the shape is fully specified (no ambiguous fields, no missing types)
- If incomplete and you can't define it from the acceptance criteria, apply `workflow-blocker-escalation` before writing any code

## Step 5: Check for conflicting in-flight changes (backend, schema changes only)

If your change touches the SQLite schema, `project.yaml`, or `execution-profile.yaml`, check open PRs for other in-flight changes to the same files. Per Spec §18.6, only one issue per repo-area is normally active at a time, so this should be rare — but confirm before proceeding.

## Step 6: Proceed or escalate

**All dependencies met:** create your feature branch (`issue-<N>-<slug>` off `main`) and begin implementation.

**Any dependency unmet:** apply `workflow-blocker-escalation`. Do not begin implementation. Pick the next unblocked issue using `workflow-phase-issues`.
