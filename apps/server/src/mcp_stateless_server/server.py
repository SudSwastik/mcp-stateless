"""Application factory and ASGI entry point."""

from typing import cast

from mcp.server import MCPServer
from mcp.server.caching import CacheHint
from mcp.server.subscriptions import SubscriptionBus
from mcp_types.methods import CACHEABLE_METHODS, CacheableMethod

from mcp_stateless_server.completions import register_completions
from mcp_stateless_server.prompts import register_prompts
from mcp_stateless_server.resources import register_resources
from mcp_stateless_server.store import NoteStore
from mcp_stateless_server.tools import register_tools


def create_server(
    store: NoteStore | None = None,
    *,
    subscriptions: SubscriptionBus | None = None,
) -> MCPServer:
    """Build an isolated MCP server instance."""
    note_store = store or NoteStore()
    server = MCPServer(
        "mcp-stateless-server",
        version="0.1.0",
        cache_hints={
            cast(CacheableMethod, method): CacheHint(ttl_ms=30_000, scope="public")
            for method in CACHEABLE_METHODS
        },
        subscriptions=subscriptions,
    )
    register_tools(server, note_store)
    register_resources(server, note_store)
    register_prompts(server, note_store)
    register_completions(server, note_store)
    return server


mcp = create_server()
app = mcp.streamable_http_app()
