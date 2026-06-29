# Code Runner — API Contract

REST + SSE API served by `orchestrator-api`. All routes except `/health`, `/login`, and `/logout` require an authenticated session cookie (`session_id`).

---

## Auth

### `POST /login`
- **Body:** `{ "password": string }`
- **Response 200:** `{ "status": "ok" }` + `Set-Cookie: session_id`
- **Response 401:** invalid password
- **Response 429:** rate-limited

### `POST /logout`
- **Response 200:** `{ "status": "ok" }` + clears cookie

---

## Run control

### `GET /runs/waves`
List available waves from GitHub milestone state.

**Response 200:**
```json
{
  "waves": [
    { "name": "Foundations", "milestone_number": 1, "state": "closed" },
    { "name": "Observability + UI", "milestone_number": 6, "state": "open" }
  ]
}
```

### `GET /runs/status`
Current run status.

**Response 200 (no active run):**
```json
{ "active": false, "run": null }
```

**Response 200 (active run):**
```json
{
  "active": true,
  "run": {
    "run_id": 1,
    "project": "my-project",
    "wave": "Observability + UI",
    "provider": "claude",
    "status": "running"
  }
}
```

`status` is one of: `pending`, `running`, `paused`, `stopped`, `completed`, `failed`.

### `POST /runs/start`
Start a new run.

**Body:**
```json
{
  "wave": "Observability + UI",
  "provider": "claude"
}
```

- `wave` (required, non-empty string): milestone name
- `provider` (optional, default `"claude"`): one of `"claude"`, `"codex"`, `"gemini"`

**Response 201:**
```json
{
  "run_id": 1,
  "project": "my-project",
  "wave": "Observability + UI",
  "provider": "claude",
  "status": "running"
}
```

**Response 409:** a run is already active
**Response 422:** invalid input

### `POST /runs/{run_id}/stop`
Stop a running or paused run.

**Response 200:** `RunResponse` with `status: "stopped"`
**Response 404:** run not found
**Response 409:** run is not in a stoppable state

### `POST /runs/{run_id}/pause`
Pause a running run.

**Response 200:** `RunResponse` with `status: "paused"`
**Response 404:** run not found
**Response 409:** run is not running

### `POST /runs/{run_id}/resume`
Resume a paused run.

**Response 200:** `RunResponse` with `status: "running"`
**Response 404:** run not found
**Response 409:** run is not paused

---

## Live progress (SSE)

### `GET /runs/{run_id}/progress`

Server-Sent Events stream for a run. Requires auth cookie. Each frame has an `event:` type and a JSON `data:` payload. A `: keepalive` comment is emitted every 15 s while the stream is open. The stream closes after a `run_ended` event.

Clients should reconnect on connection drop using the standard `EventSource` retry mechanism. On reconnect the `run_state` snapshot is re-sent automatically.

**Event types:**

#### `run_state`
Emitted immediately on subscribe (snapshot) and whenever run status changes.
```json
{
  "run_id": 1,
  "wave": "Observability + UI",
  "project": "my-project",
  "provider": "claude",
  "status": "running"
}
```
`status` is one of: `pending`, `running`, `paused`, `stopped`, `completed`, `failed`.

#### `issue_started`
Emitted when the engine begins work on an issue.
```json
{
  "run_id": 1,
  "issue_number": 47,
  "role": "implementor"
}
```
`role` is one of: `implementor`, `orchestrator`.

#### `session_event`
Emitted for each normalised event produced during a session. Uses `NormalisedEvent` shape from Spec §3.1 — no provider-specific fields.
```json
{
  "run_id": 1,
  "issue_number": 47,
  "role": "implementor",
  "event": {
    "kind": "tool_call",
    "content": "",
    "tool_name": "Edit",
    "tool_input": "{\"file\": \"main.py\"}",
    "timestamp": 1750000000.0
  }
}
```
`kind` is one of: `reasoning`, `tool_call`, `tool_result`, `output`.

