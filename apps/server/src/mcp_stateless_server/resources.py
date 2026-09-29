"""Core resource registrations."""

import json

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError

from mcp_stateless_server.models import NoteStats
from mcp_stateless_server.store import NoteStore


def register_resources(mcp: MCPServer, store: NoteStore) -> None:
    """Register note resources on the supplied server."""

    @mcp.resource(
        "notes://all",
        name="all-notes",
        description="All notes in stable identifier order.",
        mime_type="application/json",
    )
    def all_notes() -> str:
        return json.dumps([note.model_dump() for note in store.list_notes()], sort_keys=True)

    @mcp.resource(
        "notes://stats",
        name="note-stats",
        description="Derived statistics for the note collection.",
        mime_type="application/json",
    )
    def note_stats() -> NoteStats:
        notes = store.list_notes()
        return NoteStats(
            total_notes=len(notes),
            total_words=sum(len(note.body.split()) for note in notes),
        )

    @mcp.resource(
        "notes://{note_id}",
        name="note-by-id",
        description="Read one note by its identifier.",
        mime_type="application/json",
    )
    def note_by_id(note_id: str) -> str:
        note = store.get(note_id)
        if note is None:
            raise ResourceError(f"Unknown note: {note_id}")
        return note.model_dump_json()
