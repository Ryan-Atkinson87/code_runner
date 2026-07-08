# Code Runner

Self-hosted autonomous coding-agent orchestrator.

## Local stack

The full environment runs as a Docker Compose stack.

### Prerequisites

- Docker and Docker Compose v2+
- A `.env` file at the repo root (copy `.env.example` and fill in values)

### Bring the stack up

```bash
cp .env.example .env
# Fill in real values in .env

docker compose up -d --build
```

### Services

| Service | Description | URL |
|---|---|---|
| `traefik` | Ingress, TLS, routing | Dashboard: http://localhost:8080 |
| `orchestrator-api` | FastAPI backend | https://localhost/api/health |
| `orchestrator-ui` | React + Vite + TypeScript UI | https://localhost/ |
| `langfuse` | LLM observability | Internal (port 3000) |
| `langfuse-db` | Postgres for Langfuse | Internal |
| `agent-runner` | AI agent container (network-locked) | Internal |
| `egress-proxy` | Squid allowlist proxy | Internal |

### Verify

```bash
# Check all services are running
docker compose ps

# Health check (via Traefik — the only published route to orchestrator-api)
curl -k https://localhost/api/health
```

### Agent-runner network lockdown

The `agent-runner` service is isolated on a Docker-internal network (`agent_net`) with no
external route. All outbound traffic goes through the Squid `egress-proxy`, which enforces a
hostname allowlist (`squid/allowlist.txt`). The root filesystem is read-only and `/workspace` is
the only writable mount (bound to the target project directory via `CODE_RUNNER_PROJECT_DIR`).

`agent-runner` runs its own internal FastAPI service exposing bash-exec and text-editor RPC
endpoints (`POST /v1/bash`, `POST /v1/text-editor`), gated by a shared bearer token
(`AGENT_RUNNER_TOKEN`). The Claude adapter calls these over the private `agent_net` link
(`AGENT_RUNNER_URL`, defaulting to `http://agent-runner:8000`) instead of executing tool calls
in-process. The same `CODE_RUNNER_PROJECT_DIR` host path is also mounted read-write into
`orchestrator-api` at `/workspace`, independently of that — the deterministic git/PR engine reads
and writes the working tree directly, unrelated to agent tool-call execution.

Default allowlist: `github.com`, `api.github.com`, `codeload.github.com`,
`registry.npmjs.org`, `pypi.org`, `files.pythonhosted.org`. This governs an agent's own bash
commands (`git push`, `npm install`, `pip install`) — the model API call itself is made by
`orchestrator-api` (unrestricted egress), not `agent-runner`, so no model-API domain belongs here.
Per-project additions come from `project.yaml` `egress.allow` at runtime.

```bash
# Verify the lockdown with the stack running (script not yet written — see #269)
bash scripts/verify-egress-lockdown.sh
```

### Data persistence

`orchestrator-api`'s SQLite state store lives on the `orchestrator-api-data` named volume,
mounted at `/data` — it survives `docker compose down` and is only removed with
`docker compose down -v`, the same convention `langfuse-data` uses.

### Tear down

```bash
docker compose down
docker compose down -v  # also remove volumes
```

## Development

See [orchestrator-api/README.md](orchestrator-api/README.md) for backend dev commands.

See [orchestrator-ui/README.md](orchestrator-ui/README.md) for frontend dev commands (`npm run dev`, `npm run test`, `npm run lint`, `npm run typecheck`).

See [agent-runner/README.md](agent-runner/README.md) for the sandboxed tool-execution service's dev commands.
