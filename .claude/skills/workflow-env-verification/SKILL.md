---
name: workflow-env-verification
description: Verify the local development environment is correctly configured before starting a new milestone or after a change to the Docker Compose stack, project config, or secrets. Use at the start of each new milestone and after any such change. Backend implementor only.
---

Environment mismatches cause subtle, hard-to-diagnose bugs. This check takes a few minutes and is always cheaper than debugging a misconfigured environment mid-implementation.

Many of these checks describe components that don't exist yet in early milestones (Spec §14 Build Phases). Where a component hasn't been built yet, note its absence — that's expected, not a failure. Once a milestone introduces a component, its check becomes mandatory.

## Step 1: Local state store

If a state store has been built:
- Confirm the SQLite database file exists at its configured path and is writable
- Run `<MIGRATION_STATUS_CMD>` (define once a migration tool is chosen) and confirm all migrations are applied
- Confirm the schema matches what Spec §18.3 describes: per-issue state markers, blocker records, usage history, efficiency rollups

## Step 2: Project configuration

If `project.yaml` exists:
- Confirm it loads and validates against the Pydantic schema (Spec §16) without error
- Confirm `repos`, `integrations.github`, and `secrets` entries match this repo's actual layout

If `execution-profile.yaml` exists (Spec §17.5):
- Confirm it loads and references personas that exist in the canonical skill set

## Step 3: Required secrets

Confirm the following are set in the local environment (`.env`, gitignored — never committed):

| Variable | Required for |
|---|---|
| `GITHUB_PAT` | git/PR engine (Spec §10) |
| `ANTHROPIC_API_KEY` (or Claude subscription OAuth credentials in `~/.claude/.credentials.json`) | AI provider |
| `NOTION_TOKEN` | Tracker sync — Social Media Context updates |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Notifications (required once notification service is built) |
| `RESEND_API_KEY` | Optional email notifications (only if enabled) |

Variables not yet required at this stage of the build can be absent — note their absence so they aren't forgotten when the relevant milestone starts.

## Step 4: Docker Compose stack

If `docker-compose.yml` exists:
- `docker compose config` validates without error
- Services match Spec §2: `traefik`, `orchestrator-ui`, `orchestrator-api`, `langfuse`, `langfuse-db`, `agent-runner`, `egress-proxy`
- `agent-runner` has no default route to the internet; `HTTP_PROXY`/`HTTPS_PROXY` point at `egress-proxy`; an iptables DROP rule blocks direct egress on the external interface (Spec §7.2)
- `egress-proxy` (Squid) allowlist includes at minimum: `github.com`, `api.github.com`, `codeload.github.com`, `api.anthropic.com`, plus any registries this repo's package manager(s) need

## Step 5: Healthcheck

If `orchestrator-api` exists and is running locally, hit `GET /healthz` and confirm `200 OK`. If it fails, resolve before proceeding — the application is not running correctly.

## Step 6: Log failures

For each check that fails (for a component that has actually been built), post a comment on the current milestone's active issue (or create a blocker issue if no issue is active):

```
## Environment issue

**Check:** [which step failed]
**Expected:** [what should be true]
**Actual:** [what was found]
**Action needed:** [what needs to be done to fix it, and by whom]
```

Apply `workflow-blocker-escalation` if the failure cannot be resolved within the implementor's own scope.
