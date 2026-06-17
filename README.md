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
| `orchestrator-ui` | React UI (placeholder) | https://localhost/ |
| `langfuse` | LLM observability | Internal (port 3000) |
| `langfuse-db` | Postgres for Langfuse | Internal |
| `agent-runner` | AI agent container | Internal (placeholder) |
| `egress-proxy` | Squid allowlist proxy | Internal |

### Verify

```bash
# Check all services are running
docker compose ps

# Health check (via Traefik)
curl -k https://localhost/api/health

# Health check (direct)
curl http://localhost:8000/health
```

### Tear down

```bash
docker compose down
docker compose down -v  # also remove volumes
```

## Development

See [orchestrator-api/README.md](orchestrator-api/README.md) for backend dev commands.
