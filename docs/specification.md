# Code Runner — Specification

> Source: [Notion — 📐 Specification](https://app.notion.com/p/37214c40040d8142af8aeb81d8a70961)
> Synced: 2026-06-15. Notion is the source of truth — re-sync this file if the Notion page changes.

Planning spec for the autonomous coding agent orchestrator. Defines behaviour, boundaries, and architecture. This is not implementation; code is produced separately.

---

## 1. Core principles

1. **Algorithmic by default, LLM only for judgement.** Everything deterministic (reading state, ordering work, git operations, running tests/lint/typecheck, opening PRs, syncing trackers, monitoring usage) is plain Python. The AI provider is invoked only for planning, writing code, and reviewing code.
2. **State lives in git and the trackers, not in agent context.** Every AI session starts fresh and re-reads live state. No reliance on prior-session memory. Token-efficient and crash-resilient.
3. **Quality is never traded for token savings.** Model selection optimises for best code per token, not cheapest token. When usage is exhausted, it pauses; it does not degrade.
4. **The security boundary is infrastructure, not agent goodwill.** Provider permission flags are the inner layer. The container, network proxy, and GitHub branch protection are the layers that actually hold when the agent tries to step outside its lane.
5. **Provider-agnostic core.** Orchestration never knows which AI provider is running. All providers sit behind one adapter interface.
6. **Human out of the loop until the wave PR.** The agent plans, implements, and self-reviews autonomously. The human is engaged only for genuine blockers (surfaced immediately) and the final wave review PR.

---

## 2. High-level architecture

Container on the local server, bound to a single project directory. Compose stack with Traefik as ingress (mirroring the existing Trive dev setup), one service per concern.

```
traefik            ingress, TLS, routing
  orchestrator-ui  React, served behind auth
  orchestrator-api FastAPI + deterministic engine
  langfuse         LLM observability
  langfuse-db      Postgres (Langfuse dependency)
  agent-runner     runs Claude/Codex/Gemini; network-locked
  egress-proxy     Squid, allowlist enforcer
```

**Components**

- **React UI** — authenticated control panel. Start/stop runs, pick project + waves, choose provider, live progress, usage gauges, blocker/PR surfacing, efficiency reports, notification toggle, usage-override switch.
- **FastAPI backend** — REST + Server-Sent Events for live updates. Hosts auth. Serves the built React app.
- **Orchestrator engine** — deterministic core. Owns the run loop, wave/issue sequencing, dependency resolution, decides when to invoke a provider.
- **Provider adapters** — uniform interface over Claude Agent SDK, Codex CLI, Gemini CLI.
- **Usage monitor** — tracks all relevant meters per provider; enforces threshold + peak-hour throttle.
- **Git/PR engine** — all local git operations, branch lifecycle, the single hand-off push + PR per repo.
- **Tracker sync** — GitHub (authoritative execution state) and Notion (human mirror + planning input).
- **Notification service** — Telegram (default, two-way) + Resend email (optional).
- **Langfuse** — self-hosted LLM observability; powers efficiency reports.
- **SQLite** — run state, blocker records, usage history, efficiency rollups. Clean migration path to Postgres.
- **Egress proxy** — network allowlist enforced outside the agent process.

Language: Python for the entire backend and orchestration. React (Vite) for the UI.

---

## 3. Provider abstraction

### 3.1 Adapter interface

Every provider implements one interface. The orchestrator only ever calls this:

```
ProviderAdapter:
  run_session(
    workdir: path,            # the repo working directory
    role: "orchestrator" | "implementor",
    model: str,               # resolved per-role, per-provider
    allowed_tools: list[str], # the permitted tool surface
    prompt: str,              # the task instruction
    context_files: list[path] # issue body, spec excerpts
  ) -> SessionResult

SessionResult:
  events: stream[NormalisedEvent]  # reasoning / tool-call / tool-result / output
  usage: UsageReport               # tokens in/out, cost, model, duration
  outcome: "completed" | "blocked" | "error"
  artifacts: list[path]            # files changed (from git, not self-report)
```

Normalised events let the UI stream live progress identically regardless of provider.

### 3.2 Provider matrix

| Provider | Invocation | Permission/lockdown | Instruction file | Notes |
|---|---|---|---|---|
| **Claude** (default) | Claude Agent SDK (Python), fresh session per task | `allowed_tools` • hooks (PreToolUse block, PostToolUse audit) + strict-deny permission mode | `CLAUDE.md` • skills | Strongest code quality. Agent SDK credit change (see 6.4). |
| **Codex CLI** | non-interactive CLI, `--output-format json` | `sandbox_mode`, `network_access` policy, permission levels | `AGENTS.md` | Strong sandbox + token efficiency. |
| **Gemini CLI** | headless `-p` • `--output-format json` | approval modes + seatbelt/sandbox profiles | `AGENTS.md` | Large context; read-only Plan Mode. |

### 3.3 Build order

Build the Claude adapter first and prove the full loop end-to-end on Trive. Add Codex and Gemini behind the same interface afterwards. The orchestrator must not require all three to exist.

> **MVP scope note.** Multi-provider is explicitly out of scope for the MVP. The human is happy on Claude Code, so only the Claude adapter is built and exercised. The interface in 3.1 is the door left open: as long as the orchestrator calls providers *only* through `ProviderAdapter` (never Claude-specific calls leaking into the engine), adding Codex/Gemini later is an additive change with minimal blockers. The single MVP obligation is therefore architectural discipline, keep the Claude specifics behind the adapter, so deferring the other providers costs nothing later. Full event-mapping/usage-extraction/blocker-detection detail per provider is deferred until a second provider is actually wanted.

### 3.4 Instruction-file generation

Workflow rules live in one canonical source in the tool. At run start, the tool generates the provider-appropriate file into each repo working copy: Claude gets `CLAUDE.md` + skill files; Codex/Gemini get `AGENTS.md`. Prevents three drifting copies. Versioned with the project config.

---

## 4. The run model

### 4.1 Roles

- **Orchestrator role (AI):** plans a wave into issues (if not already planned), reviews each implementor PR internally, decides approve/request-changes.
- **Implementor role (AI):** picks up an issue, checks dependencies, writes code, runs tests, opens an internal PR.
- **Deterministic engine (Python):** sequencing, all git, all test/lint/typecheck gating, all tracker sync, all PR mechanics, all usage control. It presses the buttons the human used to press.

**Mapping from current Trive skills (which become the canonical instruction source):**

| Current skill | Becomes |
|---|---|
| `process-plan-milestone`, `workflow-project-planning` | AI orchestrator session (planning), driven by engine |
| `process-implement-milestone`, `workflow-phase-issues` | Engine loop selecting issues in dependency order |
| `workflow-dependency-check` | Engine pre-check before each issue (algorithmic) |
| `workflow-testing`, lint, typecheck | Engine gates (algorithmic, no AI) |
| `workflow-pr-creation` | Engine opens internal feature-branch PR; AI fills body |
| `process-review-pr`, `workflow-code-review` | AI orchestrator session (review) |
| `process-handle-feedback`, `workflow-feedback-on-tickets` | AI implementor session (feedback) |
| `workflow-notion-sync` | Engine tracker sync (algorithmic) |
| `workflow-blocker-escalation` | Engine detects, notifies human |
| `process-close-milestone`, `workflow-milestone-completion` | Engine assembles wave hand-off PR(s) |

The accessibility/responsiveness/QA skills remain human-verification items surfaced in the final PR checklist (they require a browser).

### 4.2 The wave loop (deterministic engine)

```
1. Sync integration branch (dev) from GitHub.
2. Create the wave's agent branch (`code-runner/<wave-slug>`) fresh from dev (see 5).
3. If wave not yet planned:
      invoke AI orchestrator (planning) -> issues created in GitHub + Notion.
4. Order issues by dependency (algorithmic).
5. For each unblocked issue, in order:
      a. Dependency check (algorithmic). If unmet -> park, record blocker, continue.
      b. Create short-lived feature branch off the agent branch.
      c. Invoke AI implementor -> write code against acceptance criteria. (Sessions soft-checkpoint at 30 min: stop at a safe boundary, commit, clear context, resume the same issue; 3 checkpoints without a PR parks it as a blocker. See 18.9.)
      d. Run full test suite + lint + typecheck (algorithmic gate).
         - Fail -> feed results back to a bounded number of AI fix attempts.
         - Still failing and needs a decision -> park, record blocker, continue.
      e. (Backend) API contract verification against spec.
      f. Engine opens internal PR (feature branch -> agent branch); AI fills the body.
      g. Invoke AI orchestrator (review) on the internal PR.
         - Request changes -> AI implementor feedback session -> re-review (bounded loop).
         - Approve -> engine merges feature branch into agent branch, deletes it.
      h. Sync GitHub board + Notion (algorithmic).
   Throughout: usage monitor may pause the loop (see 6).
6. When all issues are Done or parked:
      - Keep agent branch current with dev (merge dev in if it advanced).
      - Assemble the hand-off PR(s) and notify the human.
```

Parked blockers do not stop the wave; the engine continues with other unblocked issues and lists every parked blocker in the final PR and the immediate notification.

### 4.3 Fresh sessions

Each AI invocation is a new session that re-reads the issue, the relevant spec, and live state. No session inherits another's context. Slightly higher per-issue setup cost, much lower context bloat, far better crash recovery.

---

## 5. Branch and PR model

### 5.1 The agent branch

- One agent branch **per wave, per repo**, named `code-runner/<wave-slug>` where the wave slug is the wave identifier slugified to be branch-safe (e.g. wave "P3 – Services & Profiles" → `code-runner/p3-services-profiles`). The name self-documents what the hand-off PR contains.
- Created fresh from the integration branch (`dev`) at wave start. Not persistent across waves — each wave gets its own branch; the previous wave's branch is deleted after its PR merges (5.4 step 5).
- Kept current with `dev` by **merge** (not rebase) if `dev` advances during the wave.

### 5.2 Local-only during the wave

- The agent branch and all per-issue feature branches exist only on the server during the wave. Nothing is pushed to GitHub mid-wave.
- `dev` is the synced reference: fetched from GitHub at wave start; the agent branch tracks it locally.

### 5.3 Feature branches

- Each issue gets a short-lived feature branch off the agent branch.
- Internal review (AI orchestrator) happens on a local PR/diff.
- On approval, the feature branch merges into the agent branch and is deleted. No per-issue GitHub PR.

### 5.4 Hand-off (the only push)

At wave completion only:

1. Push the agent branch to GitHub once, per repo.
2. Open one PR per repo from the agent branch to `dev`.
3. PR body (mirrors current `process-close-milestone` Step 5):
   - **Summary** — what the wave delivered.
   - **Per-issue notes** — one line each, with issue refs (`Issue: #N`, never `Closes`; issues close at the later dev to main merge).
   - **Pre-checked items** — everything the engine verified programmatically (tests, lint, typecheck, API contract, auth enforcement, data correctness). Pre-ticked, not open checkboxes.
   - **Human-only checklist** — open checkboxes only for genuinely human checks: visual layout, responsive breakpoints, accessibility (screen reader/keyboard), production-only integrations (real email, OAuth redirects). Omitted entirely if the wave has none.
   - **Parked blockers** — any issue that could not be completed autonomously, with detail.
   - Note that CI must pass before merging.
4. Notify the human that the wave is ready for review.
5. After the human merges, delete the remote wave branch. The next wave creates its own fresh branch from `dev`.
6. Update the project's **📣 Social Media Context** Notion page (Current Status, Recent Milestones, What's Coming Next) to reflect what the wave shipped and what is next. Mandatory, mirrors `process-close-milestone` Step 3 in the Trive workflow. The engine does this automatically at hand-off so it is never dependent on the human remembering to ask.

