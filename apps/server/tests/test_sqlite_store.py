from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from mcp import Client
from mcp.types import TextResourceContents
from mcp_stateless_server.server import create_server
from mcp_stateless_server.sqlite_store import SQLiteNoteStore


def test_separate_store_instances_share_notes_and_idempotency(tmp_path: Path) -> None:
    database = tmp_path / "shared.sqlite3"
    first = SQLiteNoteStore(database)
    second = SQLiteNoteStore(database)

    created, changed = first.create("Shared", "Across replicas", idempotency_key="create-1")
    replayed, replay_changed = second.create(
        "Ignored replay", "Ignored", idempotency_key="create-1"
    )
    assert changed is True
    assert replay_changed is False
    assert replayed == created
    assert second.get(created.note_id) == created

    audience, published = second.publish(
        created.note_id, "public", idempotency_key="publish-1"
    )
    assert (audience, published) == ("public", True)
    assert first.publication_for(created.note_id) == "public"

    deleted, did_delete = second.delete(created.note_id, idempotency_key="delete-1")
    replayed_delete, replay_did_delete = first.delete(
        created.note_id, idempotency_key="delete-1"
    )
    assert deleted == created
    assert did_delete is True
    assert replayed_delete == created
    assert replay_did_delete is False
    assert first.get(created.note_id) is None


def test_parallel_store_instances_allocate_unique_note_ids(tmp_path: Path) -> None:
    database = tmp_path / "shared.sqlite3"
    stores = (SQLiteNoteStore(database), SQLiteNoteStore(database))

    def create(index: int) -> str:
        note, changed = stores[index % 2].create(f"Note {index}", "Body")
        assert changed is True
        return note.note_id

    with ThreadPoolExecutor(max_workers=8) as executor:
        note_ids = list(executor.map(create, range(20)))

    assert len(set(note_ids)) == 20
    assert len(stores[0].list_notes()) == 23


@pytest.mark.anyio
async def test_note_mutation_on_one_server_is_readable_on_another(tmp_path: Path) -> None:
    database = tmp_path / "shared.sqlite3"
    first_server = create_server(store=SQLiteNoteStore(database))
    second_server = create_server(store=SQLiteNoteStore(database))

    async with Client(first_server) as writer:
        created = await writer.call_tool(
            "create_note", {"title": "Replica shared state", "body": "Visible elsewhere."}
        )
    async with Client(second_server) as reader:
        result = await reader.read_resource("notes://4")

    assert created.is_error is False
    assert len(result.contents) == 1
    contents = result.contents[0]
    assert isinstance(contents, TextResourceContents)
    assert "Replica shared state" in contents.text
