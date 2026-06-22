# Code Runner — Dev Diary

## Milestone 1: Foundations — 2026-06-17

### What was done

The entire backend foundation was built from scratch across eight issues. The orchestrator-api project was scaffolded with Python 3.13, FastAPI, and a modern toolchain (uv for dependency management, ruff for linting and formatting, pyright for type checking, pytest for testing). On top of this scaffold, four core subsystems were built in parallel: a SQLite state store running in WAL mode with a migration framework, a Pydantic-validated `project.yaml` configuration loader that fails fast on invalid input, a secrets-by-reference resolver that reads environment variable names from config and resolves their values at runtime (keeping `.env` gitignored and `.env.example` committed), and a FastAPI application skeleton with a health endpoint and settings loading.

With those in place, single-user authentication was added — argon2 password hashing against an `AUTH_PASSWORD_HASH` secret, HTTP-only session cookies, rate-limited login, and a FastAPI dependency that guards all routes and SSE endpoints. The Docker Compose stack was then assembled: Traefik as the ingress proxy, orchestrator-api, orchestrator-ui (placeholder), Langfuse with its Postgres database, the agent-runner container, and a Squid-based egress proxy. The final piece was the agent-runner network lockdown: iptables rules that DROP all outbound traffic except through the Squid proxy, which enforces a domain allowlist. This ensures the AI agent container physically cannot reach any host not on the allowlist — the security boundary is infrastructure, not agent goodwill.

### Why it was done

Foundations exists because every subsequent phase depends on having a running, authenticated, containerised backend with persistent state and validated configuration. The Specification's first principle — algorithmic by default, LLM only for judgement — requires a deterministic Python engine before any AI provider is invoked. The security model (Spec §7, §10) demands that secrets never appear in committed files and that the agent container is network-locked before it ever runs. Building this layer first means the git/PR engine, Claude adapter, and usage monitor can all assume a working, secure runtime beneath them.

### Effect on the project

The system now has a deployable local stack with all seven services defined, a tested backend API behind authentication, and a state store ready for the engine's operational data. The agent-runner is sandboxed at the network level — the egress proxy allowlist is the only path to the internet, and the container's filesystem mounts are bounded. All 37 tests pass, lint and type checking are clean, and the CI-equivalent gates are established for every future PR.

Phase 2 (Git/PR engine) is now unblocked. It will build the deterministic git operations wrapper, branch lifecycle management, test/lint/typecheck gating, and the hand-off mechanism that pushes agent branches and opens PRs — the mechanical layer between the AI writing code and that code reaching review.

## Milestone 2: Git/PR Engine — 2026-06-19

### What was done

The deterministic git and GitHub layer was built across seven issues, forming the mechanical backbone that sits between AI-written code and human review. The work started with a low-level git operations wrapper (`app/git/repo.py`) — every `git` command the engine will ever run is bounded to an explicit repo path, uses structured error types, and runs through a single async subprocess interface rather than shelling out ad hoc. On top of this, two branch lifecycle managers were built: the agent-branch manager handles per-wave branch creation from `main`, merge-sync (rebasing the agent branch onto `main` between waves), and deterministic slug derivation from project and wave metadata; the feature-branch manager handles per-issue branches off the agent branch, review diffs, a serialised merge queue that prevents concurrent merges from corrupting the agent branch, and branch cleanup after merge.

In parallel with the branch chain, two independent subsystems were built. The gate runner (`app/gates/runner.py`) executes test, lint, and typecheck commands as configured in `project.yaml`, captures structured pass/fail results per repo, and distinguishes between gate failure (tests failed) and infrastructure failure (command not found, timeout). The GitHub API client (`app/github/client.py`) is scoped to exactly two operations — pushing a branch and creating a pull request — matching the PAT permissions the Specification requires for hand-off.

These converged in the hand-off engine (`app/handoff/engine.py`), which pushes the agent branch to the remote and opens one structured PR per repo with a body generated from the wave's issue list, gate results, and a human review checklist. The final piece was crash recovery: branch-state inference that reads the git graph on startup to determine where a previous run left off, and a discard-and-restart mechanism that cleanly resets a corrupted agent branch back to `main` when recovery isn't possible.

### Why it was done

The Specification's first principle — algorithmic by default — demands that git operations, branch management, quality gating, and PR creation are entirely deterministic. The AI writes code; the engine handles everything else between that code and review. This phase exists because Phase 3 (the Claude adapter and wave loop) needs a fully mechanical git layer beneath it — the wave loop calls `agent_branch.create()`, `feature_branch.merge()`, `gate_runner.run()`, and `handoff.execute()` as deterministic steps, never asking the AI to run `git` commands or create PRs. Crash recovery was included because long-running autonomous agents will inevitably be interrupted, and the engine must resume or reset without human intervention.

