"""Unit tests for deterministic note storage."""

from mcp_stateless_server.store import NoteStore


def test_store_is_seeded_in_stable_order() -> None:
    store = NoteStore()

    assert [note.note_id for note in store.list_notes()] == ["1", "2", "3"]


def test_search_is_case_insensitive() -> None:
    store = NoteStore()

    assert [note.note_id for note in store.search("STATELESS")] == ["2"]


def test_empty_search_respects_limit() -> None:
    store = NoteStore()

    assert [note.note_id for note in store.search("", limit=2)] == ["1", "2"]
