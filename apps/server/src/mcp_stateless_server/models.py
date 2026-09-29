"""Typed domain and tool-result models."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Note(BaseModel):
    """A deterministic note exposed by the demo server."""

    model_config = ConfigDict(frozen=True)

    note_id: str = Field(description="Stable note identifier")
    title: str = Field(description="Human-readable note title")
    body: str = Field(description="Note contents")


class AddResult(BaseModel):
    """Structured result returned by the add tool."""

    result: int


class SearchNotesResult(BaseModel):
    """Structured result returned by note search."""

    query: str
    notes: list[Note]
    count: int
    total: int
    next_cursor: str | None = None


class NoteStats(BaseModel):
    """Derived statistics for the note collection."""

    total_notes: int
    total_words: int


class NoteMutationResult(BaseModel):
    """Outcome of an elicited note create or delete operation."""

    action: Literal["created", "deleted", "declined", "cancelled", "not_found"]
    note: Note | None = None


class PublishNoteResult(BaseModel):
    """Outcome of a multi-round note publication workflow."""

    action: Literal["published", "declined", "cancelled", "not_found"]
    note_id: str
    audience: Literal["team", "public"] | None = None
