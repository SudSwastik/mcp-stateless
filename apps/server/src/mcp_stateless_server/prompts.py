"""Core prompt registrations."""

from typing import Literal

from mcp.server import MCPServer
from mcp_types import EmbeddedResource, TextResourceContents

from mcp_stateless_server.store import NoteStore


def register_prompts(mcp: MCPServer, store: NoteStore) -> None:
    """Register deterministic prompts on the supplied server."""

    @mcp.prompt()
    def summarize_note(
        note_id: str,
        style: Literal["brief", "detailed"] = "brief",
    ) -> list[str | EmbeddedResource]:
        """Create instructions for summarizing a note."""
        note = store.get(note_id)
        if note is None:
            raise ValueError(f"Unknown note: {note_id}")

        detail = "one sentence" if style == "brief" else "a detailed paragraph"
        return [
            f"Summarize the embedded note {note.title!r} in {detail}.",
            EmbeddedResource(
                type="resource",
                resource=TextResourceContents(
                    uri=f"notes://{note.note_id}",
                    mime_type="application/json",
                    text=note.model_dump_json(),
                ),
            ),
        ]
