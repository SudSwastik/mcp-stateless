# MCP Stateless Server

Deterministic MCP `2026-07-28` server used by the monorepo's client and compatibility tests.

## Run

From the repository root:

```bash
uv sync
uv run uvicorn mcp_stateless_server.server:app --host 127.0.0.1 --port 8000
```

The Streamable HTTP endpoint is `http://127.0.0.1:8000/mcp`.

The Compose profile runs two server processes behind a local Nginx gateway,
shares note mutations through a SQLite database on a Docker named volume, and
uses Redis Pub/Sub for subscription invalidations. SQLite sharing is intended
only for a single Docker host and local named volumes; it is not safe to put
the database on a network filesystem. Task state remains process-local, so an
in-flight task is not guaranteed to survive a request routed to another
replica. Use a shared transactional database before deploying tasks across
multiple hosts.

## OAuth resource-server integration

The module-level development app remains unauthenticated for loopback use. A
remote deployment can opt into the SDK's OAuth bearer middleware by loading
`MCP_AUTH_MODE=oauth`, `MCP_OAUTH_ISSUER_URL`, `MCP_PUBLIC_BASE_URL`,
`MCP_OAUTH_JWKS_URL`, and optionally `MCP_REQUIRED_SCOPES` before starting the
module-level ASGI app. OAuth mode requires HTTPS issuer, resource, and JWKS URLs
and enables token-resource validation. The app fails to start if OAuth
configuration is incomplete; default `MCP_AUTH_MODE=none` retains the local
loopback behavior.

For multi-process deployments, set `MCP_SUBSCRIPTION_REDIS_URL` to a shared
Redis URL on every replica. The module-level ASGI app then uses Redis Pub/Sub
to fan resource and catalog change events across processes and closes the
Redis client on shutdown. Redis Pub/Sub is best-effort; notifications are
invalidation hints, so clients should refetch current data after receiving one.
`create_server(subscriptions=...)` remains the injection point for another
implementation of the SDK's `SubscriptionBus` protocol.

The bundled verifier accepts signed JWT access tokens and validates the
signature against the configured JWKS, exact issuer, resource audience,
expiration, and configured scopes. Opaque-token introspection is not included;
deployments using opaque access tokens should instead provide their own trusted
`TokenVerifier` to `create_server`. Do not disable TLS verification or trust
unverified token claims.

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
