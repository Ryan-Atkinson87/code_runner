# orchestrator-ui

React + Vite + TypeScript frontend for Code Runner (Spec §12).

## Dev

```bash
npm install
npm run dev        # start dev server on http://localhost:5173
```

## Test / lint / typecheck

```bash
npm run test       # vitest run (once)
npm run test:watch # vitest watch mode
npm run lint       # eslint
npm run typecheck  # tsc --noEmit
```

## Build

```bash
npm run build      # tsc -b && vite build → dist/
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `VITE_API_BASE_URL` | `/api` | Base URL for all API requests |

Set in `.env.local` for local dev:
```
VITE_API_BASE_URL=http://localhost:8000
```

In Docker Compose the Nginx reverse proxy handles `/api` → `orchestrator-api`, so the default `/api` works without overriding.
