# MCP Stateless

Blueprint for two independent Python applications that demonstrate and verify the stateless Model Context Protocol (MCP) `2026-07-28` release.

## Architecture

```text
Repository 1                                Repository 2
mcp-stateless-client                       mcp-stateless-server

+---------------------------+              +---------------------------+
| Python MCP client         |   HTTP       | Python MCP server         |
|                           |<------------>|                           |
| interactive CLI           | POST /mcp    | tools                     |
| compatibility tests       |              | resources                 |
| wire-level checks         |              | prompts and elicitation   |
+---------------------------+              +---------------------------+
```

The repositories communicate only through MCP over Streamable HTTP. They do not share source code, models, fixtures, dependencies, or release pipelines.

## Applications

### `mcp-stateless-client`

An interactive CLI and black-box compatibility suite for testing local, containerized, or remotely deployed MCP servers.

### `mcp-stateless-server`

A deterministic MCP server for exercising core primitives, stateless requests, elicitation, and modern protocol extensions.

## Documentation

See the [implementation plan](docs/IMPLEMENTATION_PLAN.md) for scope, repository layouts, delivery phases, testing, security requirements, and acceptance criteria.

## Status

This repository contains the shared architecture and planning documentation. The client and server will be implemented and released as separate repositories.

## References

- [MCP `2026-07-28` specification](https://modelcontextprotocol.io/specification/2026-07-28)
- [Official Python SDK](https://github.com/modelcontextprotocol/python-sdk)
