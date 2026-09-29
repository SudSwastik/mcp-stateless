"""Application factory and ASGI entry point."""

from mcp.server import MCPServer

from mcp_stateless_server.completions import register_completions
from mcp_stateless_server.prompts import register_prompts
from mcp_stateless_server.resources import register_resources
from mcp_stateless_server.store import NoteStore
from mcp_stateless_server.tools import register_tools


def create_server(store: NoteStore | None = None) -> MCPServer:
    """Build an isolated MCP server instance."""
    note_store = store or NoteStore()
    server = MCPServer("mcp-stateless-server", version="0.1.0")
    register_tools(server, note_store)
    register_resources(server, note_store)
    register_prompts(server, note_store)
    register_completions(server, note_store)
    return server


mcp = create_server()
app = mcp.streamable_http_app()