#### `issue_completed`
Emitted when an issue finishes (success or parked).
```json
{
  "run_id": 1,
  "issue_number": 47,
  "outcome": "completed"
}
```
`outcome` is one of: `completed`, `blocked`, `error`.

#### `run_ended`
Emitted when the run finishes. Stream closes after this frame.
```json
{}
```

**Response 401:** missing or invalid session cookie
**Response 200:** `text/event-stream` (connection held open)

---

## Usage gauges

### `GET /usage/gauges`
Current usage meter snapshot for the active provider.

**Response 200:**
```json
{
  "meters": [
    {
      "kind": "token_daily",
      "utilisation": 0.62,
      "resets_at": 1750060800.0,
      "limit": 1000000,
      "used": 620000,
      "is_governing": true
    }
  ],
  "threshold_percent": 80,
  "threshold_reached": false,
  "override_active": false,
  "provider": "claude",
  "plan": "pro"
}
```

`kind` values depend on the provider plan (e.g. `token_daily`, `token_monthly`, `request_per_minute`). `is_governing` is `true` on the most-restrictive meter. `resets_at`, `limit`, and `used` are `null` when not applicable for a meter type.

**Response 401:** missing or invalid session cookie

### `POST /usage/override`
Enable or disable the human override (bypasses the 80% threshold gate).

**Body:**
```json
{ "active": true }
```

**Response 200:**
```json
{ "override_active": true }
```

**Response 401:** missing or invalid session cookie

---

## Blockers

### `GET /blockers`
List parked blockers for the active run.

**Response 200:**
```json
{
  "blockers": [
    {
      "id": 1,
      "run_id": 7,
      "issue_number": 42,
      "blocker_type": "missing_spec",
      "reason": "Spec §12 does not cover the empty-state for the PRs screen.",
      "needed_to_unblock": "Confirm whether the empty state should show a link to GitHub or just a message.",
      "status": "parked",
      "created_at": "2026-06-29T10:00:00Z",
      "resolved_at": null,
      "resolution_response": null
    }
  ],
  "run_id": 7
}
```

`blocker_type` is one of: `missing_spec`, `contract_conflict`, `unmet_dependency`, `stuck_agent`, `other`.
`status` is one of: `parked`, `resolved`.

**Response 401:** missing or invalid session cookie
**Response 404:** no active run

### `POST /blockers/{issue_number}/resolve`
Resolve a parked blocker for the given issue with a human response. The response is routed into the engine.

**Path params:** `issue_number` — integer

**Body:**
```json
{ "response": "The empty state should show a message and a link to the GitHub milestone." }
```

**Response 200:** `BlockerResponse` (same shape as the objects inside `blockers` above, with `status: "resolved"`)
**Response 401:** missing or invalid session cookie
**Response 404:** no active run or blocker not found for that issue

---

## PRs

### `GET /prs`
List open hand-off PRs for the current repo. Optionally filter by head branch.

**Query params:** `head` (optional string) — filter to PRs from a specific head branch

**Response 200:**
```json
{
  "prs": [
    {
      "number": 42,
      "title": "#12 Add project.yaml loader",
      "body": "## Summary\n...\n- [ ] Review the config schema\n- [x] Tests pass",
      "html_url": "https://github.com/owner/repo/pull/42",
      "head_branch": "issue-12-config-loader",
      "base_branch": "main",
      "state": "open",
      "checklist": [
        { "text": "Review the config schema", "checked": false },
        { "text": "Tests pass", "checked": true }
      ]
    }
  ]
}
```

`checklist` is parsed from `- [ ]` / `- [x]` lines in the PR body.

**Response 401:** missing or invalid session cookie
**Response 502:** GitHub API error

### `GET /prs/{pr_number}`
Get a single PR by number.

**Path params:** `pr_number` — integer

**Response 200:** `HandoffPR` (same shape as the objects inside `prs` above)
**Response 401:** missing or invalid session cookie
**Response 502:** GitHub API error

