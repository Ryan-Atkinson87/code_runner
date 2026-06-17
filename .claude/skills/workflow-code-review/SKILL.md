---
name: workflow-code-review
description: How to review a PR from an implementor agent. Use this skill when a PR is opened or ready for review. Orchestrator only.
---

A review is a spec compliance check, a boundary check, and a quality check. It is not a style review unless style affects correctness or maintainability. Leave structured comments on the PR so the implementor can apply `workflow-feedback-on-tickets` without ambiguity.

## Step 1: Load the context

Before reading the diff, read:
- The linked GitHub issue and its acceptance criteria checklist
- The Specification section(s) referenced in the issue
- `docs/api.md` for any endpoint or contract this PR touches
- Any `Depends on: #N` declarations in the issue body

## Step 2: Spec compliance

**Backend PRs — check against `docs/api.md` and the Specification:**
- Request shape matches (method, path, body fields, query params)
- Response shape matches (field names, types, status codes)
- Error response bodies match the documented error contract
- Every input is validated by a Pydantic model at the API boundary
- Auth guard applied wherever the issue requires it (see Specification for the authentication model)
- `docs/api.md` updated if this PR adds or changes an endpoint

**Frontend PRs — check against Specification §12 (UI scope) and `docs/api.md`:**
- All screen states implemented (loading, error, empty, populated)
- Routing matches any documented route structure
- Auth flow uses a single auth endpoint (per `docs/api.md` / `CLAUDE.md` once defined), nothing duplicated client-side
- API mocks are consistent with `docs/api.md`, not just with each other
- No business/orchestration logic re-implemented client-side that the backend already owns (e.g. recomputing usage thresholds instead of reading them from the API)

## Step 3: Production readiness

Every change ships to the running tool. Check the PR against the bar defined in `CLAUDE.md`. Any compromise is a blocking comment with a link to the relevant rule — accept no shortcuts.

**Common checks (all changes):**
- Secrets handling: no credentials in code, commits, logs, or PR body. `.env.example` updated for any new key
- Every external call (GitHub API, Notion API, Anthropic API, Telegram, Resend, filesystem/git) has explicit success and failure paths. No swallowed errors
- Names convey intent. No comments explaining *what* (only *why*, when non-obvious)
- No devDependencies imported at runtime
- New code is open for extension without rewriting existing code; no god-objects
- Docs in sync: README, `.env.example`, `docs/BUILD_PLAN.md`, `docs/api.md`, `CLAUDE.md` where relevant

**Backend:**
- Pydantic validation present on every new request body, query param, and path param
- New credential-accepting endpoints (e.g. login) are rate-limited
- Uncaught errors have a logging path with enough context to debug
- New secrets are added to the `secrets` map in `project.yaml` (by reference, never by value) and to `.env.example`
- Tests for the state store run against a real (temporary) SQLite database, not a mocked connection. Tests for external integrations (GitHub, Notion, Anthropic, Telegram, Resend) mock the HTTP layer, never hit the real services

**Frontend:**
- Every new data-driven screen has loading / empty / error / populated states
- No hardcoded API URLs anywhere — only the configured API base URL
- Destructive or high-impact actions confirm before firing
- WCAG 2.1 AA compliance on new screens (defer full audit to `workflow-accessibility-testing`)

## Step 4: Architecture rules

Check the PR against the "Architecture rules every PR must respect" section in `CLAUDE.md`:
- Deterministic logic (sequencing, git, test/lint/typecheck gating, PR mechanics, tracker sync) stays in plain Python — not routed through an AI call
- Sessions are stateless — nothing assumes an AI session remembers a previous session
- Provider-specific code lives only behind `ProviderAdapter` implementations
- Config files hold secrets by reference (env var names), never by value
- `executor: engine` skill content isn't rendered into AI-facing instructions
- Tracker-sync code is idempotent — converges to the correct state on re-run, not a delta

Flag any violation as a blocking comment citing the specific rule.

## Step 5: Boundary violations

Flag any of the following as blocking review comments:
- Backend logic duplicated or reimplemented in the frontend, or vice versa
- Auth state stored anywhere other than the documented mechanism
- A `ProviderAdapter` implementation called directly instead of through the adapter interface

## Step 6: Test coverage

Check that:
- Unit tests exist for any non-trivial logic added
- Component tests cover the primary interaction paths for UI changes
- API mocks are updated if new endpoints are introduced
- No test has been deleted without explanation

If test coverage is missing, leave a comment specifying exactly what needs to be tested. Do not block on 100% coverage, block on absence of tests for the core acceptance criteria paths.

## Step 7: Leave review comments

For each finding:
- Reference the specific file and line
- State the category: `blocking` (must fix before merge) or `non-blocking` (fix or note in a follow-up issue)
- For `blocking` comments, state exactly what is required to resolve it
- For `non-blocking` comments, create a follow-up issue if the work is worth tracking, and reference it in the comment

## Step 8: Sign off or request changes

- **Request changes** if any blocking finding exists: post a comment (`gh pr comment <PR> --body "..."`) with the heading **"Requesting changes — implementor action needed"**, listing each blocking finding with its file/line and the exact fix required. Stop here — wait for `process-handle-feedback`.
- **Sign off** if all acceptance criteria are met, no blocking findings remain, and architecture/boundary rules are observed: post a comment (`gh pr comment <PR> --body "..."`) with the heading **"Ready to merge"**, summarising what was checked and confirming the PR passes review.
- Never sign off a PR with an open blocking comment.
- **Do not merge PRs.** Merging is the human's responsibility.

GitHub rejects a formal `gh pr review` from the PR author (see "Tooling conventions" in `CLAUDE.md`) — a comment is the sign-off, there is no separate approval action.

## Step 9: Notify the human

After posting the review comment, print a terminal message:
- If ready to merge: `PR #N ("<title>") is ready to merge. Sign-off comment posted.`
- If changes needed: `PR #N ("<title>") needs changes before it can merge. Comment posted for the implementor.`

After the human confirms the PR has merged, the orchestrator must:
1. Check off the issue's row in `docs/BUILD_PLAN.MD` (`- [ ] #N — ...` → `- [x] #N — ...`) and commit the change to `main`.
2. Apply `workflow-notion-sync`.
