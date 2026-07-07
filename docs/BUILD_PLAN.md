# Build Plan

Code Runner's local equivalent of a GitHub Project board — this repo doesn't use one (see
"GitHub conventions" in `CLAUDE.md`). This file is the single source of truth for build
progress and has two parts:

1. A **phase table** tracking the Spec §14 build phases through `⬜` → `🔄` → `✅`.
2. A **per-phase issue checklist** — every issue created for that milestone, in the order
   they'll be worked, checked off when its PR merges and the issue closes.

## Keeping this file current

| When | Who | What |
|---|---|---|
| A phase is about to be planned | Orchestrator (`process-plan-milestone` Step 1) | Confirm the phase's dependencies are `✅` and the phase table still matches reality |
| A new issue is created for a milestone | Orchestrator (`workflow-project-planning` Steps 4-6) | Add `- [ ] #N — Title` under that phase's "Issues" heading, in dependency order |
| A PR merges and closes an issue | Human merges; Orchestrator checks off the row (`workflow-code-review` Step 9) when confirmed | Check off the corresponding row |
| A milestone closes | Orchestrator (`process-close-milestone` Step 3) | Set the phase's status to `✅`; if the next phase's dependencies are now all `✅`, set its status to `🔄` |

## Status legend

| Symbol | Meaning |
|---|---|
| ⬜ | Not started — a dependency isn't `✅` yet |
| 🔄 | Ready / in progress — dependencies met, milestone planned or being implemented |
| ✅ | Complete — milestone closed |

## Phases (Spec §14)

| # | Phase | Status | Depends on |
|---|---|---|---|
| 1 | Foundations | ✅ | — |
| 2 | Git/PR engine | ✅ | 1 |
| 3 | Claude adapter + wave loop | ✅ | 1, 2 |
| 4 | Usage monitor | ✅ | 3 |
| 5 | Trackers + notifications | ✅ | 3 |
| 6 | Observability + UI | ✅ | 3, 4, 5 |
| 7 | Multi-provider | ✅ | 3 |
| 8 | Deployment bootstrap | 🔄 | 1, 2, 3, 4, 5, 6, 7 |

---

## 1. Foundations

Container + egress proxy + filesystem binding; FastAPI skeleton + auth; SQLite state; config
schema + `project.yaml` loader.

**Status:** ✅ (complete — milestone closed 2026-06-17)

### Issues

- [x] #1 — Scaffold orchestrator-api Python project (uv, ruff, pyright, pytest)
- [x] #2 — FastAPI application skeleton with health endpoint and settings loading _(deps: #1)_
- [x] #3 — SQLite state store: schema baseline, WAL mode, connection management _(deps: #1)_
- [x] #4 — project.yaml Pydantic schema and fail-fast loader _(deps: #1)_
- [x] #5 — Secrets-by-reference resolution and .env.example _(deps: #1)_
- [x] #6 — Single-user auth: argon2 password, session cookie, route/SSE guard _(deps: #2, #5)_
- [x] #7 — Docker Compose stack skeleton (Traefik + 7 services + Dockerfiles) _(deps: #2)_
- [x] #8 — agent-runner network lockdown: Squid egress allowlist + iptables DROP + mount boundary _(deps: #7)_

---

## 2. Git/PR engine

Branch lifecycle (agent branch, feature branches, local-only flow, hand-off push + PR);
test/lint/typecheck gates.

**Status:** ✅ (complete — milestone closed 2026-06-19)

### Issues

- [x] #9 — Deterministic git operations wrapper bounded to a repo path _(deps: #1)_
- [x] #10 — Agent-branch lifecycle: per-wave branch creation, merge-sync, slug derivation _(deps: #9, #4)_
- [x] #11 — Feature-branch lifecycle: per-issue branch, review diff, serialised merge, delete _(deps: #10)_
- [x] #12 — Test/lint/typecheck gate runner with structured per-repo results _(deps: #1, #4)_
- [x] #13 — GitHub API client for hand-off (PAT-scoped: push agent branch + PRs only) _(deps: #5)_
- [x] #14 — Hand-off engine: push agent branch and open one structured PR per repo _(deps: #10, #12, #13)_
- [x] #15 — Branch-state inference and discard-and-restart for crash recovery _(deps: #11)_

