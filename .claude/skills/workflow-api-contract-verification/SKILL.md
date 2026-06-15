---
name: workflow-api-contract-verification
description: Verify that an implementation matches its documented contract exactly — the ProviderAdapter interface, the project.yaml/execution-profile.yaml schemas, or the HTTP/SSE API between orchestrator-api and orchestrator-ui. Use for every backend interface added or changed, and for any frontend code consuming an endpoint (including mocks). Both implementor specialities.
---

A contract is only useful if implementation and consumer agree on it exactly. This project has
three kinds of contract, each with its own source of truth.

| Contract | Source of truth |
|---|---|
| `ProviderAdapter` interface | Specification §3.1 — `run_session` signature, `SessionResult` shape |
| `project.yaml` / `execution-profile.yaml` schema | Specification §16.3 / §17.5 field tables |
| HTTP/SSE API between `orchestrator-api` and `orchestrator-ui` | `docs/api.md` in this repo (create on first endpoint — Spec §12 lists the required capability surface but not exact shapes) |

## Step 1: Identify which contract applies

Most backend PRs touch exactly one of these. If a PR introduces a new HTTP/SSE endpoint and
`docs/api.md` does not exist yet, this PR creates it.

## Step 2: Backend — verify against the contract

**`ProviderAdapter` / config schemas:** compare field-by-field against the relevant
Specification table. A deviation means either the implementation is wrong, or the Specification
needs an explicit, called-out update in the PR description — never a silent divergence.

**HTTP/SSE endpoints:**
- If `docs/api.md` doesn't describe this endpoint yet, add it as part of this PR: method, path,
  request/response shape (including types), status codes, and — for SSE — the event shape and
  event types. This PR establishes the contract.
- If it already exists, the implementation must match exactly. If the contract is intentionally
  changing, update `docs/api.md` in the same PR and call out the change explicitly in the PR
  description (consumers will need to update too).

## Step 3: Frontend — verify against the contract

Compare the API client and any mock handlers against `docs/api.md` directly — not against
existing TypeScript types, fixtures, or other handlers, which may already have drifted. Applies
to new mocks and to updates of existing ones, and whenever switching a call from a mock to the
live backend.

## Step 4: Unresolved or undocumented

If the contract for something you're building isn't in the Specification and isn't yet in
`docs/api.md`, and the acceptance criteria don't give you enough to define it reasonably,
apply `workflow-blocker-escalation` rather than guessing — an undocumented contract guessed by
the backend and guessed differently by the frontend is worse than a short pause.