GitHub sees the agent branch only for the review window, giving a real reviewable PR with CI while all work-in-progress stays local.

> CI note: the hand-off assumes CI runs on PRs to `dev`. Confirm the Trive CI triggers fire on `dev` PRs, not only `main`/pushes, before relying on the "CI must pass" line.

---

## 6. Usage monitoring and control

### 6.1 Meters

Usage is multiple meters, not one. The monitor tracks all that apply to the active provider/plan:

- 5-hour rolling window (subscription plans).
- Weekly (7-day) cap, including per-model weekly meters where they exist (Opus and Sonnet are tracked independently as of the Nov 2025 Opus 4.5 change).
- Monthly Agent SDK credit (see 6.4).
- API spend / token budget (API key mode).

### 6.2 Reading usage (the mechanism)

The monitor reads usage differently per mode. Both paths are built; only the active one runs.

**Subscription mode (primary, the path used today).** Poll the undocumented OAuth usage endpoint `GET https://api.anthropic.com/api/oauth/usage`, authenticated with the OAuth token Claude Code maintains in `~/.claude/.credentials.json` (header `anthropic-beta: oauth-2025-04-20`). It returns per-window utilisation (0-100) and a `resets_at` for each of: `five_hour`, `seven_day`, `seven_day_opus`, `seven_day_sonnet`, plus an `extra_usage` object (`is_enabled`, `monthly_limit`, `used_credits`, `utilization`) covering credits/overage. These map directly onto the 6.1 meters. The statusLine JSON (`rate_limits.five_hour` / `.seven_day`, Claude Code ≥2.1.x) is an available no-network fallback for the two main windows.

