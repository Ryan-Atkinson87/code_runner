# Deployment Plan — Local Server

Step-by-step plan for standing up Code Runner on a self-hosted server, verified against the
codebase as of 2026-07-08 (all Spec §14 phases 1–7 closed, plus the **Deployment bootstrap**
milestone (#8) that closed the gaps this file originally tracked). Each step below is marked
against what actually happens if you run it today:

- ✅ **Works as-is** — verified by reading the relevant source, not just the docs.
- ⚠️ **Blocked** — will fail as the project stands; a GitHub issue tracks the fix. Do not expect
  this step to succeed until the linked issue is closed.

## Blocking-issue summary

All of the composition/bootstrap/sandboxing gaps this file was drafted against are now closed:
`create_app()` wires real dependencies, `orchestrator-api` has repo/DB volume mounts, canonical
skill/prompt/overlay content exists, and agent tool execution runs inside the sandboxed
`agent-runner` executor rather than in-process. No open blockers remain under
[**Deployment bootstrap** (#8)](https://github.com/Ryan-Atkinson87/code_runner/milestone/8).

Re-run through this file once a server with Docker is available to confirm every step end-to-end
(this revision is based on source review, not a live run — see the readiness checklist at the
bottom).

---

## 1. Prerequisites — ✅

- Docker Engine + Docker Compose v2+ installed on the server.
- Network access from the server to `github.com`, `api.github.com`, `registry.npmjs.org`,
  `pypi.org`, `files.pythonhosted.org` (the default Squid allowlist for `agent-runner`,
  `squid/allowlist.txt`) and to `api.anthropic.com` for `orchestrator-api` itself, which is the
  process that actually calls the model API and has no egress restriction (Spec §7.2).
- This repo cloned onto the server (`git clone` over SSH or HTTPS, your choice of auth).

## 2. GitHub PAT — ✅ (manual step, no code involved)

Create a fine-grained PAT scoped to the target project repo(s) only:

- **Contents:** Read/Write
- **Pull requests:** Read/Write
- **Metadata:** Read

No admin or branch-protection scopes — `app/github/client.py` has no merge capability by design
(enforced by a CI check per the dev diary), so the PAT never needs push access to protected
branches.

## 3. Environment file — ✅

```bash
cp .env.example .env
```

Fill in:

| Var | Required for | Notes |
|---|---|---|
| `GITHUB_PAT` | hand-off/PR creation | from step 2 |
| `ANTHROPIC_API_KEY` | Claude provider adapter | |
| `AGENT_RUNNER_TOKEN` | agent-runner executor auth | shared secret; `orchestrator-api` and `agent-runner` must use the same value |
| `NOTION_TOKEN` | Notion tracker sync | optional for a first test run |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | notifications | optional for a first test run |
| `AUTH_PASSWORD_HASH` | login | generated in step 4 |
| `LANGFUSE_NEXTAUTH_SECRET` / `LANGFUSE_SALT` | Langfuse server | any random string |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | trace emission | created in the Langfuse UI **after** first boot (step 8) |
| `CODE_RUNNER_PROJECT_DIR` | mounting the target project repo | absolute host path, mounted read-write into both `orchestrator-api` and `agent-runner` at `/workspace` |
| `CODE_RUNNER_PROJECT_CONFIG_PATH` / `CODE_RUNNER_DB_PATH` / `CODE_RUNNER_EXECUTION_PROFILE_PATH` | `orchestrator-api` composition root | set all three to boot with real dependencies wired; see `.env.example` for the expected paths under `/workspace` and `/data` |

## 4. Generate the auth password hash — ✅

```bash
cd orchestrator-api
uv run python -c "from argon2 import PasswordHasher; print(PasswordHasher().hash('yourpassword'))"
```

Paste the output into `AUTH_PASSWORD_HASH` in `.env`.

## 5. Bring the stack up — ✅

```bash
docker compose up -d --build
docker compose ps
```

All three Dockerfiles build cleanly:
- `orchestrator-api/Dockerfile` — `uv sync` + `uvicorn app.main:create_app --factory`.
- `orchestrator-ui/Dockerfile` — multi-stage `node:22-alpine` build → `nginx:alpine` serving the
  static bundle. No runtime env vars needed; `VITE_API_BASE_URL` is baked in at build time
  (default `/api` is correct unless you're not routing through Traefik).
- `agent-runner/Dockerfile` — `uv sync` + `uvicorn app.main:create_app --factory`, the internal
  bash/text-editor executor service (#256) that `orchestrator-api` calls over `agent_net`
  (#257, #258).

Traefik's TLS is self-contained — `traefik/traefik.yml` configures a default auto-generated
self-signed cert for `localhost` (`tls.stores.default.defaultGeneratedCert`), so there's no
separate certificate to provision. `curl -k` (accepting the self-signed cert) is all that's
needed.

### 5a. Health check — ✅

```bash
curl -k https://localhost/api/health
```

This is the only supported health check — `orchestrator-api` has no published host port (only
`traefik` publishes host ports, by design, Spec §2), so a "direct" `curl localhost:8000` alternative
was removed from README.md rather than added (#249).

## 6. Prepare `project.yaml` for your target project — ✅

The schema is real and validated (`app/config/schema.py`) — required fields are `project.name`,
`integrations.github.owner`, at least one `repos[]` entry, and a `secrets` map of logical names
to env-var names. Reference fixtures: `orchestrator-api/tests/fixtures/minimal_project.yaml`
(smallest valid example) and `trive_project.yaml` (full example).

Place the file inside your `CODE_RUNNER_PROJECT_DIR` mount (i.e. under `/workspace` once
mounted) and point `CODE_RUNNER_PROJECT_CONFIG_PATH` at it. `create_app()`'s composition root
(`app/bootstrap.py`) loads it at boot — `GET`/`PUT /config` work end-to-end once that's set.

## 7. Generate `execution-profile.yaml` — ✅

Intended flow is `POST /profile/propose` → review → `POST /profile/confirm` (a "tech-lead
session" generates this file — it's not meant to be hand-written, though a hand-written one
would validate against `app/profile/schema.py` if you needed a stopgap). `app/bootstrap.py`
wires `profile_generate_fn` at boot, so `POST /profile/propose` works end-to-end with
`CODE_RUNNER_EXECUTION_PROFILE_PATH` set.

## 8. Log in — ✅

```bash
curl -k -c cookies.txt -X POST https://localhost/api/login \
  -H "Content-Type: application/json" \
  -d '{"password":"yourpassword"}'
```

Single-user auth — password only, no username field. The session cookie in `cookies.txt`
authenticates subsequent requests and the SSE progress stream.

## 9. Start a real run — ✅

`POST /runs/start` boots a real `RunController`, `Store`, and `GitHubClient` from the composition
root (`app/bootstrap.py`) once `CODE_RUNNER_PROJECT_CONFIG_PATH`/`CODE_RUNNER_DB_PATH` are set
(step 3). `orchestrator-api` has direct filesystem access to the project repo via the
`CODE_RUNNER_PROJECT_DIR` mount (step 3), which its deterministic git/PR engine
(`app/git/repo.py`) reads and writes directly — that mount is unrelated to agent tool-call
execution.

Agent-authored bash and text-editor tool calls do **not** run inside `orchestrator-api`. The
Claude adapter (`app/providers/claude.py`) sends them over the private `agent_net` network path
to the `agent-runner` executor (#256–#259), which enforces `pre_tool_use_check` itself and
executes them inside its own network-locked, read-only-root container. This is the sandboxing
boundary Spec §7.1/§7.2 decided on — see `orchestrator-api/tests/test_arch_sandboxed_execution.py`
for the architectural test that locks it in.

Canonical skill/persona-prompt/overlay content exists under `orchestrator-api/canonical/`
(#250), so `compose_and_render` has real content to load for a wave against any
`execution-profile.yaml` declaring the standard persona types.

## 10. Observability (Langfuse) — ✅, independent of the above

`app/observability/langfuse_emitter.py` reads `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY`/`HOST` directly
from the environment at call time. The Langfuse UI itself (`http://<server>:3000` or via its own
container) will come up and let you create API keys once the stack is running; a real run (step
9) is what populates it with traces.

## 11. Egress lockdown verification — ✅

```bash
bash scripts/verify-egress-lockdown.sh
```

Exercises proxy env vars, allowlisted-domain access, non-allowlisted-domain blocking, direct
egress bypass, the filesystem boundary, and confirms other services keep normal internet access
— run it with the Compose stack up.

## 12. Tear down — ✅

```bash
docker compose down       # keep volumes (Langfuse data, orchestrator-api SQLite state)
docker compose down -v    # also remove volumes
```

---

## Readiness checklist (re-check when revisiting)

- [x] Composition root wires real dependencies — API boots functional, not stubbed
- [x] `orchestrator-api` can reach a project repo and persists its DB
- [x] Sandboxed execution boundary restored and locked in (agent tool calls run in `agent-runner`,
      not in-process; architectural test added)
- [x] README matches the actual reachable endpoints
- [x] Canonical skill/prompt/overlay content exists for `compose_and_render` to load
- [x] `scripts/verify-egress-lockdown.sh` exists and covers the documented checks
- [ ] Steps 6, 7, 9 re-verified end-to-end with a real `project.yaml` and a trivial milestone on
      an actual server (this file is based on source review; no Docker host was available to run
      the full stack when it was last updated)
