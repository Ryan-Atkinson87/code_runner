# orchestrator-api

FastAPI backend for the Code Runner orchestration engine.

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) for environment and dependency management

## Dev commands

All commands run inside the project's virtual environment via `uv run`.

```bash
# Install dependencies (creates .venv on first run)
uv sync --dev

# Lint
uv run ruff check .

# Format (check only)
uv run ruff format --check .

# Format (apply)
uv run ruff format .

# Type-check
uv run pyright

# Tests
uv run pytest
```