**API mode (built, untested, inactive until a key is added).** When on an API key, usage comes from response headers (`anthropic-ratelimit-tokens-remaining`, `-tokens-reset`, etc.) read per call via the SDK's raw-response accessor. No polling endpoint needed. This path is implemented for completeness but is not exercised until an API key is configured; the human is subscription-only for now.

**Volatility caveat (load-bearing).** The OAuth usage endpoint is undocumented and reverse-engineered; the OAuth token works for this endpoint but is rejected for general API calls. Subscription accounting is visibly in flux (new models such as Fable 5 with burn multipliers, free-window-then-credits transitions, and official usage docs going 404). The usage reader is therefore a best-effort, provider-specific adapter with graceful degradation: if the endpoint shape changes or a read fails, it falls back (OAuth endpoint → statusLine stdin → token-estimation) rather than crashing the run, and must tolerate new meters/weightings appearing without code changes. The API-header path is the dependable substrate if reliable autonomous pausing ever matters more than subscription cost.

### 6.3 Threshold rule

- Pause threshold is **80% of the most restrictive applicable meter**. Whichever meter is closest to its limit governs.
- On reaching threshold: **hard pause**. Finish the current atomic step cleanly, commit progress, then stop. The pause is graceful (a known marker), unlike a crash, so resume needs no discard (contrast 18.4).
- No model downgrade to keep running. Quality is not compromised.

### 6.4 Pause and resume

A usage pause sets a `waiting-for-usage` state and resumes automatically. Two-tier reset detection:

**Reset time known (normal case).** If the last successful usage read gave a `resets_at` for the governing meter, sleep precisely until that time plus a small buffer, then resume. No probing.

**Reset time unknown (fallback).** If the usage reader is unavailable or the run hit a hard 429 with no readable reset, probe: issue the cheapest possible test call (tiny `max_tokens`, trivial prompt) **on the specific model tier that is exhausted** (a Sonnet probe does not prove the Opus weekly reset, given per-model meters). A 200 means the window reopened → resume; a 429 means keep waiting.

**Probe interval: exponential backoff, not flat.** Start at 5 minutes, double on each failed probe (5 → 10 → 20 → 40), cap at 30 minutes, reset to 5 minutes on success. This self-tunes: a brief 5-hour-window exhaustion is picked up within ~5-15 min, while a multi-day weekly cap settles into ~half-hourly checks instead of burning hundreds of probes. (A flat 10-minute interval is an acceptable v1 simplification but backoff is preferred and is only a few lines.)

The probe consumes a negligible sliver of the same pool being preserved; this is accepted as the price of automatic resume.

**Resume point.** On resume the engine continues from the per-issue state marker (18.3) at the next step, exactly like walking away and telling Claude Code to "continue" once the window resets. No work is lost because the pause stopped at a committed, known step.

### 6.5 Override

- A UI switch lets the human override the threshold and keep working into available credits/usage. Used deliberately (e.g. to evaluate whether Max is worth buying long-term).
- Override is explicit and visible; does not persist silently across runs unless left on.

### 6.6 Agent SDK credit change (date-sensitive)

From **15 June 2026**, Agent SDK and `claude -p` usage on subscription plans draw from a separate monthly Agent SDK credit, distinct from interactive Claude.ai usage. When the agent runs via the SDK on a subscription, it no longer competes with the human's chat pool. The monitor must:

- Treat the Agent SDK credit as its own meter for the Claude provider on subscription plans.
- Target the correct meter for "reserve capacity for the human" (chat pool vs SDK credit) depending on provider/plan/date.
- Surface clearly in the UI which meter is governing.

### 6.7 Peak-hour throttle

- Subscription usage burns faster weekday mornings (reported ~1.3-1.5x, roughly 5-11am Pacific). The monitor throttles or defers heavy work in this window unless override is on.

### 6.8 Provider/plan switching

- Provider and plan (Pro / Max / API key, and OpenAI / Google equivalents) are selectable in config and switchable from the UI mid-project. The monitor reloads the correct meter set on switch.

---

## 7. Security and lockdown

Layered, infrastructure-first. The agent must be physically unable to act outside its lane, not merely asked not to.

### 7.1 Container boundary

Runs in a container on the local server, filesystem-bound to the single project directory (mount). Cannot see or touch anything outside the target directory. Docker (consistent with the existing Trive Traefik setup).

### 7.2 Network egress allowlist

- Only the `agent-runner` service is network-locked. Other services (api, ui, langfuse) reach the internet normally.
- `agent-runner` has no default route to the internet, only a route to the Squid egress proxy. `HTTP_PROXY`/`HTTPS_PROXY` point at Squid, and an iptables DROP rule on the external interface blocks direct egress so the proxy cannot be bypassed even if the agent removes the env vars.
- Squid filters on destination hostname (correct approach, since GitHub/registries sit behind CDNs with changing IPs). Domain-level allow/deny only, no TLS interception, so no CA cert needed.
- This stops the "agent wanders off and asks permission to fetch something" failure mode: the request is blocked at the network layer, so there is no tangent and no prompt to handle.

**Agent-runner allowlist** (Squid ACL, extendable per-project via config):

- `github.com`, `api.github.com`, `codeload.github.com` — git + PR operations
- `registry.npmjs.org` — npm (Trive is pnpm/Node)
- `pypi.org`, `files.pythonhosted.org` — pip, if any repo is Python
- `api.anthropic.com` — the agent-runner calls the model API directly (decided). OpenAI/Google equivalents added when those providers are enabled.

### 7.3 GitHub branch protection

- Branch protection on `main` and `dev` rejects direct pushes server-side. Even if the agent attempted a push there, GitHub refuses it.
- The agent's GitHub PAT is scoped so it cannot push to protected branches; it can push the agent branch and open PRs only.

### 7.4 Provider permission layer (inner)

- Claude: `allowed_tools` restricted to coding tools; hooks block destructive ops (no `rm` outside repo, no editing CI/workflow files, no reading secrets/`.env`); strict-deny permission mode so anything not pre-approved is denied rather than prompted.
- Codex: sandbox + network policy (npm/GitHub only) + restricted permission level.
- Gemini: sandbox profile + restricted approval mode.

