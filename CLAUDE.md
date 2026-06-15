# Code Runner — Project Reference

Code Runner is a self-hosted autonomous coding-agent orchestrator: a deterministic engine that
drives Claude Code (and, later, Codex/Gemini behind the same adapter) through a project
milestone by milestone, invoking the AI only for planning, writing, and reviewing code. The
human is out of the loop until a hand-off PR is ready for review.

This repo (`code_runner`) is the first thing being built. Its own development is run using the
same orchestrator/implementor skill workflow it is designed to formalise — adapted by hand for
now, since the tool doesn't exist yet to generate and drive it automatically. The skills in
`.claude/skills/` are that adapted workflow.

## Source of truth

- **Specification (Notion):** the 18-section spec — `https://app.notion.com/p/37214c40040d8142af8aeb81d8a70961`.
  All design decisions trace back to this page. Skills reference it by section number
  (e.g. "Spec §5" = Branch and PR model). Read the relevant section before making a design
  decision that isn't already covered by an issue's acceptance criteria.
- **Social Media Context (Notion):** `https://app.notion.com/p/37214c40040d811396f4eb7e674d3edd` —
  updated at every milestone close (mandatory — see `workflow-milestone-completion`).
- **GitHub:** `Ryan-Atkinson87/code_runner`.

This project does **not** have separate Notion "Technical Tasks" / "User Stories" / "Open Items"
pages — those exist for other projects (Trive Services) and are not needed here. GitHub issues
are the technical tasks directly; Spec §15 ("Open items to resolve") is the open-items list; the
Social Media Context page is the only Notion page that gets routine updates. Do not create new
Notion tracking pages "just in case" — if a skill says to sync Notion, it means the Social Media
Context page unless stated otherwise.

## Roles

- **Orchestrator** — plans a milestone into issues, reviews implementor PRs, runs QA /
  accessibility / responsiveness checks on UI changes, closes milestones.
- **Implementor × backend** — the Python/FastAPI/Pydantic orchestration engine: provider
  adapters, git/PR engine, usage monitor, tracker sync, config loaders.
- **Implementor × frontend** — the React/Vite UI: run control, live progress (SSE), usage
  gauges, blocker list, PR surfacing, efficiency reports, notifications, config view (Spec §12).

One repo, two implementor specialities, no admin frontend. `Depends on: #N` in an issue body
refers to another issue in *this* repo — there is no cross-repo dependency syntax to interpret.

## Repo layout

TBD — to be filled in during the Foundations milestone (Spec §14, phase 1). Suggested starting
point, matching the component names in Spec §2:

- `orchestrator-api/` — FastAPI backend + deterministic engine
- `orchestrator-ui/` — React/Vite frontend

Build progress (phase status and per-milestone issue checklists) lives in
`docs/BUILD_PLAN.md` — see "GitHub conventions" below.

Update this section as soon as the layout is decided — several skills reference
`<BACKEND_PATH>` / `<FRONTEND_PATH>` and should be updated to point at the real directories.

## GitHub conventions

- **Single `main` branch.** PRs target `main` directly. Use `Closes #N` in PR bodies — merging
  closes the linked issue immediately. There is no `dev` branch and no batch milestone-close PR.
- **Milestones = build phases.** Spec §14 lists the suggested phases (Foundations, Git/PR
  engine, Claude adapter + wave loop, Usage monitor, Trackers + notifications, Observability +
  UI, Multi-provider). Use these as the initial milestone names; refine as planning proceeds.
- **Labels:** repo defaults (`bug`, `enhancement`, `documentation`, `question`, `wontfix`, ...)
  plus `chore` and `blocked` — create the latter two if they don't exist yet.
- **No GitHub Project board** for this repo. Issue state (open/closed), labels, and milestones
  are sufficient at this scale. If a board is added later, update `workflow-phase-issues` and
  `process-review-pr` to read/write its status field.
- **Local build plan:** `docs/BUILD_PLAN.md` tracks Spec §14 phase status (`⬜`/`🔄`/`✅`) and a
  per-milestone issue checklist, in place of the board. `workflow-project-planning` adds rows as
  issues are created; `workflow-code-review` checks them off when a PR merges and closes its
  issue; `process-close-milestone` updates phase status.

## Tooling conventions

These reduce the number of permission prompts and avoid calls GitHub will reject outright. They
apply to every skill and every agent persona.

- **No `VAR=$(...)` compound Bash.** Command-substitution assignments aren't auto-approved even
  when the underlying command is on the allowlist — run the lookup and the dependent step as
  separate Bash calls.
- **Filter JSON with `jq`, not inline Python.** Pipe `gh`/`gh api` output through `jq`. Never use
  `python3 -c "..."` for this — multiline `-c` scripts trigger security prompts.
- **`gh` CLI first.** Use `gh` (issue, pr, api shorthand) for standard GitHub operations. Reserve
  `gh api` for GraphQL queries `gh` has no subcommand for. Always bound list commands with
  `--limit N` — never `--paginate`.
