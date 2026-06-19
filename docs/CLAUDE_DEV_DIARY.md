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
