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