- **Edit files only via Read/Edit/Write.** Never `sed`, `awk`, `echo >`, or `cat >` to change file
  contents — applies to source, `docs/BUILD_PLAN.md`, issue/PR bodies, docs, everything.
- **Notion MCP — batch and cache.** At the start of any session that needs Notion, load the tool
  schemas with one `ToolSearch` call
  (`select:mcp__claude_ai_Notion__notion-fetch,mcp__claude_ai_Notion__notion-search,mcp__claude_ai_Notion__notion-update-page`).
  Fetch each page once per session and hold it in context — don't re-fetch. Fetch sequentially,
  not in parallel. On HTTP 429, back off 60 seconds before retrying.
- **GitHub self-review is blocked.** This repo has one GitHub identity (`Ryan-Atkinson87`) acting
  as both implementor (PR author) and orchestrator (reviewer) — GitHub rejects any
  `gh pr review` (approve, request-changes, or comment-type) submitted by the PR author.
  `workflow-code-review` therefore posts review findings and sign-off as a regular
  `gh pr comment`, and merges directly with `gh pr merge` — no formal review step. "Request a
  review from the orchestrator" elsewhere in these skills means posting that hand-off comment,
  not assigning a GitHub reviewer.

## Tech stack & commands

| Area | Stack | Test | Lint | Typecheck |
|---|---|---|---|---|
| Backend (`<BACKEND_PATH>`) | Python 3.13, FastAPI, Pydantic, asyncio, SQLite | `<BACKEND_TEST_CMD>` | `<BACKEND_LINT_CMD>` | `<BACKEND_TYPECHECK_CMD>` |
| Frontend (`<FRONTEND_PATH>`) | React + Vite | `<FRONTEND_TEST_CMD>` | `<FRONTEND_LINT_CMD>` | `<FRONTEND_TYPECHECK_CMD>` |

These placeholders get filled in as part of the Foundations milestone, when the package manager
and tooling are chosen and the scaffold lands. Until a command is filled in, `workflow-testing`
and `process-review-pr` treat that gate as "not yet established — note it, don't fail on it",
not as a silent skip forever. Once filled in, the gate is mandatory like any other repo.

Local environment: Docker Compose stack (Traefik ingress, `orchestrator-api`, `orchestrator-ui`,
`langfuse` + `langfuse-db`, `agent-runner`, `egress-proxy`) per Spec §2. There is no separate
prod/dev deployment target yet — "the local server" is the only environment.

## Architecture rules every PR must respect

These come from the Specification's core principles and security model, and are checked in
`workflow-code-review` in addition to the general production-readiness bar below.

- **Deterministic logic stays deterministic (Spec §1 Principle 1).** Sequencing, git operations,
  test/lint/typecheck gating, PR mechanics, and tracker sync are plain Python. A PR that routes
  one of these through an AI call where a deterministic implementation is possible is a blocking
  finding.
- **Sessions are stateless (Spec §1 Principle 2, §4.3).** Anything an AI session needs must be
  re-readable from git/GitHub/Notion/SQLite at session start. No design that requires an AI
  session to remember something from a previous session.
- **Provider specifics stay behind `ProviderAdapter` (Spec §3.1, §3.3).** Orchestration code
  must not call Claude-, Codex-, or Gemini-specific APIs directly outside the adapter
  implementations. Even though only the Claude adapter is built for the MVP, the engine talks to
  `ProviderAdapter`, never to the Claude SDK directly.
- **Secrets by reference, never by value (Spec §10, §16.3).** Config files (`project.yaml`,
  `execution-profile.yaml`) hold env-var *names* only and must be safe to commit. Actual secrets
  come from the container secret store / environment at runtime.
- **Engine vs AI separation in rendered instructions (Spec §17.3, §17.7).** `executor: engine`
  skills are not rendered into an AI session's instructions — they're the engine's own spec,
  surfaced to an AI only at defined hand-back points (e.g. a failing test fed back to
  `implement`). Don't add AI-facing instructions for work the engine already does
  deterministically.
- **Idempotent sync (Spec §18.5).** Any tracker-sync code (GitHub board, Notion, Social Media
  Context) must converge to the correct state when re-run after a partial failure — "make the
  target match the source", not "apply a delta".

## Production readiness bar (all PRs)

- No secrets in code, commits, or logs; `.env.example` updated for any new env var.
- Every external call (GitHub API, Notion API, Anthropic API, Telegram, Resend, filesystem/git)
  has an explicit success and failure path — no silent `except: pass`.
- No devDependencies imported at runtime.
- Names convey intent; no comments explaining *what* the code does, only non-obvious *why*.
- New code is open for extension; no god-objects, no premature abstraction.
- Docs in sync: README, `.env.example`, `docs/BUILD_PLAN.md`, and this file where relevant.
- Frontend: every new data-driven screen has loading, empty, error, and populated states; no
  hardcoded API URLs; destructive actions confirm before firing; WCAG 2.1 AA on new screens.
