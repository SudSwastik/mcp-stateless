# MCP Stateless Client

Independent black-box client for inspecting and verifying MCP `2026-07-28`
Streamable HTTP servers.

The client communicates exclusively through the public MCP endpoint. It does
not import server application code.

## Inspect a server

```bash
uv run mcp-stateless-client inspect \
  --url http://127.0.0.1:8000/mcp
```

## Verify stateless discovery

```bash
uv run mcp-stateless-client verify \
  --url http://127.0.0.1:8000/mcp
```

## Use core primitives

```bash
uv run mcp-stateless-client call add \
  --arguments '{"a": 2, "b": 3}'

uv run mcp-stateless-client call create_note \
  --arguments '{"body": "Created by MCP."}'

uv run mcp-stateless-client call delete_note \
  --arguments '{"note_id": "2"}' \
  --elicitation-policy accept

uv run mcp-stateless-client call connect_provider \
  --arguments '{"provider": "github"}' \
  --elicitation-policy accept

uv run python -c 'import asyncio; from mcp_stateless_client import ClientConfig, reindex_notes; print(asyncio.run(reindex_notes(ClientConfig())))'

uv run mcp-stateless-client read notes://1

uv run mcp-stateless-client prompt summarize_note \
  --arguments '{"note_id": "1", "style": "brief"}'
```

Use `--output json` for a machine-readable result. The corresponding
environment variables are:

```text
MCP_SERVER_URL=http://127.0.0.1:8000/mcp
MCP_PROTOCOL_VERSION=2026-07-28
MCP_REQUEST_TIMEOUT_SECONDS=15
MCP_OUTPUT_FORMAT=text
MCP_ELICITATION_POLICY=interactive
```

Form elicitation is interactive by default. Set `--elicitation-policy` (or
`MCP_ELICITATION_POLICY`) to `accept`, `decline`, or `cancel` for deterministic
non-interactive runs. `accept` supplies schema-valid example values; for
example, it uses `Elicited title` for a missing note title and confirms
deletion. For URL-mode authorization, interactive mode displays the URL for
user approval; deterministic policies accept, decline, or cancel navigation.

`inspect` traverses all advertised tool, resource, resource-template, and
prompt pages. `verify` adds catalog and schema checks to the raw transport
checks, probes completion twice for deterministic suggestions, and emits a
compatibility report. `call`, `read`, and `prompt` use the pinned modern
protocol directly without a legacy initialization handshake.

The `reindex_notes` Python helper advertises the task extension, answers the
task-time options prompt, and polls using the server's current `pollIntervalMs`.
