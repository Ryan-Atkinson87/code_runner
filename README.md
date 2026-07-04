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

Default allowlist: `github.com`, `api.github.com`, `codeload.github.com`,
`registry.npmjs.org`, `pypi.org`, `files.pythonhosted.org`, `api.anthropic.com`.
Per-project additions come from `project.yaml` `egress.allow` at runtime.

```bash
# Verify the lockdown with the stack running
bash scripts/verify-egress-lockdown.sh
```

### Tear down

```bash
docker compose down
docker compose down -v  # also remove volumes
```

## Development

See [orchestrator-api/README.md](orchestrator-api/README.md) for backend dev commands.

See [orchestrator-ui/README.md](orchestrator-ui/README.md) for frontend dev commands (`npm run dev`, `npm run test`, `npm run lint`, `npm run typecheck`).
