"""Resettable in-memory storage for deterministic tests and demos."""

from collections.abc import Iterable
from dataclasses import dataclass
from threading import RLock

from mcp_stateless_server.models import Note
from mcp_stateless_server.pagination import (
    decode_cursor,
    encode_cursor,
    snapshot_fingerprint,
)

INITIAL_NOTES = (
    Note(note_id="1", title="Protocol overview", body="MCP requests use JSON-RPC."),
    Note(note_id="2", title="Stateless core", body="Modern requests carry their own context."),
    Note(note_id="3", title="Elicitation", body="MRTR pauses and resumes a request."),
)


@dataclass(frozen=True, slots=True)
class NoteSearchPage:
    """One stable page of note-search results."""

    notes: tuple[Note, ...]
    total: int
    next_cursor: str | None


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

    def create(self, title: str, body: str) -> Note:
        """Add a note with the next numeric identifier."""
        with self._lock:
            numeric_ids = [int(note_id) for note_id in self._notes if note_id.isdigit()]
            note = Note(
                note_id=str(max(numeric_ids, default=0) + 1),
                title=title,
                body=body,
            )
            self._notes[note.note_id] = note
            return note

    def search(self, query: str, limit: int = 10) -> list[Note]:
        """Search note titles and bodies case-insensitively."""
        return self._matching_notes(query)[:limit]

    def _matching_notes(self, query: str) -> list[Note]:
        """Return the complete stable match set for a normalized query."""
        normalized_query = query.casefold().strip()
        if not normalized_query:
            return self.list_notes()

        return [
            note
            for note in self.list_notes()
            if normalized_query in note.title.casefold() or normalized_query in note.body.casefold()
        ]

    def search_page(
        self,
        query: str,
        limit: int = 10,
        cursor: str | None = None,
    ) -> NoteSearchPage:
        """Return a stateless page bound to the query, limit, and result snapshot."""
        matches = self._matching_notes(query)
        snapshot = snapshot_fingerprint([note.model_dump_json() for note in matches])
        offset = (
            decode_cursor(
                cursor,
                query=query,
                limit=limit,
                snapshot=snapshot,
                total=len(matches),
            )
            if cursor is not None
            else 0
        )
        page = tuple(matches[offset : offset + limit])
        next_offset = offset + len(page)
        next_cursor = (
            encode_cursor(
                query=query,
                limit=limit,
                snapshot=snapshot,
                offset=next_offset,
            )
            if next_offset < len(matches)
            else None
        )
        return NoteSearchPage(notes=page, total=len(matches), next_cursor=next_cursor)