---

## Config

### `GET /config`
Read the current project configuration. Secrets are shown by reference (env-var names) only — values are never returned.

**Response 200:**
```json
{
  "project_name": "my-project",
  "project_description": "Autonomous coding agent orchestrator",
  "provider": {
    "default": "claude",
    "plan": "pro",
    "models": {
      "planning": "claude-opus-4-8",
      "implementing": "claude-sonnet-4-6",
      "reviewing": "claude-sonnet-4-6"
    }
  },
  "egress": {
    "allow": ["api.anthropic.com", "api.github.com"]
  },
  "notifications": {
    "telegram": true,
    "email": false
  },
  "secrets": {
    "ANTHROPIC_API_KEY": "ANTHROPIC_API_KEY",
    "GITHUB_TOKEN": "GITHUB_TOKEN"
  }
}
```

**Response 401:** missing or invalid session cookie

### `PUT /config/provider`
Update the provider/model mapping. All fields are optional — omit to leave unchanged.

**Body:**
```json
{
  "default": "claude",
  "plan": "pro",
  "models": { "planning": "claude-opus-4-8", "implementing": "claude-sonnet-4-6", "reviewing": "claude-sonnet-4-6" }
}
```

`default` must be one of `"claude"`, `"codex"`, `"gemini"`.

**Response 200:** full `ConfigResponse` (same shape as `GET /config`)
**Response 401:** missing or invalid session cookie
**Response 422:** invalid provider name or model config

### `PUT /config/egress`
Replace the egress allowlist.

**Body:**
```json
{ "allow": ["api.anthropic.com", "api.github.com"] }
```

**Response 200:** full `ConfigResponse`
**Response 401:** missing or invalid session cookie
**Response 422:** validation error

### `PUT /config/notifications`
Toggle notification channels. Omit a field to leave its state unchanged.

**Body:**
```json
{ "telegram": true, "email": false }
```

**Response 200:** full `ConfigResponse`
**Response 401:** missing or invalid session cookie

---

## Profile generation

### `POST /profile/propose`
Trigger the tech-lead profile-generation session. Long-running — the response is returned when the session completes.

**Response 200:**
```json
{
  "outcome": "proposed",
  "raw_yaml": "---\nprovider:\n  default: claude\n  plan: pro\n...",
  "error": ""
}
```

`outcome` is one of: `proposed`, `error`. On `error`, `raw_yaml` is `""` and `error` contains the message.

**Response 401:** missing or invalid session cookie

### `POST /profile/confirm`
Write the pending proposed profile to disk. Must be called after a successful `/profile/propose`.

**Response 200:**
```json
{ "written": true, "path": "execution-profile.yaml" }
```

**Response 401:** missing or invalid session cookie
**Response 409:** no pending proposal (propose must be called first)

### `POST /profile/reject`
Discard the pending proposal. Nothing is written.

**Response 200:**
```json
{ "written": false, "path": "" }
```

**Response 401:** missing or invalid session cookie

---

## Error responses

All error responses use the same JSON body shape regardless of status code:

```json
{ "detail": "human-readable message" }
```

| Status | Condition | Example `detail` |
|--------|-----------|-----------------|
| 401 | No valid session cookie | `"Not authenticated"` |
| 404 | Resource not found (e.g. unknown run ID) | `"Run 42 not found"` |
| 409 | State conflict (e.g. starting while already running) | `"Run 1 is already running; stop it first"` |
| 422 | Request body failed validation | FastAPI validation error (see below) |
| 429 | Rate limit exceeded (login endpoint only) | `"Too many attempts"` |

### 422 Validation error shape

FastAPI returns a structured error for validation failures:

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "wave"],
      "msg": "Field required",
      "input": {}
    }
  ]
}
```

The `detail` field is a list of validation errors; each has `type`, `loc` (path to the failing field), `msg`, and `input`.
