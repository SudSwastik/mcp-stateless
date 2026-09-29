"""Core tool registrations."""

from typing import Annotated

from mcp.server import MCPServer
from pydantic import Field

from mcp_stateless_server.models import AddResult, SearchNotesResult
from mcp_stateless_server.store import NoteStore


def register_tools(mcp: MCPServer, store: NoteStore) -> None:
    """Register deterministic tools on the supplied server."""

    @mcp.tool()
    def add(a: int, b: int) -> AddResult:
        """Add two integers."""
        return AddResult(result=a + b)

    @mcp.tool()
    def search_notes(
        query: str,
        limit: Annotated[int, Field(ge=1, le=100)] = 10,
    ) -> SearchNotesResult:
        """Search notes by title or body text."""
        notes = store.search(query, limit)
        return SearchNotesResult(query=query, notes=notes, count=len(notes))
