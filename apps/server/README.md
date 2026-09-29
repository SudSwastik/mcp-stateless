# MCP Stateless Server

Deterministic MCP `2026-07-28` server used by the monorepo's client and compatibility tests.

## Run

From the repository root:

```bash
uv sync
uv run uvicorn mcp_stateless_server.server:app --host 127.0.0.1 --port 8000
```

The Streamable HTTP endpoint is `http://127.0.0.1:8000/mcp`.

## Test

```bash
uv run pytest
uv run ruff check .
uv run mypy apps
```

See the repository [testing guide](../../docs/TESTING.md) for HTTP, Inspector, Docker, and troubleshooting instructions.
