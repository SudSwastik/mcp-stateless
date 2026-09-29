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


def test_search_page_cursor_resumes_without_server_state() -> None:
    store = NoteStore()

    first = store.search_page("", limit=2)
    second = store.search_page("", limit=2, cursor=first.next_cursor)

    assert [note.note_id for note in first.notes] == ["1", "2"]
    assert first.total == 3
    assert [note.note_id for note in second.notes] == ["3"]
    assert second.next_cursor is None
