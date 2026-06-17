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
