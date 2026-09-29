# MCP Stateless Server

Deterministic MCP `2026-07-28` server used by the monorepo's client and compatibility tests.

## Run

From the repository root:

```bash
uv sync
uv run uvicorn mcp_stateless_server.server:app --host 127.0.0.1 --port 8000
```

The Streamable HTTP endpoint is `http://127.0.0.1:8000/mcp`.

## OAuth resource-server integration

The module-level development app remains unauthenticated for loopback use. A
remote deployment can opt into the SDK's OAuth bearer middleware by loading
`auth_settings_from_env()` and passing the returned settings together with a
trusted `TokenVerifier` to `create_server(auth=..., token_verifier=...)` before
calling `streamable_http_app()`. Configure `MCP_AUTH_MODE=oauth`,
`MCP_OAUTH_ISSUER_URL`, `MCP_PUBLIC_BASE_URL`, and optionally
`MCP_REQUIRED_SCOPES`. OAuth mode requires HTTPS issuer and resource URLs and
enables token-resource validation.

The deployment supplies the verifier for its identity provider. It must validate
the signature, issuer, expiry, audience/resource, and token scopes; the SDK
enforces expiry, configured scopes, and the returned resource indicator. Do not
use a verifier that skips TLS validation or trusts unverified token claims.

## Primitive examples

`search_notes` uses opaque cursors that are self-contained and bound to the
query, page size, and result snapshot. Pass `next_cursor` back as `cursor` to
retrieve the next page; no server-side protocol session is created.

The server also exposes:

- completion for `summarize_note` note IDs and styles;
- completion for the `notes://{note_id}` resource template;
- the derived JSON resource `notes://stats`;
- `connect_provider` demonstrates URL-mode out-of-band authorization. Its demo
  endpoint receives no credentials or authorization codes through MCP.
- `reindex_notes` falls back to a synchronous result for ordinary clients and
  returns an expiring task handle to clients that advertise the server's task
  extension. Poll and update the task with `tasks/get` and `tasks/update`; no
  task-list endpoint is exposed.

## Test

```bash
uv run pytest
uv run ruff check .
uv run mypy apps
```

See the repository [testing guide](../../docs/TESTING.md) for HTTP, Inspector, Docker, and troubleshooting instructions.