### Effect on the project

The engine now has a complete, tested git pipeline: branch creation, per-issue feature branches with a serialised merge queue, structured quality gates, GitHub push and PR creation, and crash recovery. The test suite grew from 37 to 182 tests, all passing with clean lint and type checks. Every git operation is bounded to a repo path and uses structured errors — no raw subprocess calls leak into higher layers.

Phase 3 (Claude adapter + wave loop) is now unblocked. It will build the provider adapter interface, Claude-specific adapter, instruction-file generation, and the deterministic wave loop that sequences planning, implementation, gating, review, and hand-off — assembling the full autonomous coding pipeline on top of the git engine built here.

## Milestone 3: Claude Adapter + Wave Loop — 2026-06-20

### What was done

The full autonomous coding pipeline was assembled across seventeen issues in three parallel workstreams — the provider adapter, the instruction system, and the wave-loop engine — plus three human-gate enforcement issues that proved the engine's safety boundary structurally.

The provider adapter workstream defined a provider-agnostic `ProviderAdapter` interface with normalised result, event, and usage types (Spec §3), then implemented the Claude-specific adapter behind it. The Claude adapter drives the Anthropic Agent SDK, executes bash and text-editor tool calls client-side, maps raw SDK events to normalised `SessionEvent` objects, extracts git-derived artifacts from the working tree after each session, and maps session outcomes to an explicit `SessionOutcome` enum (success, test failure, blocker, timeout, error). A separate hook-lockdown layer enforces tool permissions (`allowed_tools`, strict-deny lists) and `PreToolUse`/`PostToolUse` hooks that prevent the agent from escaping its sandbox.

The instruction system workstream built a canonical skill model with YAML-frontmatter metadata, a directory-based loader with merge semantics (project skills override tool-base skills by ID), an `execution-profile.yaml` schema defining which personas a project uses, and a persona composer that assembles personas as `type × speciality` (e.g. `implementor × backend`) with stage-aware skill filtering — a backend implementor structurally cannot load accessibility or responsiveness skills. A provider-format renderer then composes the persona into concrete instruction files: a `CLAUDE.md` plus individual skill files for Claude, with the Codex/Gemini `AGENTS.md` renderer deferred to Phase 7. A tech-lead profile-generation session rounds out the instruction system — it scans the project's repositories, proposes an execution profile via an AI session, and writes it only after explicit human confirmation.

The wave-loop engine workstream built the sequencing and orchestration machinery. Per-issue state markers in SQLite track each issue through its lifecycle (queued → implementing → gating → reviewing → merged → parked), with resume-or-reset crash recovery that reads git state to decide whether to pick up where a crashed session left off or discard and restart cleanly. A concurrency scheduler runs issues parallel across repos but sequential within each, enforcing a configurable cap that doubles as a usage lever (the Phase 4 usage monitor steps it down 3→2→1→pause rather than halting abruptly). A GitHub issue/milestone reader parses dependency declarations from issue bodies and produces a topologically sorted work order. The bounded implement-gate-fix loop drives the AI through implement → test/lint/typecheck → fix cycles with 30-minute checkpointing and a stuck-agent guard. The bounded internal-review cycle fills the PR body, runs review → feedback → re-review cycles, and merges approved feature branches through the serialised merge queue. The capstone wave-loop driver assembles all of these into the end-to-end deterministic wave loop defined in Spec §4.

Three final issues enforced the human gate. An explicit `merge_pull_request` method was added to `GitHubClient` that raises `NotImplementedError` — the engine's inability to merge PRs to `main` is a structural block, not just absence of code. An end-to-end test proves the wave loop stops at PR creation (branches pushed, PR opened, no merge, no branch cleanup). An architectural CI test greps the entire codebase for any call to GitHub's merge endpoint outside the deny-method, catching any future code that tries to bypass the gate.

### Why it was done

This milestone is the core of Code Runner — the reason the tool exists. The Specification's central thesis is that everything deterministic should be deterministic, and the AI should be invoked only for planning, writing, and reviewing code (Spec §1 Principle 1). Phase 3 realises that thesis: the wave-loop driver is plain Python that reads state from git and GitHub, decides what to do next, invokes the Claude adapter for the AI-requiring steps, gates the output with deterministic test/lint/typecheck checks, and hands off to the human via a structured PR. The provider-agnostic adapter interface (Spec §3) ensures that swapping Claude for Codex or Gemini is an additive change, not a rewrite. The persona system (Spec §17) eliminates the brittle hand-written prompts that plagued the earlier Trive workflow — role boundaries are now structural, not advisory.

### Effect on the project