**Workable now (Phase-1 deps permitting):** #9, #12, #13 (each depends only on Phase-1 issues).
Then #10 (needs #9), #11 (needs #10), #15 (needs #11), and #14 last (needs #10, #12, #13). The
gate runner (#12) and GitHub client (#13) are independent of the branch-lifecycle chain and can
be built in parallel with it. All of Phase 2 is gated on Phase 1 merging first.

---

## 3. Claude adapter + wave loop

Full end-to-end on Trive with one provider. Instruction-file generation. Internal review loop.
Also absorbs the deterministic loop-wiring deferred from Phase 2 (per-issue state markers,
concurrency scheduler) since it sequences the wave-loop steps defined here.

**Status:** ✅ (complete — milestone closed 2026-06-20)

### Issues

Listed in dependency order. Three workstreams run largely in parallel: the **provider adapter**
(#16→#17→#18), the **instruction system** (#19→#20, #21→#22, #23), and the **wave-loop engine**
(#24, #25, #26 → #27/#28 → #29). The driver #29 is the capstone that assembles everything.

- [x] #16 — Define ProviderAdapter interface and normalised result/event/usage types _(deps: #1)_
- [x] #19 — Canonical skill model and loader (metadata + body; tool-base + per-project) _(deps: #1)_
- [x] #21 — execution-profile.yaml schema and fail-fast loader _(deps: #1, #4)_
- [x] #24 — Per-issue state markers and resume-or-reset crash recovery _(deps: #3)_ — deferred from Phase 2
- [x] #25 — Wave concurrency scheduler (parallel-across-repos, serialised merge queue, cap) _(deps: #11, #4)_ — deferred from Phase 2
- [x] #26 — GitHub issue/milestone reader and dependency-order wave assembly _(deps: #13, #4)_
- [x] #17 — Implement Claude provider adapter via Claude Agent SDK _(deps: #16, #9, #4)_
- [x] #18 — Claude tool-permission and hook lockdown (allowed_tools, strict-deny, Pre/PostToolUse) _(deps: #17)_
- [x] #20 — Persona composition (type × speciality with stage-skill filtering) _(deps: #19)_
- [x] #22 — Provider-format renderer (compose personas → CLAUDE.md + skill files) _(deps: #20, #21)_
- [x] #23 — Tech-lead profile-generation session (propose profile, human-confirm before write) _(deps: #17, #19, #21)_
- [x] #27 — Bounded implement-gate-fix loop with 30-min checkpointing and stuck-agent guard _(deps: #11, #12, #17, #22, #24)_
- [x] #28 — Bounded internal-review cycle (PR-body fill, review→feedback→re-review, merge) _(deps: #11, #17, #22, #24)_
- [x] #29 — Wave-loop driver: end-to-end orchestration of the deterministic wave loop _(deps: #18, #22, #23, #25, #26, #27, #28, #14)_
- [x] #104 — Add merge_pull_request deny-method to GitHubClient (human-gate enforcement) _(deps: #13)_
- [x] #105 — Add end-to-end test asserting wave stops at PR creation _(deps: #29, #104)_
- [x] #106 — Add architectural CI test that greps for unauthorised GitHub merge calls _(deps: #104)_

**Workable now (Phase-1/2 deps permitting):** #16, #19, #21, #24, #26 each depend only on
Phase-1/2 issues; #25 needs Phase-2 #11. After #16: #17 → #18. After #19: #20; #20 + #21 → #22;
#17 + #19 + #21 → #23. After #24 (+ #11/#12/#17/#22): #27 and #28. The driver #29 comes last —
it integrates #18, #22, #23, #25, #26, #27, #28 and the Phase-2 hand-off engine (#14). All of
Phase 3 is gated on Phases 1 and 2 merging first.

---

## 4. Usage monitor

Meters, 80%-most-restrictive rule, hard pause/resume, peak-hour throttle, override, Agent SDK
credit handling.

**Status:** ✅ (complete — milestone closed 2026-06-22)

### Issues

Listed in dependency order. The meter model (#30) is the foundation; the two readers (#31, #32)
and the threshold/pause/cap layers build on it. #37 is the capstone that handles provider/plan
switching and wires the monitor into the live wave loop.

- [x] #30 — Usage meter model, governing-meter selection, and reader interface _(deps: #16, #4)_
- [x] #31 — Subscription usage reader: OAuth /api/oauth/usage poll with degradation chain _(deps: #30, #17)_
- [x] #32 — API-mode usage reader from response headers (built, inactive) _(deps: #30, #17)_
- [x] #33 — Threshold evaluation and date-sensitive Agent SDK credit meter handling _(deps: #30, #4)_
- [x] #34 — Hard pause and two-tier automatic resume (reset-known sleep + backoff probe) _(deps: #30, #3, #24, #17)_
- [x] #35 — Concurrency cap step-down as usage lever (3→2→1→pause) _(deps: #30, #25, #34)_
- [x] #36 — Override switch and peak-hour throttle policy modifiers _(deps: #33, #35)_
- [x] #37 — Provider/plan switch meter reload and wave-loop monitor integration _(deps: #29, #33, #34, #35, #36)_

**Workable now (Phase-1/2/3 deps permitting):** #30 first (needs #16, #4). After #30: #31, #32,
#33, and #34 can run in parallel (each needs #30 plus their Phase-3 deps — #34 also needs #3/#24).
Then #35 (needs #34 + scheduler #25), then #36 (needs #33 + #35). The capstone #37 comes last —
it integrates #33–#36 and the Phase-3 wave-loop driver (#29). All of Phase 4 is gated on Phase 3
merging first.

---

## 5. Trackers + notifications

GitHub<->Notion sync; Telegram two-way + Resend; blocker escalation.

**Status:** ✅ (complete — milestone closed 2026-06-24)

### Issues

Listed in dependency order. Three workstreams: **Notion tracker sync** (#38→#39, #40), the
**notification service** (#41→#42, with the two-way control channel #45 last), and **blockers**
(#43→#44). The Notion client (#38), notification core (#41), and blocker store (#43) are the
three independent foundations.

- [x] #38 — Notion API client: scoped, auto-discover databases, 429 backoff _(deps: #4, #5)_
- [x] #39 — Idempotent GitHub→Notion mirror sync (make target match source) _(deps: #38, #26)_
- [x] #40 — Social Media Context page update at wave hand-off _(deps: #38, #14)_
- [x] #41 — Notification service: channel abstraction, dispatcher, config toggles _(deps: #4)_
- [x] #42 — Telegram and Resend outbound notification channels _(deps: #41, #5)_
- [x] #43 — Blocker model and SQLite store: structured record, park/list/resolve _(deps: #3)_
- [x] #44 — Blocker escalation engine: park-and-continue, immediate notify, PR surfacing _(deps: #43, #42, #14, #27)_
- [x] #45 — Telegram two-way control: inbound command listener and engine dispatch _(deps: #42, #43, #29, #34, #36)_
- [x] #135 — Wire SocialContextUpdater into wave_driver hand-off sequence _(deps: #40)_

**Workable now (Phase-1/2/3 deps permitting):** #38 (needs #4, #5), #41 (needs #4), and #43
(needs #3) are the three independent starts. Then #39 (needs #38 + issue reader #26) and #40
(needs #38 + hand-off engine #14); #42 (needs #41); #44 (needs #43, #42, #14, #27). The two-way
control channel #45 comes last. **Cross-phase note:** #45 also wires Telegram `pause`/`resume`
and `override usage` into the Phase-4 usage levers (#34, #36), so it cannot finish until those
land — the rest of Phase 5 needs only Phases 1–3. #44 ties into the Phase-3 stuck-agent guard
(#27).

---

## 6. Observability + UI

Langfuse integration, two-layer logging, efficiency reports; React UI wiring it all together.

**Status:** ✅ (complete — milestone closed 2026-07-01)

### Issues

Listed in dependency order, in three workstreams: **observability backend** (#46→#47/#48 →
#49/#50), the **HTTP/SSE API surface** the UI consumes (#51–#58, each backing one screen), and the
**React frontend** (#59 scaffold → #60 shell → #61–#68 screens). The API issues pull in the
phase-3/4/5 capstones (#29, #33, #36, #44) the screens ultimately surface; the frontend scaffold
(#59) fills the `<FRONTEND_*_CMD>` placeholders in `CLAUDE.md`.

- [x] #46 — Layer 1 raw event capture: compressed per-session structured event stream _(deps: #16, #3)_
- [x] #47 — Langfuse trace emission: each AI session as a Layer 2 trace _(deps: #46, #17, #7)_
- [x] #48 — Efficiency rollups in SQLite: per issue/role/skill/wave/month aggregation _(deps: #46, #3)_
- [x] #49 — Storage cap and tiered retention pruning (~50GB; raw 90d / traces 180d / rollups indefinite) _(deps: #46, #47)_
- [x] #50 — Efficiency report generator: on-demand/per-wave/per-month + regression + suggestions _(deps: #48, #47)_
- [x] #51 — Run-control API: project/wave/provider selection + start/stop/pause/resume _(deps: #29, #2, #6)_
- [x] #52 — Live-progress SSE endpoint: normalised event stream _(deps: #46, #16, #6)_
- [x] #53 — Usage-gauges API: meters, governing meter, 80% line, override switch _(deps: #33, #36, #2)_
- [x] #54 — Blockers API: list parked blockers and respond inline _(deps: #43, #44, #2)_
- [x] #55 — PRs API: surface hand-off PRs with bodies and human checklists _(deps: #14, #13, #2)_
- [x] #56 — Efficiency-reports API: serve on-demand/wave/month report views _(deps: #50, #2)_
- [x] #57 — Config + notifications API: read/edit project config + channel toggle _(deps: #4, #41, #2)_
- [x] #58 — Profile-generation API: trigger tech-lead session, propose, human-confirm before write _(deps: #23, #2)_
- [x] #59 — Scaffold orchestrator-ui (React + Vite + TS; eslint/prettier, vitest, tsc) _(deps: #7, #2)_ — `chore`
- [x] #60 — App shell: routing, login + session auth, API/SSE client, baseline UI states _(deps: #59, #6)_
- [x] #61 — Run-control screen: select project/wave(s)/provider, start/stop/pause/resume _(deps: #60, #51)_
- [x] #193 — Run-control empty state: add interactive action link when no open waves _(deps: #61, #57)_
- [x] #62 — Live-progress screen: current wave/issue/role and SSE event stream _(deps: #60, #52)_
- [x] #63 — Usage-gauges screen: meters, governing highlighted, 80% line, override switch _(deps: #60, #53)_
- [x] #64 — Blockers screen: live parked-blocker list with inline response _(deps: #60, #54)_
- [x] #65 — PRs screen: surface hand-off PRs with bodies and checklists _(deps: #60, #55)_
- [x] #66 — Efficiency-reports screen: on-demand/per-wave/per-month views _(deps: #60, #56)_
- [x] #67 — Settings screen: config view read/edit + notifications toggle _(deps: #60, #57)_
- [x] #68 — Profile-generation screen: trigger session, review proposed profile, confirm before write _(deps: #60, #58)_
- [x] #121 — Enable pyright type-checking on test files _(chore)_
- [x] #123 — Replace lstrip with removeprefix in is_merged _(chore)_
- [x] #152 — Document Phase 6 API contracts in docs/api.md _(docs)_
- [x] #178 — Update root README.md to reflect orchestrator-ui scaffold _(chore)_
- [x] #184 — Add VITE_API_BASE_URL to root .env.example _(chore)_
- [x] #185 — Make EmptyState.action required (dev-mode warning) _(chore)_
- [x] #186 — [A11y] Layout — skip-to-content link for keyboard users _(a11y)_
- [x] #187 — [A11y] LoginPage — main landmark _(a11y)_
- [x] #188 — [A11y] LoginPage + Layout — touch targets ≥44px _(a11y)_
- [x] #189 — [Responsive] Layout sidebar 375px — hamburger/drawer for mobile _(responsive)_
- [x] #190 — [Responsive] LoginPage 375px — 16px font prevents iOS auto-zoom _(responsive)_
- [x] #191 — [Responsive] LoginPage 375px — horizontal margin on mobile _(responsive)_
- [x] #206 — [A11y] BlockersPage — move focus to resolved section after submit _(a11y)_
- [x] #207 — BlockersPage — preserve textarea content visually during submission _(ux)_
- [x] #208 — [A11y] PrsPage — deduplicate GitHub link per PR card _(a11y)_
- [x] #209 — UsageGaugesPage — inline error when usage override POST fails _(ux)_
- [x] #210 — ProfilePage — remove tautological rawYaml ternary _(chore)_
- [x] #211 — [A11y] ProfilePage — raise action-error and Reject button red to text-red-700 _(a11y)_
- [x] #219 — [A11y] ReportsPage — tab/panel ARIA linkage (id + aria-labelledby) _(a11y)_
- [x] #220 — [A11y] ReportsPage — Unicode outcome symbols aria-label _(a11y)_
- [x] #222 — [A11y] BlockersPage + SettingsPage — raise error contrast to text-red-700 _(a11y)_
- [x] #223 — [Responsive] All pages — text-base sm:text-sm on inputs/selects/textareas prevents iOS auto-zoom _(responsive)_
- [x] #205 — drive settings provider options list from GET /config/providers _(deps: #67)_

**Workable now (Phase-1/2/3/4/5 deps permitting):** #46 first (needs #16, #3). After #46: #47,
#48 (parallel); then #49 (needs #46, #47) and #50 (needs #48, #47). The API issues unblock as
their engine capstones land — #51 needs the wave-loop driver (#29); #53 needs the usage levers
(#33, #36); #54 needs the blocker engine (#44); #55 needs the hand-off engine (#14); #56 needs
the report generator (#50); #52 needs Layer 1 (#46). Frontend: #59 scaffold first (needs #7),
then the shell #60, then each screen #61–#68 pairs with its backing API. **Cross-phase note:**
Phase 6 is the convergence phase — every API issue surfaces a capstone from Phases 3–5, so it is
gated on those merging first; the run-control/usage/blocker actions reuse the same engine
dispatch points the Telegram two-way channel (#45) wired, rather than reimplementing control
logic.

---

## 7. Multi-provider

Codex and Gemini adapters behind the existing `ProviderAdapter` interface (#16). This phase
resolves the Spec §15 open item deferred "until a second provider is actually wanted" — the
per-provider event mapping, usage extraction, and blocker detection now live in each adapter
issue.

**Status:** ✅ (complete — milestone closed 2026-07-03)

### Issues

Listed in dependency order. A shared **AGENTS.md renderer** (#69) feeds both providers; the two
adapter workstreams (**Codex** #70→#71, **Gemini** #72→#73) run in parallel; the capstone (#74)
wires provider selection, run-start instruction-file generation, non-Claude usage metering, and
provider/plan switching, then proves a full wave end-to-end on a second provider.

- [x] #69 — AGENTS.md instruction-file renderer for Codex/Gemini _(deps: #22)_
- [x] #70 — Codex CLI provider adapter: invocation, event mapping, usage, blocker detection _(deps: #16, #9, #4)_
- [x] #71 — Codex permission and sandbox lockdown layer _(deps: #70)_
- [x] #72 — Gemini CLI provider adapter: invocation, event mapping, usage, blocker detection _(deps: #16, #9, #4)_
- [x] #73 — Gemini permission and sandbox lockdown layer _(deps: #72)_
- [x] #74 — Multi-provider selection, switch, and end-to-end validation _(deps: #69, #71, #73, #30, #29, #37)_
- [x] #229 — refactor: extract shared `_build_prompt` / `_derive_artifacts` helpers out of provider adapters _(deps: #70, #72)_
- [x] #230 — feat: drive RunControlPage provider list from `GET /config/providers` API _(deps: #205)_
- [x] #235 — refactor: move LockdownError to providers/utils.py _(chore, cleanup)_
- [x] #236 — fix: RunControlPage provider select defaultValue should derive from API, not hardcode "claude" _(deps: #230)_
- [x] #240 — fix: add done-callback to wave background task for exception logging
- [x] #241 — fix: remove orphaned provider label when providers list is empty
- [x] #244 — test: remove vacuous `queryByRole('group')` assertion in empty-providers test _(chore)_

**Workable now (Phase-3 deps permitting):** #69 (needs renderer #22), #70 and #72 (each need
#16/#9/#4) are the three independent starts. Then #71 (needs #70) and #73 (needs #72). The
capstone #74 comes last — it integrates the renderer (#69), both lockdown'd adapters (#71, #73),
the meter model (#30), the wave-loop driver (#29), and the provider/plan switch (#37). **Cross-phase
note:** #74 depends on Phase-4 #37 (meter reload on switch) and surfaces the provider selection
that Phase-6 run-control (#51) exposes in the UI — so although the phase is gated only on Phase 3
architecturally, the capstone cannot fully land until Phase 4 (#37) and the wave-loop driver (#29)
do. All of Phase 7 is gated on Phase 3 merging first.

---

## 8. Deployment bootstrap

Not one of the original Spec §14 phases — a gap discovered while drafting
`docs/DEPLOYMENT_PLAN.md` for a first real end-to-end run. Every subsystem from Phases 1-7 is
built and unit-tested in isolation, but nothing ever wired them together at process start
(`create_app()`), gave `orchestrator-api` filesystem access to a target project, or authored the
tool-level canonical persona/skill content the wave loop composes at render time. See
`docs/DEPLOYMENT_PLAN.md`'s blocking-issue table for how these map onto its step-by-step plan.

**Status:** 🔄 (in progress — opened 2026-07-04)

### Issues

- [x] #246 — Wire real dependencies into `create_app()` so the API boots functional, not stubbed
- [x] #247 — Add docker-compose volume mounts: `orchestrator-api` needs project-repo access + SQLite persistence _(deps: #246)_
- [ ] #248 — Claude adapter executes tool calls in-process, bypassing the `agent-runner` sandbox decided in the Spec _(tracking issue; decision recorded 2026-07-06 — option (a), scoped into #256-#260 below)_
- [x] #249 — README's documented direct health check cannot work — port 8000 not published
- [x] #250 — No canonical base-skill/persona-prompt/overlay content exists — `compose_and_render` has nothing to load in production _(discovered while implementing #246; PR #253 seeded the canonical content and loaders; PR #255 wired `app/bootstrap.py` to use it)_
- [x] #256 — Build an agent-runner executor service for bash + text-editor tool execution
- [x] #257 — Give orchestrator-api an internal-only network path to the agent-runner executor _(deps: #256)_
- [ ] #258 — Swap ClaudeAdapter's tool execution from local subprocess to the agent-runner executor RPC _(deps: #256, #257)_
- [ ] #259 — Concurrency and failure-mode parity for the executor under the wave-loop's parallel scheduler _(deps: #258)_
- [ ] #260 — Add architectural test locking in the sandboxed execution boundary; sync spec/deployment docs _(deps: #258, #259; closes #248 on merge)_
- [x] #262 — agent-runner: use constant-time comparison for bearer token auth _(non-blocking finding from #261 review)_

**Workable now:** #257 merged, unblocking #258. #259-#260 continue to unlock in sequence as
each preceding issue merges. #262 is merged.
