# MCP Stateless Server

Deterministic MCP `2026-07-28` server used by the monorepo's client and compatibility tests.

## Run

From the repository root:

```bash
uv sync
uv run uvicorn mcp_stateless_server.server:app --host 127.0.0.1 --port 8000
```

The Streamable HTTP endpoint is `http://127.0.0.1:8000/mcp`.

## Primitive examples

`search_notes` uses opaque cursors that are self-contained and bound to the
query, page size, and result snapshot. Pass `next_cursor` back as `cursor` to
retrieve the next page; no server-side protocol session is created.

The server also exposes:

- completion for `summarize_note` note IDs and styles;
- completion for the `notes://{note_id}` resource template;
- the derived JSON resource `notes://stats`.
- `connect_provider` demonstrates URL-mode out-of-band authorization. Its demo
  endpoint receives no credentials or authorization codes through MCP.

## Test

```bash
uv run pytest
uv run ruff check .
uv run mypy apps
```

See the repository [testing guide](../../docs/TESTING.md) for HTTP, Inspector, Docker, and troubleshooting instructions.
