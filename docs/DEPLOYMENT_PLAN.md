# Deployment Plan — Local Server

Step-by-step plan for standing up Code Runner on a self-hosted server, verified against the
codebase as of 2026-07-04 (all Spec §14 phases 1–7 closed, `main` at `e906d5a`). Each step below
is marked against what actually happens if you run it today:

- ✅ **Works as-is** — verified by reading the relevant source, not just the docs.
- ⚠️ **Blocked** — will fail as the project stands; a GitHub issue tracks the fix. Do not expect
  this step to succeed until the linked issue is closed.

## Blocking-issue summary

All filed under milestone [**Deployment bootstrap** (#8)](https://github.com/Ryan-Atkinson87/code_runner/milestone/8)
— newly discovered gap work, not part of the original Spec §14 phase list.

| Issue | Title | Blocks step(s) |
|---|---|---|
| [#246](https://github.com/Ryan-Atkinson87/code_runner/issues/246) | Wire real dependencies into `create_app()` so the API boots functional, not stubbed | 6, 7, 9 |
| [#247](https://github.com/Ryan-Atkinson87/code_runner/issues/247) | Add docker-compose volume mounts: `orchestrator-api` needs project-repo access + SQLite persistence | 9 |
| [#248](https://github.com/Ryan-Atkinson87/code_runner/issues/248) | Claude adapter executes tool calls in-process, bypassing the `agent-runner` sandbox decided in the Spec | 9 (security posture, not a hard blocker to boot) |
| [#249](https://github.com/Ryan-Atkinson87/code_runner/issues/249) | README's documented direct health check cannot work — port 8000 not published | 5b |

Re-run through this file once those issues close to confirm readiness — that's its purpose.

---

## 1. Prerequisites — ✅

- Docker Engine + Docker Compose v2+ installed on the server.
- Network access from the server to `github.com`, `api.github.com`, `registry.npmjs.org`,
  `pypi.org`, `api.anthropic.com` (the default Squid allowlist, `squid/allowlist.txt`).
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
| `NOTION_TOKEN` | Notion tracker sync | optional for a first test run |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | notifications | optional for a first test run |
| `AUTH_PASSWORD_HASH` | login | generated in step 4 |
| `LANGFUSE_NEXTAUTH_SECRET` / `LANGFUSE_SALT` | Langfuse server | any random string |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | trace emission | created in the Langfuse UI **after** first boot (step 8) |
| `CODE_RUNNER_PROJECT_DIR` | — | today only referenced by the unused `agent-runner` mount (see #247, #248) — setting it has no effect on a real run yet |

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

Both Dockerfiles build cleanly:
- `orchestrator-api/Dockerfile` — `uv sync` + `uvicorn app.main:create_app --factory`.
- `orchestrator-ui/Dockerfile` — multi-stage `node:22-alpine` build → `nginx:alpine` serving the
  static bundle. No runtime env vars needed; `VITE_API_BASE_URL` is baked in at build time
  (default `/api` is correct unless you're not routing through Traefik).

Traefik's TLS is self-contained — `traefik/traefik.yml` configures a default auto-generated
self-signed cert for `localhost` (`tls.stores.default.defaultGeneratedCert`), so there's no
separate certificate to provision. `curl -k` (accepting the self-signed cert) is all that's
needed.

### 5a. Health check via Traefik — ✅

```bash
curl -k https://localhost/api/health
```

### 5b. Health check "direct" — ⚠️ blocked by [#249](https://github.com/Ryan-Atkinson87/code_runner/issues/249)

README.md documents `curl http://localhost:8000/health` as a "direct" alternative. This cannot
work: `orchestrator-api` has no `ports:` mapping in `docker-compose.yml`, so port 8000 isn't
reachable from the host at all. Skip this check until #249 closes (either the doc line is
removed or the port gets published).

## 6. Prepare `project.yaml` for your target project — ⚠️ blocked by [#246](https://github.com/Ryan-Atkinson87/code_runner/issues/246)

The schema is real and validated (`app/config/schema.py`) — required fields are `project.name`,
`integrations.github.owner`, at least one `repos[]` entry, and a `secrets` map of logical names
to env-var names. Reference fixtures: `orchestrator-api/tests/fixtures/minimal_project.yaml`
(smallest valid example) and `trive_project.yaml` (full example).

You can write this file today, but nothing in the running app reads it yet — `Settings`
(`app/settings.py`) has no config-path field, and `config_path`/`project_config` are pure
`create_app()` constructor kwargs that the Dockerfile's entrypoint never supplies. `GET`/`PUT
/config` will 500 with `RuntimeError("ProjectConfig not initialised")` until #246 closes.

## 7. Generate `execution-profile.yaml` — ⚠️ blocked by [#246](https://github.com/Ryan-Atkinson87/code_runner/issues/246)

Intended flow is `POST /profile/propose` → review → `POST /profile/confirm` (a "tech-lead
session" generates this file — it's not meant to be hand-written, though a hand-written one
would validate against `app/profile/schema.py` if you needed a stopgap). `POST /profile/propose`
will 500 with `RuntimeError("Profile generation not initialised")` until #246 closes, since
nothing ever calls `init_profile_deps`.

## 8. Log in — ✅

```bash
curl -k -c cookies.txt -X POST https://localhost/api/login \
  -H "Content-Type: application/json" \
  -d '{"password":"yourpassword"}'
```

Single-user auth — password only, no username field. The session cookie in `cookies.txt`
authenticates subsequent requests and the SSE progress stream.

## 9. Start a real run — ⚠️ blocked by [#246](https://github.com/Ryan-Atkinson87/code_runner/issues/246) and [#247](https://github.com/Ryan-Atkinson87/code_runner/issues/247)

`POST /runs/start` will 500 with `RuntimeError("RunController not initialised")` — nothing
constructs a real `RunController`, `Store`, or `GitHubClient` at boot (#246). Separately, even
once that's fixed, `orchestrator-api` has no volume mount to your project's repo — the Claude
adapter runs its `bash`/text-editor tool calls as `subprocess` calls inside the
`orchestrator-api` container itself (not inside the sandboxed `agent-runner` container), so
`orchestrator-api` needs direct filesystem access to the repo (#247).

Before relying on this for anything beyond a local experiment, also read
[#248](https://github.com/Ryan-Atkinson87/code_runner/issues/248): the Spec decided that model
calls and tool execution happen from the network-locked `agent-runner` container; the shipped
adapter runs them unsandboxed from `orchestrator-api` instead. The egress allowlist and
filesystem lockdown currently protect a container that never executes agent-authored code.

## 10. Observability (Langfuse) — ✅, independent of the above

`app/observability/langfuse_emitter.py` reads `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY`/`HOST` directly
from the environment at call time — this is not wired through `create_app()`'s DI, so it's
unaffected by #246. The Langfuse UI itself (`http://<server>:3000` or via its own container)
will come up and let you create API keys once the stack is running. It just won't have any real
traces to show until #246/#247 are fixed and a real run executes.

## 11. Egress lockdown verification — ✅ (script runs successfully; see caveat)

```bash
bash scripts/verify-egress-lockdown.sh
```

This checks the `agent-runner`/Squid network configuration and will pass on its own terms. Per
#248, treat a passing result as "the sandbox is correctly configured," not as "agent code
execution is sandboxed" — those are currently two different things.

## 12. Tear down — ✅

```bash
docker compose down       # keep volumes (Langfuse data)
docker compose down -v    # also remove volumes
```

---

## Readiness checklist (re-check when revisiting)

- [ ] #246 closed — API boots with real dependencies wired
- [ ] #247 closed — `orchestrator-api` can reach a project repo and persists its DB
- [ ] #248 resolved (design decision made, spec and implementation consistent again)
- [ ] #249 closed — README matches the actual reachable endpoints
- [ ] Steps 6, 7, 9 re-verified end-to-end with a real `project.yaml` and a trivial milestone
