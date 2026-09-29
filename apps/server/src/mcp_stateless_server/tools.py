"""Core tool registrations."""

from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.subscriptions import SubscriptionBus
from mcp.shared.subscriptions import ResourcesListChanged, ResourceUpdated
from mcp_types import CallToolResult, ResourceLink, TextContent
from pydantic import Field

from mcp_stateless_server.models import AddResult, Note, SearchNotesResult
from mcp_stateless_server.pagination import CursorError
from mcp_stateless_server.store import NoteStore


def register_tools(mcp: MCPServer, store: NoteStore, event_bus: SubscriptionBus) -> None:
    """Register deterministic tools on the supplied server."""

    @mcp.tool()
    def add(a: int, b: int) -> AddResult:
        """Add two integers."""
        return AddResult(result=a + b)

    @mcp.tool()
    async def create_note(title: str, body: str) -> Note:
        """Create a note and notify listeners that note resources changed."""
        note = store.create(title, body)
        await event_bus.publish(ResourcesListChanged())
        for uri in ("notes://all", "notes://stats", f"notes://{note.note_id}"):
            await event_bus.publish(ResourceUpdated(uri=uri))
        return note

    @mcp.tool()
    def search_notes(
        query: str,
        limit: Annotated[int, Field(ge=1, le=100)] = 10,
        cursor: str | None = None,
    ) -> Annotated[CallToolResult, SearchNotesResult]:
        """Search notes by title or body text with stable cursor pagination."""
        try:
            page = store.search_page(query, limit, cursor)
        except CursorError as exc:
            raise ToolError(str(exc)) from exc
        result = SearchNotesResult(
            query=query,
            notes=list(page.notes),
            count=len(page.notes),
            total=page.total,
            next_cursor=page.next_cursor,
        )
        links = [
            ResourceLink(
                type="resource_link",
                uri=f"notes://{note.note_id}",
                name=note.title,
                description=f"Note {note.note_id}",
                mime_type="application/json",
            )
            for note in page.notes
        ]
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=f"Found {page.total} matching notes; returned {len(page.notes)}.",
                ),
                *links,
            ],
            structured_content=result.model_dump(mode="json"),
        )