The system can now drive a full autonomous coding session: read a milestone's issues from GitHub, sort them by dependency, compose the right persona for each role, invoke Claude to write and review code, gate every change with tests/lint/typecheck, and push a structured PR for human review — all without human intervention until the PR is ready. The test suite grew from 182 to 487 tests, all passing with clean lint and type checks.

Three phases are now unblocked. Phase 4 (Usage monitor) will add the metering, threshold, and pause/resume machinery that prevents runaway token spend. Phase 5 (Trackers + notifications) will add Notion sync, Telegram/email notifications, and blocker escalation. Phase 7 (Multi-provider) will add Codex and Gemini adapters behind the same `ProviderAdapter` interface. Phase 6 (Observability + UI) remains blocked until Phases 4 and 5 complete.

## Milestone 4: Usage Monitor — 2026-06-22

### What was done

The usage monitoring and cost-control subsystem was built across eight issues, giving the engine the ability to observe token consumption in real time and respond with graduated throttling before hitting provider rate limits. The work started with a meter model (`app/usage/models.py`) that represents each provider's rate-limiting dimensions — five-hour rolling windows, seven-day caps, per-model quotas, Agent SDK credits, and API budget meters — as a uniform `Meter` type with a utilisation percentage. A governing-meter selection algorithm applies the "80%-most-restrictive" rule from Spec §6: whichever meter is closest to its limit governs all downstream decisions, regardless of which meter kind it is.

Two usage readers were built in parallel. The subscription reader (`app/usage/subscription.py`) polls the provider's OAuth usage endpoint with a degradation chain — if the primary endpoint is unavailable, it falls back to cached snapshots rather than failing open. The API-mode reader (`app/usage/api_reader.py`) extracts usage data from response headers during AI sessions, built and tested but left inactive until API-mode billing is needed. Both readers produce the same `UsageSnapshot` type, keeping the downstream pipeline source-agnostic.

On top of the meter model, a threshold evaluator handles the 80% governing-meter trigger and date-sensitive Agent SDK credit handling — credits that expire at month-end are treated more aggressively as the reset date approaches. A hard pause manager (`app/usage/pause.py`) halts all AI sessions when the governing meter crosses threshold, then resumes via a two-tier strategy: if the meter's reset time is known, it sleeps until reset plus a buffer; if unknown, it probes with exponential backoff (5 min → 10 → 20 → 30 min cap) using a cheap model to detect when capacity returns.

The concurrency cap stepper (`app/usage/cap_stepper.py`) provides a gentler lever between full speed and hard pause. As utilisation rises through configured bands (50% → 65% → 75%), it steps the wave scheduler's concurrency cap down from 3 → 2 → 1, reducing token burn rate before a full stop becomes necessary. An override switch and peak-hour throttle policy layer sit on top of everything — the override suppresses all usage-based gating (for urgent human-directed work), while the peak-hour throttle defers heavy work during the provider's burn window (weekday mornings Pacific time) when rate limits are most likely to bind.

The capstone issue wired everything together: the `UsageMonitor` class (`app/usage/monitor.py`) composes reader → threshold → cap-step → policy → pause/resume into a single `check()` method the wave loop calls each poll cycle, and handles provider/plan switching by tearing down and rebuilding the meter chain when the active provider changes mid-run.

### Why it was done

Autonomous coding agents can consume significant token budgets, and provider rate limits on subscription plans are hard ceilings — hitting one mid-session kills the run with no graceful recovery. The Specification (§6) requires the engine to monitor usage proactively and respond with graduated pressure rather than binary stop/start. Without this phase, the engine had no awareness of how close it was to any rate limit and no mechanism to slow down, pause, or resume. The graduated approach — cap step-down before hard pause, probe-based resume when reset time is unknown — was designed to maximise productive work time while staying within limits.

### Effect on the project

The engine now has a complete cost-control pipeline: real-time meter observation, governing-meter selection, configurable threshold evaluation, graduated concurrency reduction, hard pause with automatic resume, and policy overrides for both human intervention and time-of-day awareness. The test suite grew from 487 to 615 tests, all passing with clean lint and type checks. The usage monitor is fully integrated into the wave loop — the driver calls `monitor.check()` each cycle and responds to the returned `PolicyAction` (proceed, throttle, or pause) without any AI involvement, keeping cost control entirely deterministic per Spec §1 Principle 1.

Phase 6 (Observability + UI) remains blocked on Phase 5 (Trackers + notifications). Phases 5 and 7 (Multi-provider) are in progress. When Phase 5 completes, Phase 6 will be unblocked — its usage-gauges screen (#63) will surface the monitor state built here, and the provider/plan switching validated in this phase will be exposed through the run-control UI.