### 7.5 Explicit prohibitions (enforced by the layers above)

- No push to `main` or `dev`.
- No force-push, no remote branch deletion except the agent's own branch at hand-off.
- No editing CI/workflow files.
- No reading `.env` or secret stores.
- No file operations outside the project directory.
- No network egress outside the allowlist.

The coding role gets full freedom inside these boundaries (read/write/run within the repo, install dependencies, run tests) and zero freedom outside them.

---

## 8. Project configuration (reusability)

A single config defines a project so the tool works on new repos with minimal setup. Source-of-truth split:

- **GitHub** — authoritative execution state (issues, milestones/waves, Project board).
- **Local plan file** — the working view the agent and human read while coding (the `IMPLEMENTATION_PLAN.md` equivalent).
- **Notion** — mandatory human dashboard: mirror of execution state plus the origin point for planning, user stories, and technical tasks before they become GitHub issues.

**Sync direction (prevents three-way drift):**

- GitHub is the source of truth for what is done.
- Notion mirrors GitHub state for the human and is the planning input (human/AI plans there first; planning is turned into GitHub issues).
- Notion is never an independent execution-state authority.

Per-project config (e.g. `project.yaml` in the project directory) declares:

- Repos and their roles (generic case: one or more repos).
- Wave structure and dependencies (or where to read them: plan file + GitHub milestones).
- Integration branch name (`dev`), agent branch name.
- Tracker integrations: GitHub (required), Notion (required — every project has a Notion page).
- Provider + plan selection and per-role model mapping.
- Test/lint/typecheck commands per repo.
- Allowlist additions if a project needs extra registries.

Notion is a standard, always-on integration for every project (not Trive-specific).

**Social Media Context page.** Every project's Notion workspace has a 📣 Social Media Context page (Current Status, Recent Milestones, What's Coming Next), read by a separate social-posting process. The engine updates it automatically at every wave hand-off (see 5.4 step 6) so it always reflects reality without manual prompting. The implementor/engine must keep it current as part of completing a wave, not as an afterthought.

---

## 9. Blockers and human escalation

### 9.1 Behaviour

When the agent hits something that previously required the human (missing spec, contract conflict, unmet dependency with no valid stub):

- **Park** that issue, record a structured blocker (type, what's blocked, why, what's needed to unblock).
- **Continue** other unblocked issues in the wave.
- **Notify the human immediately** (do not wait for wave end, unlike the wave-complete summary).
- List all parked blockers in the final hand-off PR.

### 9.2 Notification channels

- **Telegram** — default, two-way. A bot sends alerts and accepts replies, doubling as a control channel. From the phone the human can respond to a blocker, override the usage limit for a wave, pause, resume, request status.
- **Resend email** — optional, off by default. Suited to digests/summaries rather than instant alerts.
- **UI toggle** — choose Email and/or Telegram. Telegram on by default, email off. Both can be on together.

### 9.3 Command scope

Telegram accepts commands from day one: at minimum `status`, `pause`, `resume`, `override usage`, and free-text blocker responses that the engine feeds into the relevant AI session.

---

## 10. Credentials

- **GitHub: fine-grained PAT.** Scoped to the project repos only. No permission to push to protected branches (`main`, `dev`). Can push the agent branch and open PRs. Backs the 7.3 backstop.
- **AI provider auth:** Claude subscription login or `ANTHROPIC_API_KEY`; OpenAI / Google equivalents for the other providers. Switchable in config/UI.
- **Notion:** integration token scoped to the project workspace.
- **Telegram:** bot token + the human's chat ID.
- **Resend:** existing account API key.
- All secrets live in the container's secret store, never in the repo, never readable by the agent role.

---

## 11. Observability and efficiency review

### 11.1 Two-layer logging

- **Layer 1 — raw capture:** every AI session writes a compressed structured event stream (timestamp, role, model, wave, issue, event type, token deltas, tool calls, retries, outcome). Bulky, because tool outputs dominate.
- **Layer 2 — traces + rollups:** each session emitted as a Langfuse trace (self-hosted), queryable by issue, skill/step, wave, month. Aggregated rollups in SQLite. Reports read Layer 2; Layer 1 is opened only when drilling into a flagged session.

### 11.2 Storage cap and retention

- **Cap ~50 GB**, tiered retention:
  - Raw transcripts (Layer 1): ~90 days.
  - Langfuse traces: ~180 days.
  - Aggregated rollups: indefinite (megabytes).
- Prune oldest raw data first as the cap approaches. Rollups preserve long-term trends after raw data ages out.
- Separate from the git working copies of the repos.

### 11.3 Efficiency reports

Available on demand, per wave, and per month. The report identifies where prompts/workflow can be tightened:

- Tokens per issue, per role, per skill/step, per wave.
- Retry rates and where they cluster.
- Model usage vs outcome (where a cheaper model would have sufficed without quality loss, and where it would not).
- Month-over-month regression detection (tokens-per-issue or retry-rate creeping up).
- Concrete suggestions: verbose prompts/skills, looping steps, context loaded but unused.

### 11.4 AI-engineering alignment

Langfuse is the standard open-source LLM-observability tool. Powers these reports and builds familiarity with tracing/eval tooling expected in AI-engineering work.

---

## 12. UI scope (React)

Authenticated (login required even on LAN). **Auth mechanism:** single-user login — a password verified against an argon2 hash (held as the `AUTH_PASSWORD_HASH` secret), establishing an HTTP-only server-side session cookie; one FastAPI dependency guards all routes and the SSE stream. No user table or registration (single human, single local server). Minimum capability set:

- **Run control:** select project, select wave(s), select provider/plan, start/stop, pause/resume.
- **Live progress:** current wave, current issue, current role/session, normalised event stream (SSE).
- **Usage gauges:** all applicable meters for the active provider, governing meter highlighted, the 80% line shown, override switch.
- **Blockers:** live list of parked blockers with detail; respond inline (same as Telegram).
- **PRs:** surfaced hand-off PRs with bodies and human checklists.
- **Efficiency reports:** on-demand / per-wave / per-month views (Langfuse-backed).
- **Notifications:** channel toggle (Email and/or Telegram; Telegram default-on).
- **Config view:** read/edit project config, provider/model mapping, allowlist.

Provider onboarding is handled in config, not a UI wizard.

---

## 13. Tech stack summary

