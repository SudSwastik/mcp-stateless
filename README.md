# MCP Stateless

Monorepo for two Python applications that demonstrate and verify the stateless Model Context Protocol (MCP) `2026-07-28` release.

## Architecture

```text
Application 1                              Application 2
apps/client                                apps/server

+---------------------------+              +---------------------------+
| Python MCP client         |   HTTP       | Python MCP server         |
|                           |<------------>|                           |
| interactive CLI           | POST /mcp    | tools                     |
| compatibility tests       |              | resources                 |
| wire-level checks         |              | prompts and elicitation   |
+---------------------------+              +---------------------------+
```

The applications communicate through MCP over Streamable HTTP and remain independently testable inside one repository.

## Applications

### `apps/client` (`mcp-stateless-client`)

An interactive CLI and black-box compatibility suite for testing local, containerized, or remotely deployed MCP servers.

### `apps/server` (`mcp-stateless-server`)

A deterministic MCP server for exercising core primitives, stateless requests, elicitation, and modern protocol extensions.

## Documentation

See the [implementation plan](docs/IMPLEMENTATION_PLAN.md) for scope and delivery phases, and the [testing guide](docs/TESTING.md) for validation commands.

## Quick verification

Start the server in one terminal:

```bash
uv run uvicorn mcp_stateless_server.server:app --host 127.0.0.1 --port 8000
```

Then run the independent client in another terminal:

```bash
uv run mcp-stateless-client verify
```

## References

- [MCP `2026-07-28` specification](https://modelcontextprotocol.io/specification/2026-07-28)
- [Official Python SDK](https://github.com/modelcontextprotocol/python-sdk)
