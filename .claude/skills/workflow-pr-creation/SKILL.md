---
name: workflow-pr-creation
description: Checklist to complete before opening a PR. Use this skill after implementation is done and tests pass, before opening the pull request. Implementor agents only (backend, frontend).
---

A PR that fails this checklist will be returned by the orchestrator. Work through every item before opening.

## Pre-flight checks

Complete these in order. Do not open the PR until all are confirmed.

### 0. Scope

- [ ] Open the linked GitHub issue. Read the description and every acceptance criterion.
- [ ] Every AC is satisfied by this PR — not partially, not "good enough". If an AC cannot be met, apply `workflow-blocker-escalation` rather than opening the PR.
- [ ] The implementation covers **only** what the issue requires. No extra features, no refactors beyond the issue scope, no speculative additions. If you found something worth fixing, open a new issue for it.

### 1. Tests

- [ ] The test command for every area you changed passes with zero failures (see `CLAUDE.md` for backend/frontend commands). If a command is still a placeholder, note that explicitly in the PR.
- [ ] No tests have been skipped or deleted without explanation in the PR description

### 2. Spec compliance

**All changes:**
- [ ] Read every acceptance criterion in the issue. Copy the checkbox list into the PR body (Section 5 below) and tick each one — this is a claim that the code satisfies it, not a formatting exercise.

**Backend (`<BACKEND_PATH>`):**
- [ ] Applied `workflow-api-contract-verification` for every `ProviderAdapter` implementation, config schema, or HTTP/SSE endpoint added or changed
- [ ] All deviations from the Specification or `docs/api.md` are resolved or escalated

**Frontend (`<FRONTEND_PATH>`):**
- [ ] Compared every changed screen against the UI scope in Specification §12
- [ ] All screen states are implemented: loading, empty, error, populated
- [ ] Applied `workflow-api-contract-verification` for every endpoint consumed or mocked in this PR — verify shapes directly against `docs/api.md`, not from existing types, fixtures, or other handler definitions. This applies to new mocks and to updates of existing ones.
- [ ] Mock handlers match `docs/api.md` exactly (confirmed by the step above)
- [ ] `workflow-api-contract-verification` applied if switching an endpoint from a mock to the live API in this PR

### 3. Production readiness

Every change ships to the running tool. Confirm the change meets the bar defined in `CLAUDE.md`. If a shortcut would compromise any item, stop and choose the proper solution — do not open the PR with a known compromise.

**All changes:**
- [ ] No secrets in code, commits, or logs; `.env.example` updated for any new env var
- [ ] Every external call (GitHub API, Notion API, Anthropic API, Telegram, Resend, filesystem/git) has an explicit success and failure path — no silent catches
- [ ] No devDependencies imported at runtime
- [ ] Names convey intent; no comments explaining *what* the code does
- [ ] New code is open for extension; no god-objects, no premature abstraction
- [ ] Docs in sync: README, `.env.example`, `docs/BUILD_PLAN.md`, `docs/api.md` where relevant

**Backend additions:**
- [ ] Every new input surface validated by a Pydantic model at the API boundary — request body, query params, and path params. No handler receives untyped or partially-typed input.
- [ ] Any new endpoint accepting credentials (e.g. login) is rate-limited
- [ ] Uncaught errors surface through the logging path with enough context to debug
- [ ] New secrets are added to the `secrets` map in `project.yaml` (by reference, never by value) and to `.env.example`
- [ ] Tests for the state store run against a real (temporary) SQLite database, not a mocked connection. Tests for external integrations (GitHub, Notion, Anthropic, Telegram, Resend) mock the HTTP layer — never hit the real services
- [ ] Respects the architecture rules in `CLAUDE.md` (deterministic logic stays deterministic, provider specifics stay behind `ProviderAdapter`, idempotent sync)

**Frontend additions:**
- [ ] Every new data-driven screen has loading, empty, error, and populated states
- [ ] No hardcoded API URLs — only the configured API base URL (see `CLAUDE.md`)
- [ ] Destructive or high-impact actions (stop a run, override the usage threshold, delete a branch) confirm before firing
- [ ] New screens pass WCAG 2.1 AA and render correctly at mobile / tablet / desktop

### 4. Boundary rules

- [ ] No logic from one area has leaked into the other — no orchestration/business logic in React components, no UI concerns in the FastAPI backend beyond serving the API and the built frontend
- [ ] Frontend: auth state comes from a single auth endpoint (see `CLAUDE.md` once the auth approach is defined), nothing hardcoded or duplicated client-side
- [ ] Provider-specific code (Claude Agent SDK calls, etc.) lives only behind `ProviderAdapter` implementations — the engine never calls a provider SDK directly

### 5. PR title and body

**Title format:** `[issue number] Short imperative description`
Example: `#12 Add project.yaml loader with Pydantic validation`

**Body must include:**

```markdown
## Summary
[One paragraph describing what changed and why]

## Issue
Closes #[issue number]

## Related issues
[Any issues this depends on or unblocks, or "None"]

## Acceptance criteria
[Copy the checkbox list from the issue body and tick each item]

## Spec reference
[Specification section(s), e.g. "Spec §16.3"]

## Test notes
[Describe what is tested and any pre-existing failures noted]

## Contract changes
[Describe any changes to docs/api.md, the ProviderAdapter interface, or config schemas, or "None"]
```

### 6. Labels and milestone

- [ ] PR is assigned to the correct milestone
- [ ] PR has at least one label (`enhancement`, `bug`, `chore`, ...)

## Opening the PR

Branch naming: `issue-<N>-<short-slug>`, created off `main`.

Once all items above are checked, open the PR against `main` with `Closes #<N>` in the body — merging will close the issue automatically. Request a review from the orchestrator. Do not merge without orchestrator approval.
