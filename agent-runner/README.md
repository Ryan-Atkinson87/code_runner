# agent-runner

Sandboxed tool-execution service for Code Runner (Spec §7.1, §7.2). Runs bash and text-editor
tool calls on behalf of the orchestration engine's AI sessions, inside the network-locked,
read-only `agent-runner` container rather than in `orchestrator-api` itself.

Internal-only: reachable from `orchestrator-api` over the `agent_net` Docker network, never
published to the host or to `code_runner`. Every request must carry an `Authorization: Bearer
<AGENT_RUNNER_TOKEN>` header matching the shared secret; requests are rejected with 401
(wrong/missing token) or 503 (no token configured).

## Endpoints

- `GET /health`
- `POST /v1/bash` — `{"command": str, "restart": bool}` → `{"output": str}`
- `POST /v1/text-editor` — `{"command": "view"|"create"|"str_replace"|"insert", "path": str, ...}`
  → `{"output": str}`

Tool-level failures (permission denied, execution errors) are returned as `200` with the failure
description in `output`, matching the shape the Claude adapter already expects from its
tool-result content — only transport-level failures (auth, timeout, unreachable) are non-200.

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) for environment and dependency management

## Dev commands

All commands run inside the project's virtual environment via `uv run`.

```bash
# Install dependencies (creates .venv on first run)
uv sync --dev

# Lint
uv run ruff check .

# Format (check only)
uv run ruff format --check .

# Format (apply)
uv run ruff format .

# Type-check
uv run pyright

# Tests
uv run pytest
```