| Concern | Choice |
|---|---|
| Backend / orchestration | Python, FastAPI, Pydantic, asyncio |
| Live updates | Server-Sent Events |
| UI | React (Vite) + auth |
| State store | SQLite -> Postgres migration path |
| LLM observability | Self-hosted Langfuse |
| AI providers | Claude Agent SDK (default), Codex CLI, Gemini CLI — behind one adapter |
| Notifications | Telegram (default, two-way) + Resend (optional) |
| Isolation | Docker, Squid egress allowlist proxy, GitHub branch protection |
| VCS auth | Fine-grained GitHub PAT |

---

## 14. Build phases (suggested)

1. **Foundations:** container + egress proxy + filesystem binding; FastAPI skeleton + auth; SQLite state; config schema + `project.yaml` loader.
2. **Git/PR engine:** branch lifecycle (agent branch, feature branches, local-only flow, hand-off push + PR), test/lint/typecheck gates.
3. **Claude adapter + wave loop:** full end-to-end on Trive with one provider. Instruction-file generation. Internal review loop.
4. **Usage monitor:** meters, 80%-most-restrictive rule, hard pause/resume, peak-hour throttle, override, Agent SDK credit handling.
5. **Trackers + notifications:** GitHub<->Notion sync; Telegram two-way + Resend; blocker escalation.
6. **Observability + UI:** Langfuse integration, two-layer logging, efficiency reports; React UI wiring it all together.
7. **Multi-provider:** Codex and Gemini adapters behind the existing interface.

---

## 15. Open items to resolve before/while building

Resolved (kept here for traceability; detail is in the referenced sections):

- **Agent branch name** — per-wave `code-runner/<wave-slug>` (full slug), created fresh per wave, deleted after merge. See 5.1.
- **Retry counts** — defaults 3 test-fix attempts, 2 review-change cycles; configurable per project in `project.yaml`. See 16.3 `limits`.
- **Model mapping** — Opus for planning and review, Sonnet for implementation (Opus escalation on complex issues) and QA semantic judgement. See 16.3 `provider.models`.
- **Plan file ownership** — hybrid: human (or planner persona at setup) owns the forward-looking wave structure/intent; the engine owns the status markers, updated as work completes. Mirrors Trive `process-close-milestone` Step 4.
- **Postgres switch trigger** — switch when more than one process needs to write the state store concurrently (e.g. UI/API split from the engine, multiple project engines, or moving off the single local server). Until then SQLite in WAL mode. A single async process with parallel sessions stays on SQLite.
- **Auth mechanism** — single-user password (argon2 hash via `AUTH_PASSWORD_HASH`) establishing an HTTP-only server-side session cookie; one FastAPI dependency guards all routes + SSE. No user table or registration. See 12.

Still open:

- Provider adapter interface depth (per-provider event mapping, usage extraction, blocker detection) — deferred, not an MVP blocker. MVP is Claude-only; the only requirement is keeping Claude specifics behind the `ProviderAdapter` interface (3.3 note) so Codex/Gemini can be added later as an additive change. Specify fully only when a second provider is actually wanted.
- Profile generation UX detail (UI trigger flow for the tech-lead session) — human-confirmed before write is decided (17.5); the surrounding UX is a phase-6 detail.
- Usage-meter polling cadence — how frequently the monitor reads meter levels to step the concurrency cap down (18.7). Phase-4 implementation detail. (Resolution direction: the same poll that reads `/oauth/usage` for the threshold, cached ~5 min as the community tools do, feeds the cap-stepping; sub-5-min polling is unnecessary.)

---

## 16. `project.yaml` schema

The single declarative config that points Code Runner at a project. One file per project, lives in the project root directory. Loaded and validated (Pydantic) at startup; a malformed config fails fast before any wave begins.

### 16.1 Design rules

- **Declarative only.** Describes the project. Contains no logic beyond the test/lint/typecheck command strings. Everything else the engine derives.
- **Convention over configuration.** Defaults cover the minimal case (one repo, GitHub + Notion, Claude). The Trive three-repo case fills in more.
- **Secrets by reference, never by value.** Holds the env-var names the engine resolves from the container secret store. Never tokens. Safe to commit.
- **GitHub is authoritative for waves.** A wave = all GitHub milestones sharing a name across the project's repos. No explicit wave list needed in the common case.

### 16.2 Top-level keys

| Key | Required | Purpose |
|---|---|---|
| `project` | yes | Identity and root directory. |
| `integrations` | yes | GitHub and Notion connection refs. |
| `branches` | no (defaults) | Integration branch, agent branch pattern, sync strategy. |
| `waves` | no (defaults) | How waves are derived. Defaults to milestone-name grouping. |
| `repos` | yes | Per-repo paths, roles, and gate commands. |
| `provider` | no (defaults) | Default provider, plan, per-role model mapping. |
| `usage` | no (defaults) | Threshold, peak-hour throttle, meter overrides. |
| `egress` | no | Allowlist additions beyond the built-in defaults. |
| `notifications` | no (defaults) | Channels and defaults. |
| `limits` | no (defaults) | Retry counts. |
| `secrets` | yes | Names of env vars the engine resolves. Never values. |

### 16.3 Field detail

**`project`**

- `name` — string, used in PR titles, notifications, logs.
- `description` — string, optional.
- `root` — absolute path to the directory containing the repos. The container mount boundary. The agent cannot see outside this.

**`integrations`**

- `github.owner` — org or user that owns the repos.
- `github.project_board` — Project board number/id, for status reads/writes.
- `notion.workspace` — workspace ref.
- `notion.dashboard_page` — the project's top-level Notion page. The engine auto-discovers the Technical Tasks and User Stories databases nested under this page; they do not need explicit refs.
- `notion.social_context_page` — ref to the 📣 Social Media Context page the engine updates at hand-off (5.4 step 6).
- Notion refs accept a full URL or a bare page/database id.

**`branches`**

- `integration` — the branch the agent branches from and PRs back to. Default `dev`.
- `agent_pattern` — the per-wave agent branch name pattern. Default `code-runner/<wave-slug>`, where `<wave-slug>` is the wave identifier slugified to be branch-safe. The branch is created fresh per wave and deleted after its PR merges (not persistent across waves).
- `sync_strategy` — how the agent branch is kept current with the integration branch. `merge` (default) or `rebase`. Spec mandates merge.

**`waves`**

- `source` — `milestone-name` (default), `explicit`, or `plan-file`.
  - `milestone-name`: a wave is all milestones with the same name across the project's repos. No further config.
  - `explicit`: provide a `list` below.
  - `plan-file`: read wave structure from `plan_file`.
