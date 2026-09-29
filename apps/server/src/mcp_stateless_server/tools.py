"""Core tool registrations."""

import hashlib
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver import (
    CancelledElicitation,
    Context,
    DeclinedElicitation,
    Elicit,
    ElicitationResult,
    Resolve,
)
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult, ResourceLink, TextContent
from pydantic import BaseModel, Field

from mcp_stateless_server.models import AddResult, NoteMutationResult, SearchNotesResult
from mcp_stateless_server.pagination import CursorError
from mcp_stateless_server.store import NoteStore


class NoteTitle(BaseModel):
    """Validated title requested from the user when omitted."""

    title: str = Field(min_length=1, max_length=120)


class DeleteConfirmation(BaseModel):
    """Explicit confirmation for a destructive note deletion."""

    confirm: bool


def register_tools(mcp: MCPServer, store: NoteStore) -> None:
    """Register deterministic tools on the supplied server."""

    @mcp.tool()
    def add(a: int, b: int) -> AddResult:
        """Add two integers."""
        return AddResult(result=a + b)

    def resolve_create_title(
        title: str | None,
    ) -> NoteTitle | Elicit[NoteTitle]:
        if title is not None and title.strip():
            return NoteTitle(title=title.strip())
        return Elicit(message="What title should this note have?", schema=NoteTitle)

    def resolve_delete_confirmation(
        note_id: str,
    ) -> DeleteConfirmation | Elicit[DeleteConfirmation]:
        if store.get(note_id) is None:
            return DeleteConfirmation(confirm=False)
        return Elicit(
            message=f"Delete note {note_id}? This cannot be undone.",
            schema=DeleteConfirmation,
        )

    @mcp.tool()
    async def create_note(
        body: str,
        ctx: Context,
        resolved_title: Annotated[ElicitationResult[NoteTitle], Resolve(resolve_create_title)],
        title: str | None = None,
    ) -> NoteMutationResult:
        """Create a note, asking for a missing title through MRTR."""
        if isinstance(resolved_title, DeclinedElicitation):
            return NoteMutationResult(action="declined")
        if isinstance(resolved_title, CancelledElicitation):
            return NoteMutationResult(action="cancelled")

        idempotency_key = _request_state_key(ctx.request_state)
        note, changed = store.create(
            resolved_title.data.title,
            body,
            idempotency_key=idempotency_key,
        )
        if changed:
            await _notify_note_change(ctx, note.note_id)
        return NoteMutationResult(action="created", note=note)

    @mcp.tool()
    async def delete_note(
        note_id: str,
        ctx: Context,
        confirmation: Annotated[
            ElicitationResult[DeleteConfirmation], Resolve(resolve_delete_confirmation)
        ],
    ) -> NoteMutationResult:
        """Delete a note only after explicit MRTR confirmation."""
        if store.get(note_id) is None:
            return NoteMutationResult(action="not_found")
        if isinstance(confirmation, DeclinedElicitation):
            return NoteMutationResult(action="declined")
        if isinstance(confirmation, CancelledElicitation):
            return NoteMutationResult(action="cancelled")
        if not confirmation.data.confirm:
            return NoteMutationResult(action="declined")

        note, changed = store.delete(
            note_id,
            idempotency_key=_request_state_key(ctx.request_state),
        )
        if note is None:
            return NoteMutationResult(action="not_found")
        if changed:
            await _notify_note_change(ctx, note.note_id)
        return NoteMutationResult(action="deleted", note=note)

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


def _request_state_key(request_state: str | None) -> str | None:
    if request_state is None:
        return None
    return hashlib.sha256(request_state.encode("utf-8")).hexdigest()


async def _notify_note_change(ctx: Context, note_id: str) -> None:
    await ctx.notify_resources_changed()
    for uri in ("notes://all", "notes://stats", f"notes://{note_id}"):
        await ctx.notify_resource_updated(uri)
