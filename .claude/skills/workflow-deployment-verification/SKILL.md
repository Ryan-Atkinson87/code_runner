---
name: workflow-deployment-verification
description: Verify the local Docker Compose stack is healthy and running the latest main before milestone QA begins. Orchestrator only.
---

Run this skill after every PR for a milestone has merged to `main`, before `workflow-qa` begins. There is no separate production environment yet (Spec §14) — "the deployment" is the local Docker Compose stack running the current `main` branch.

**Do not run this skill mid-milestone, while PRs are still open.** It checks the state of `main` after the milestone's changes have landed.

Many of these checks describe services that don't exist yet in early milestones. Where a service hasn't been built yet, note its absence — that's expected, not a failure. Once a milestone introduces a service, its check becomes mandatory.

## Step 1: Rebuild and start the stack

- Pull the latest `main`
- `docker compose build` for any service with changed code
- `docker compose up -d`
- `docker compose ps` — confirm every defined service reports healthy

## Step 2: Backend (`orchestrator-api`)

- `GET /healthz` (configured port — see `docker-compose.yml`) returns `200 OK`
- If `project.yaml` / `execution-profile.yaml` exist, confirm they loaded without error (check `orchestrator-api` startup logs)
- Confirm the secrets listed in `workflow-env-verification` Step 3 are present in the running container's environment — confirm presence only, never print values

## Step 3: Frontend (`orchestrator-ui`)

- Loads at its configured local URL without console errors
- The configured API base URL points at `orchestrator-api`, not a mock
- If auth is implemented, the login screen renders and an unauthenticated request to a protected endpoint returns the documented `401`/`403`

## Step 4: Egress proxy and agent-runner

- `agent-runner` has no default route to the internet; `HTTP_PROXY`/`HTTPS_PROXY` point at `egress-proxy` (Spec §7.2)
- `egress-proxy` allowlist permits every host this milestone's work needs

## Step 5: Log failures

For each check that fails (for a service that has actually been built):
- Document the exact failure (service, expected, actual)
- Create a GitHub issue with labels `bug` and `critical`, assigned to the current milestone
- Block `workflow-qa` until all critical issues are resolved
