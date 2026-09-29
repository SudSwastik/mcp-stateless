# Testing guide

Run all commands from the repository root unless a section says otherwise.

## Prerequisites

- Python 3.12 or newer
- [`uv`](https://docs.astral.sh/uv/)
- Docker Desktop or another Docker-compatible runtime for container tests

## Install the workspace

```bash
uv sync --all-packages
```

The lock file is committed. In CI or when verifying a clean checkout, prevent dependency resolution from changing it:

```bash
uv sync --frozen --all-packages
```

## Run all automated checks

```bash
uv run pytest
uv run ruff check .
uv run mypy apps
```

Expected result:

```text
44 passed
All checks passed!
Success: no issues found
```

The exact execution time may differ.

## Run server tests

```bash
uv run pytest apps/server/tests
```

Run one test module:

```bash
uv run pytest apps/server/tests/test_tools.py
```

Run one test by name:

```bash
uv run pytest apps/server/tests/test_tools.py::test_add_returns_structured_output
```

Use verbose output while diagnosing a failure:

```bash
uv run pytest -vv apps/server/tests
```

The protocol tests use the SDK's in-memory client. They exercise real MCP request handling without opening a port or starting a subprocess.

## Run client tests

```bash
uv run pytest apps/client/tests
```

The client suite starts the server as a separate process on an ephemeral
loopback port. Client tests communicate only through HTTP and never import
server application code.

## Run the compatibility client

Start the server as shown below, then inspect its advertised protocol contract:

```bash
uv run mcp-stateless-client inspect \
  --url http://127.0.0.1:8000/mcp
```

Run the non-mutating raw-wire checks:

```bash
uv run mcp-stateless-client verify \
  --url http://127.0.0.1:8000/mcp
```

For automation, append `--output json`. A successful verification confirms
JSON-RPC request correlation, pinned-version compatibility, server identity,
capability discovery, independent requests without `Mcp-Session-Id`, and
rejection of mismatched routing headers. It also traverses primitive catalogs,
validates tool schemas, and checks that repeated completion requests return
stable suggestions.

Exercise the server primitives through the standalone client:

```bash
uv run mcp-stateless-client call add \
  --arguments '{"a": 2, "b": 3}'
uv run mcp-stateless-client read notes://1
uv run mcp-stateless-client prompt summarize_note \
  --arguments '{"note_id": "1", "style": "brief"}'
```

These commands use the pinned modern version directly; they do not perform a
legacy initialization handshake or import server code.

## Test the live Streamable HTTP server

Start the server:

```bash
uv run uvicorn mcp_stateless_server.server:app \
  --host 127.0.0.1 \
  --port 8000
```

The MCP endpoint is:

```text
http://127.0.0.1:8000/mcp
```

In a second terminal, verify modern stateless discovery:

```bash
curl --fail-with-body --silent --show-error \
  http://127.0.0.1:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2026-07-28' \
  -H 'Mcp-Method: server/discover' \
  --data '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "server/discover",
    "params": {
      "_meta": {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {
          "name": "manual-smoke-test",
          "version": "0.1.0"
        }
      }
    }
  }'
```

Verify that the response:

- has JSON-RPC request ID `1`;
- lists protocol version `2026-07-28`;
- advertises tools, resources, and prompts;
- identifies the server as `mcp-stateless-server`;
- does not return an `Mcp-Session-Id` header.

Stop the server with `Ctrl+C`.

## Test with MCP Inspector

Start the server as shown above, then connect an MCP Inspector-compatible client to:

```text
http://127.0.0.1:8000/mcp
```

Verify these operations:

| Primitive | Operation | Expected result |
| --- | --- | --- |
| Tool | `add` with `a=2`, `b=3` | Structured result `{"result": 5}` |
| Tool | `search_notes` with `query="MRTR"` | Note `3`, titled `Elicitation` |
| Tool pagination | `search_notes` with empty query and `limit=2` | Two notes plus opaque `next_cursor`; retry returns note `3` |
| Resource | Read `notes://all` | Three notes in ID order |
| Resource | Read `notes://stats` | `total_notes=3` and `total_words=16` |
| Resource template | Read `notes://1` | `Protocol overview` note |
| Prompt | `summarize_note`, note `1`, style `brief` | A one-sentence summary instruction |
| Completion | Prompt `note_id` with an empty prefix | Stable suggestions `1`, `2`, and `3` |

## Test the container image

Build the server image from the repository root:

```bash
docker build \
  --file apps/server/Dockerfile \
  --tag mcp-stateless-server:test \
  .
```

Run it on loopback:

```bash
docker run --rm \
  --publish 127.0.0.1:8000:8000 \
  mcp-stateless-server:test
```

Repeat the discovery request from the live-server section.

## Test with Docker Compose

```bash
docker compose --file infra/compose.yaml up --build
```

Run the discovery smoke test against `http://127.0.0.1:8000/mcp`, then stop and remove the Compose resources:

```bash
docker compose --file infra/compose.yaml down
```

## Validate a clean checkout

Before opening a pull request or committing a completed feature:

```bash
uv sync --frozen --all-packages
uv run pytest
uv run ruff check .
uv run mypy apps
docker build --file apps/server/Dockerfile --tag mcp-stateless-server:test .
docker build --file apps/client/Dockerfile --tag mcp-stateless-client:test .
git diff --check
```

Do not commit `.venv`, caches, coverage output, local environment files, or secrets.

## Troubleshooting

### `uv` reports a stale environment

Resynchronize from the committed lock file:

```bash
uv sync --frozen --all-packages
```

### Port 8000 is already in use

Choose another port:

```bash
uv run uvicorn mcp_stateless_server.server:app \
  --host 127.0.0.1 \
  --port 8001
```

Update the smoke-test URL to match.

### The server returns `421 Misdirected Request`

The SDK enables DNS-rebinding protection. Use `127.0.0.1` or `localhost` for local testing. A deployed hostname must be added explicitly to the server transport-security allowlist in a later deployment configuration.

### Docker cannot bind port 8000

Stop the local server first or publish the container on another host port:

```bash
docker run --rm \
  --publish 127.0.0.1:8001:8000 \
  mcp-stateless-server:test
```