- `plan_file` — path to the human-readable plan (the `IMPLEMENTATION_PLAN.md` equivalent). Always allowed as the readable mirror even under `milestone-name`; only authoritative when `source: plan-file`.
- `list` — only when `source: explicit`. Each entry: wave name + which repo/milestone pairs it contains.
- Cross-repo ordering within a wave is derived by the engine from the issue dependency declarations (as the Trive skills already do), not from this config.

**`repos`** — a list. Each entry:

- `name` — must match the GitHub repo name.
- `path` — relative to `project.root`.
- `role` — free-text label (`backend`, `frontend`, `admin`, …). Drives which instruction skills apply.
- `backend` — boolean. Explicit flag (not inferred from `role`) that turns on the API-contract-verification step for this repo. Default `false`.
- `package_manager` — `pnpm` / `npm` / `pip` / `poetry` / …. Informs which registries the egress allowlist needs.
- `commands.test` — full command string for the test gate. Omit/empty = no test gate.
- `commands.lint` — lint gate command. Omit = skipped.
- `commands.typecheck` — typecheck gate command. Omit = skipped.

**`provider`**

- `default` — `claude` (default) / `codex` / `gemini`.
- `plan` — `pro` / `max` / `api` (and provider equivalents). Drives which usage meters apply.
- `models` — per-role mapping: `planning`, `implementing`, `reviewing`. Provider-specific model strings, expressed by tier so the mapping survives model releases (the exact string is config). **Default tier mapping (Claude):** planning = Opus (architecture/decomposition is highest-leverage and infrequent); reviewing = Opus (the reviewer's value is catching flaws, and the flagship is materially better at not letting flaws pass — a cheap reviewer that misses things defeats the out-of-the-loop model); implementing = Sonnet default with per-issue escalation to Opus on flagged-complex issues (Sonnet is within 1-2 points of Opus on coding at ~40% less cost); qa-reviewer semantic judgement = Sonnet (narrower than code review; the programmatic half is engine-deterministic). Haiku is not used in the main loop. This realises Principle 3: best code per token, Opus where judgement quality is the whole point, Sonnet where it is near-parity cheaper. Switchable per wave from the UI. Codex/Gemini get an equivalent tier mapping when those adapters are built.
- Provider is project-wide; no per-repo override (revisit later if needed).

**`usage`**

- `threshold_percent` — pause point. Default `80`.
- `peak_hour_throttle` — boolean. Default `true`.
- `meters` — optional explicit meter limits/overrides where the plan's defaults need adjusting (e.g. known API budget).

**`egress`**

- `allow` — extra hostnames appended to the built-in allowlist (GitHub + the registries implied by each repo's `package_manager` + the active provider's model API). Most projects need nothing here.

**`notifications`**

- `telegram` — boolean. Default `true`.
- `email` — boolean. Default `false`.
- Channel credentials are in `secrets`, not here.

**`limits`**

- `test_fix_attempts` — default `3`.
- `review_cycles` — default `2`.

**`secrets`** — map of logical name → env-var name the engine resolves from the container secret store. Never the secret itself. Expected keys depend on enabled integrations/providers: `github_pat`; `anthropic_api_key` / `openai_api_key` / `google_api_key`; `notion_token`; `telegram_bot_token`, `telegram_chat_id`; `resend_api_key` (if email enabled).

### 16.4 Minimal example (one repo, defaults everywhere)

```yaml
project:
  name: My Tool
  root: /projects/my-tool

integrations:
  github:
    owner: my-user
    project_board: 1
  notion:
    dashboard_page: <notion-page-ref>
    social_context_page: <notion-page-ref>

repos:
  - name: my-tool
    path: .
    package_manager: pnpm
    commands:
      test: pnpm test
      lint: pnpm lint
      typecheck: pnpm typecheck

secrets:
  github_pat: GITHUB_PAT
  anthropic_api_key: ANTHROPIC_API_KEY
  notion_token: NOTION_TOKEN
  telegram_bot_token: TELEGRAM_BOT_TOKEN
  telegram_chat_id: TELEGRAM_CHAT_ID
```

Everything not stated uses defaults: integration branch `dev`, per-wave agent branch `code-runner/<wave-slug>`, waves by milestone name, provider Claude, 80% threshold, peak-hour throttle on, Telegram on / email off, 3 test-fix / 2 review cycles.

### 16.5 Worked example — Trive Services (three repos)

```yaml
project:
  name: Trive Services
  description: Multi-tenant local services booking platform.
  root: /projects/trive-services

integrations:
  github:
    owner: Ryan-Atkinson87
    project_board: 3
  notion:
    workspace: trive-services
    dashboard_page: <trive-services-page-ref>
    social_context_page: <trive-social-context-page-ref>

branches:
  integration: dev
  agent_pattern: code-runner/<wave-slug>
  sync_strategy: merge

waves:
  source: milestone-name
  plan_file: IMPLEMENTATION_PLAN.md   # readable mirror; not authoritative

repos:
  - name: trive-backend
    path: trive-backend
    role: backend
    backend: true
    package_manager: pnpm
    commands:
      test: pnpm test
      lint: pnpm lint
      typecheck: pnpm typecheck

  - name: trive-frontend
    path: trive-frontend
    role: frontend
    package_manager: pnpm
    commands:
      test: pnpm test
      lint: pnpm lint
      typecheck: pnpm typecheck

  - name: trive-admin
    path: trive-admin
    role: admin
    package_manager: pnpm
    commands:
      test: pnpm test
      lint: pnpm lint
      typecheck: pnpm typecheck

provider:
  default: claude
  plan: max
  models:
    planning: <opus-tier model string, e.g. claude-opus-4-8>
    implementing: <sonnet-tier default, e.g. claude-sonnet-4-6; opus-tier on flagged-complex issues>
    reviewing: <opus-tier model string, e.g. claude-opus-4-8>

usage:
  threshold_percent: 80
  peak_hour_throttle: true

notifications:
  telegram: true
  email: false

limits:
  test_fix_attempts: 3
  review_cycles: 2

secrets:
  github_pat: GITHUB_PAT
  anthropic_api_key: ANTHROPIC_API_KEY
  notion_token: NOTION_TOKEN
  telegram_bot_token: TELEGRAM_BOT_TOKEN
  telegram_chat_id: TELEGRAM_CHAT_ID
```

---

## 17. Canonical instruction source, personas, and rendering

The workflow rules are authored once and rendered into whatever format the active provider expects at run start. There are never two hand-maintained rule sets. This section defines the three-layer structure (skills, personas, execution profile) and how they render.

### 17.1 The drift problem this solves

Claude Code reads a skills directory (per-skill files + frontmatter). Codex and Gemini read a single `AGENTS.md`. Hand-maintaining both means the same rule lives in two places and diverges. Instead: one canonical set, multiple generated outputs. The non-Claude files are generated, never edited.

It also solves a known failure in the Trive build: the orchestrator checks responsiveness and accessibility while reviewing backend PRs. Under this model a backend review session is composed without those skills, so it structurally cannot drift into them.

### 17.2 Three layers

```
Layer 1  Canonical skills           what to do, per lifecycle stage (executor-tagged)
Layer 2  Persona system             who applies judgement (type × speciality, composed)
Layer 3  Project execution profile  which personas + stage routing a project uses
                                     (generated by the tech-lead setup session)

   profile  ->  compose personas  ->  pull each persona's stage skills
            ->  render per provider (CLAUDE.md+skills | AGENTS.md)
```

### 17.3 Layer 1 — canonical skills

The rule library. Provider-neutral. Structured form (not free Markdown) so it can be transformed: each skill is a unit with metadata + body. Markdown body is fine; the metadata is what makes it renderable.

Each skill carries:

- `id` — stable identifier.
- `stage` — lifecycle stage it belongs to (below).
- `executor` — `ai` or `engine`. Determines whether the skill is rendered into an AI session's instructions, or is a spec the engine follows deterministically (and may surface to an AI only when judgement is needed, e.g. interpreting a test failure).
- `applies_to` — `neutral` or a provider list (`claude` / `codex` / `gemini`). Provider-specific mechanics (Claude `allowed_tools`, Codex `sandbox_mode`) are tagged so they render only for that target.
- `specialities` — optional list; if set, the skill loads only for personas carrying a matching speciality. This is the mechanism that keeps WCAG skills out of a backend review.
- `body` — the rule text.

**Lifecycle stages** (each tagged with its primary executor):

| Stage | Executor | Notes |
|---|---|---|
| `plan` | AI | Decompose a wave into issues, write acceptance criteria. |
| `implement` | AI | Write code; write new tests as part of this. |
| `test` | engine | Run the suite. Skill doc defines the gate and how failures route back to `implement`. AI involved only to fix. |
| `contract-verify` | engine + AI | Backend only. Compare against the API Surface. |
| `review` | AI | Judge code against spec and boundaries. |
| `qa` | engine + AI | Engine runs the programmatic half (status codes, shapes, contrast math). AI judges the parts needing reasoning (ARIA semantics, UX). Human-only items become PR checkboxes. |
| `integrate` | engine | Branch merge, PR assembly, board + Notion sync, Social Media Context update. |
| `escalate` | engine | Detect blocker, park, notify. |
| `cross-cutting` | neutral | Boundaries, security, spec-as-source-of-truth. Obeyed by every stage. |

The current Trive skills map onto these stages directly (see Section 4.1 mapping). They become the seed canonical set.

### 17.4 Layer 2 — persona system

A persona is the unit that runs an AI session. Personas are **composed, not hand-written**, so a project can have as many as it needs without a maintenance explosion. Two axes:

- **Type** (kind of judgement) — small fixed set: `planner`, `implementor`, `reviewer`, `qa-reviewer`.
- **Speciality** (domain lens) — open-ended: `backend`, `frontend`, `admin`, `accessibility` (WCAG), `responsiveness`, `ui-ux`, `security`, `api-contract`, `performance`, …

A concrete persona is `type × speciality`, e.g. `implementor × backend`, `qa-reviewer × accessibility`, `reviewer × security`. Composition at render time = base type prompt + speciality overlay + the stage skills whose `specialities` match (or are unset/neutral). Overlays are themselves structured (metadata + body) like skills, so the same renderer handles them.

Adding a speciality is writing one overlay, not a new agent. Adding a persona to a project is naming a `type × speciality` pair in the profile, not authoring a prompt. Each composed persona maps to exactly one fresh provider session per task (consistent with Section 4.3); personas do not share a session.

**Tech-lead persona (setup-time, not per-iteration).** A distinct `tech-lead` type acts as principal engineer. Its job is the project-shaping decision: which persona-compositions this project instantiates, which stages run AI vs engine, any project-specific routing. It runs once at onboarding and only re-engages on structural change (new repo, newly discovered cross-cutting concern). It does not run every wave or every issue, so it adds no per-iteration cost. Its output is Layer 3.

### 17.5 Layer 3 — project execution profile

A separate generated file (`execution-profile.yaml`), distinct from `project.yaml`:

- `project.yaml` is human-authored config (Section 16).
- `execution-profile.yaml` is the tech-lead session's output and has a different change cadence (regenerated on structural change, not hand-edited).

The profile declares, for this project:

- Which personas are instantiated (the `type × speciality` list).
- Per stage: executor confirmation (AI persona vs engine) where it differs from the default.
- Routing: which persona handles which repo/role; which QA specialities apply (e.g. Trive: accessibility + responsiveness + ui-ux; a backend-only API project: none).
- Any project-specific skill overrides or additions.

**Generation:** the tech-lead session proposes the profile from `project.yaml` + a repo scan; the human confirms before it is written (the human is the actual principal engineer signing off the proposed split). After first sign-off, the engine may regenerate automatically on structural change.

Example shape (Trive):

- Personas: `planner`, `implementor×backend`, `implementor×frontend`, `implementor×admin`, `reviewer×backend`, `reviewer×frontend`, `reviewer×admin`, `qa-reviewer×accessibility`, `qa-reviewer×responsiveness`, `qa-reviewer×ui-ux`.
- Backend PRs route to `reviewer×backend` only — no accessibility/responsiveness skills loaded.
- QA specialities: accessibility, responsiveness, ui-ux.

Example shape (backend-only API project):

- Personas: `planner`, `implementor×backend`, `reviewer×backend`, `reviewer×security`.
- No QA UI specialities. No frontend personas.

### 17.6 Where the canonical set lives

Tool-level base (versioned with the tool, applied to every project) + optional per-project additions/overrides declared in the profile. Trive's rules are essentially the base; a new project writes only what differs.

### 17.7 Rendering

At run start, per repo:

1. Read `execution-profile.yaml` → the persona list and routing.
2. For each persona, compose: base type + speciality overlay + matching stage skills (filtered by `specialities` and `applies_to`).
3. Render to the active provider's format:
   - Claude → `CLAUDE.md` (cross-cutting + engine-contract summary) + the per-persona skill files in Claude Code's expected layout.
   - Codex / Gemini → a consolidated `AGENTS.md` containing the same composed content for the personas in play.
4. Engine-executor skills are not rendered into AI instructions; they are the engine's own spec. They surface to an AI session only at the defined hand-back points (e.g. a failing test fed to `implement`).

Provider-specific skills (`applies_to` ≠ neutral) render only for their target, so a Claude run never shows Codex sandbox rules and vice versa.

---

## 18. Crash recovery and concurrency

### 18.1 Recovery principle

State lives in git and the trackers, not in agent context (Principle 2). Recovery is therefore not memory restoration; it is reading durable state on restart and inferring where work stopped. Every stopping point must leave an unambiguous, readable trace.

**Source-of-truth order:** git and GitHub are the truth. The engine's own state markers (18.3) are a hint to avoid re-scanning, never authoritative. If a marker disagrees with git, git wins.

### 18.2 Stopping points and recovery

Walking the wave loop (Section 4.2), for each step, what is durable on restart:

| Died during | Durable trace | Recovery |
|---|---|---|
| Dependency check (a) | Nothing changed | Re-run; no cost |
| Feature branch created (b) | Branch exists, no commits | Reuse/reset, restart implement |
| AI implementing (c) | Branch may have partial/uncommitted changes | **Discard and restart clean** (18.4) |
| Test gate (d) | Commits exist, no internal PR | Re-run tests (deterministic, safe to repeat) |
| Internal PR + review (f/g) | Internal PR exists | Re-read review state, resume |
| Merge to agent branch (h) | Merged or not (git merge is atomic) | If merged, advance; else re-attempt |
| Board / Notion sync (h) | May be partially applied | **Idempotent re-sync** (18.5) |

Two steps are genuinely ambiguous and need explicit rules: mid-implementation (c) and half-finished sync (h). The rest are safe to re-run or trivially checkable.

### 18.3 Per-issue state markers

The engine writes a marker per in-flight issue to its own SQLite (not the trackers), recording the last completed step. On restart it reads markers and, per issue, either resumes at the next step (if the last completed step was deterministic and idempotent) or resets the issue (if it died mid-AI-session).

This is the engine's crash log, distinct from board state. It bounds restart work: only in-flight issues need evaluating, not the whole wave. Because of the concurrency cap (18.6), at most N issues are ever in flight.

### 18.4 Mid-AI-session crash: discard and restart

A partial working tree from a dead AI session cannot be trusted; the session's reasoning context is gone. **Never resume a half-written AI session.**

On restart, if an issue's feature branch has uncommitted changes, or commits but no opened internal PR, discard the branch and restart that issue clean from the agent branch. Confirmed policy: the partial diff is not salvaged or preserved for inspection; it is discarded. This wastes one issue's work but is always correct, and matches the Trive pattern (an issue `In Progress` with no open PR is re-selected and re-worked). The fresh-session principle makes this cheap to reason about: there is no state to recover, so the engine does not try.

### 18.5 Idempotent sync

Every tracker-sync operation is "make the target match the source," not "apply a delta." Re-running after a partial failure converges to the correct state regardless of how far the previous run got. This is a stated design rule for the tracker-sync engine (GitHub board and Notion), not an afterthought: it is what makes a crash mid-sync recoverable by simply running the sync again.

### 18.6 Concurrency model

Within one wave: **parallel across repos, sequential within each repo, serialised merges, configurable cap.**

- Each repo runs at most one active issue at a time (sequential within).
- Different repos run concurrently (parallel across).
- The cap defaults to the number of repos in the project (one active issue per repo). Cap of 1 = fully sequential.

**Why not more parallel.** Multiple concurrent issues in the same repo would start work against a contract still changing in a sibling session, breaking the dependency ordering the engine derives. One-per-repo matches the natural structure: the repos are largely independent workstreams.

**Cross-repo dependencies** are handled as in Trive: a dependent issue either uses an MSW stub (so it does not need the live sibling session) or is ordered after its dependency reaches a stable done state. Parallelism across repos does not break this, because a dependent issue is not started until its dependency is stable. The engine's existing dependency ordering covers it.

**Serialised merge queue.** Sessions run in parallel, but merging a feature branch into the agent branch is one-at-a-time per repo, eliminating merge races. Review sessions (AI) may run concurrently; only the merge moment serialises.

### 18.7 Concurrency cap as a usage lever

The usage monitor steps the cap down as the governing meter climbs, rather than only hard-pausing at the threshold: 3 → 2 → 1 → pause. This glides into the pause instead of hitting a wall, and ensures the final pause has at most one in-flight session to drain cleanly. The hard pause (Section 6.2) remains the floor; the stepping-down is a smoothing layer above it.

This also bounds crash recovery: with the cap and per-repo sequential work, at most N issues are ever in flight, so restart evaluates at most N issues for resume-or-reset.

### 18.8 Interaction summary

- Cap bounds in-flight issues, which bounds the restart evaluation set.
- Mid-AI-session crashes discard cleanly, so no partial-state recovery logic is needed.
- Idempotent sync means mid-sync crashes recover by re-running.
- Markers are hints; git/GitHub is truth, so markers can never cause incorrect recovery.
- The usage monitor steps the cap down, giving a graceful drain into pause with a single in-flight session at the floor.

### 18.9 Long-session checkpointing

A single AI session that runs too long accumulates context bloat and drifts in quality. To bound this, a session has a **soft checkpoint at 30 minutes of wall-clock**. This is a checkpoint boundary, not a hard kill: the engine never interrupts mid-action.

**Mechanism.** When a session crosses 30 minutes, the engine signals a stop at the **next safe boundary** (after the current tool call/edit completes and changes are committed). It then:

1. Logs progress to the per-issue state marker (18.3) — what was done, where it stopped.
2. Commits the work in progress on the feature branch.
3. Clears context and starts a **fresh session that resumes the same issue**, re-reading the committed state and the issue's acceptance criteria and continuing from there.

Because the stop only ever happens at a committed point, this never triggers the discard-and-restart path (18.4); no work is lost. It is a context refresh, not a recovery.

**Resume the same issue, not the loop.** The fresh session continues the issue it was working, rather than re-entering issue selection. Interrupting to switch issues mid-stream would waste the partial progress.

**Stuck-agent guard.** If the same issue hits the 30-minute checkpoint **3 times without producing an internal PR**, that is the signal the agent is stuck or looping rather than progressing. On the third checkpoint the engine parks the issue as a blocker (`escalate`, Section 9) and notifies the human, instead of starting a fourth session. This stops endless checkpoint cycling on a genuinely stuck issue while still allowing two clean context refreshes for legitimately long work.

The checkpoint count is per-issue and resets when the issue produces a PR or is parked.
