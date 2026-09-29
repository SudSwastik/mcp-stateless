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

Use `--output json` for a machine-readable result. The corresponding
environment variables are:

```text
MCP_SERVER_URL=http://127.0.0.1:8000/mcp
MCP_PROTOCOL_VERSION=2026-07-28
MCP_REQUEST_TIMEOUT_SECONDS=15
MCP_OUTPUT_FORMAT=text
```

`verify` sends discovery over separate HTTP connections, validates JSON-RPC
correlation and version compatibility, rejects protocol session state, and
checks that a header/body routing mismatch fails with the specified error.
