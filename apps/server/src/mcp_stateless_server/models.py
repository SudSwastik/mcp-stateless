"""Typed domain and tool-result models."""

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
