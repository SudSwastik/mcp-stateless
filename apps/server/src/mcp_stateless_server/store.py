"""Resettable in-memory storage for deterministic tests and demos."""

from collections.abc import Iterable
from threading import RLock

from mcp_stateless_server.models import Note

INITIAL_NOTES = (
    Note(note_id="1", title="Protocol overview", body="MCP requests use JSON-RPC."),
    Note(note_id="2", title="Stateless core", body="Modern requests carry their own context."),
    Note(note_id="3", title="Elicitation", body="MRTR pauses and resumes a request."),
)


class NoteStore:
    """Small thread-safe store with deterministic ordering."""

    def __init__(self, notes: Iterable[Note] = INITIAL_NOTES) -> None:
        self._lock = RLock()
        self._initial_notes = tuple(notes)
        self._notes: dict[str, Note] = {}
        self.reset()

    def reset(self) -> None:
        """Restore the initial note set."""
        with self._lock:
            self._notes = {note.note_id: note for note in self._initial_notes}

    def list_notes(self) -> list[Note]:
        """Return notes ordered by their stable identifiers."""
        with self._lock:
            return [self._notes[note_id] for note_id in sorted(self._notes)]

    def get(self, note_id: str) -> Note | None:
        """Return one note when it exists."""
        with self._lock:
            return self._notes.get(note_id)

    def search(self, query: str, limit: int = 10) -> list[Note]:
        """Search note titles and bodies case-insensitively."""
        normalized_query = query.casefold().strip()
        if not normalized_query:
            return self.list_notes()[:limit]

        return [
            note
            for note in self.list_notes()
            if normalized_query in note.title.casefold() or normalized_query in note.body.casefold()
        ][:limit]
