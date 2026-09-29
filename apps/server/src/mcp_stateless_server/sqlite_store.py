"""SQLite-backed shared note state for single-host multi-process deployments."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from mcp_stateless_server.models import Note
from mcp_stateless_server.store import INITIAL_NOTES, NoteStore


class SQLiteNoteStore(NoteStore):
    """Persist note state across server processes sharing a local SQLite file.

    SQLite's transactional write lock protects ID allocation and idempotency
    records across replicas. Use a local Docker named volume; SQLite databases
    are not suitable for shared network filesystems or multi-host deployments.
    """

    def __init__(self, path: str | Path, notes: Iterable[Note] = INITIAL_NOTES) -> None:
        self._path = str(path)
        if self._path == ":memory:":
            raise ValueError("SQLiteNoteStore requires a persistent database path")
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._initial_notes = tuple(notes)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
        with self._connection(write=True) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    note_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS created_operations (
                    operation_key TEXT PRIMARY KEY,
                    note_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS deleted_operations (
                    operation_key TEXT PRIMARY KEY,
                    note_json TEXT
                );
                CREATE TABLE IF NOT EXISTS publications (
                    note_id TEXT PRIMARY KEY,
                    audience TEXT NOT NULL CHECK (audience IN ('team', 'public'))
                );
                CREATE TABLE IF NOT EXISTS published_operations (
                    operation_key TEXT PRIMARY KEY,
                    note_id TEXT NOT NULL,
                    audience TEXT NOT NULL CHECK (audience IN ('team', 'public'))
                );
                CREATE TABLE IF NOT EXISTS connected_providers (
                    provider TEXT PRIMARY KEY
                );
                """
            )
            connection.executemany(
                "INSERT OR IGNORE INTO notes(note_id, title, body) VALUES (?, ?, ?)",
                [(note.note_id, note.title, note.body) for note in self._initial_notes],
            )

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            if write:
                connection.commit()
        except Exception:
            if write:
                connection.rollback()
            raise
        finally:
            connection.close()

    def reset(self) -> None:
        """Restore the initial records and clear demo operation state."""
        with self._connection(write=True) as connection:
            for table in (
                "notes",
                "created_operations",
                "deleted_operations",
                "publications",
                "published_operations",
                "connected_providers",
            ):
                connection.execute(f"DELETE FROM {table}")
            connection.executemany(
                "INSERT INTO notes(note_id, title, body) VALUES (?, ?, ?)",
                [(note.note_id, note.title, note.body) for note in self._initial_notes],
            )

    def list_notes(self) -> list[Note]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT note_id, title, body FROM notes ORDER BY note_id"
            ).fetchall()
        return [Note(note_id=row["note_id"], title=row["title"], body=row["body"]) for row in rows]

    def get(self, note_id: str) -> Note | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT note_id, title, body FROM notes WHERE note_id = ?", (note_id,)
            ).fetchone()
        return Note(note_id=row["note_id"], title=row["title"], body=row["body"]) if row else None

    def create(
        self, title: str, body: str, *, idempotency_key: str | None = None
    ) -> tuple[Note, bool]:
        with self._connection(write=True) as connection:
            if idempotency_key is not None:
                row = connection.execute(
                    "SELECT note_json FROM created_operations WHERE operation_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if row is not None:
                    return Note.model_validate_json(row["note_json"]), False
            note_ids = connection.execute("SELECT note_id FROM notes").fetchall()
            numeric_ids = [int(row["note_id"]) for row in note_ids if row["note_id"].isdigit()]
            next_id = max(numeric_ids, default=0) + 1
            note = Note(note_id=str(next_id), title=title, body=body)
            connection.execute(
                "INSERT INTO notes(note_id, title, body) VALUES (?, ?, ?)",
                (note.note_id, note.title, note.body),
            )
            if idempotency_key is not None:
                connection.execute(
                    "INSERT INTO created_operations(operation_key, note_json) VALUES (?, ?)",
                    (idempotency_key, note.model_dump_json()),
                )
        return note, True

    def delete(
        self, note_id: str, *, idempotency_key: str | None = None
    ) -> tuple[Note | None, bool]:
        with self._connection(write=True) as connection:
            if idempotency_key is not None:
                operation = connection.execute(
                    "SELECT note_json FROM deleted_operations WHERE operation_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if operation is not None:
                    cached = (
                        Note.model_validate_json(operation["note_json"])
                        if operation["note_json"] is not None
                        else None
                    )
                    return cached, False
            row = connection.execute(
                "SELECT note_id, title, body FROM notes WHERE note_id = ?", (note_id,)
            ).fetchone()
            note = (
                Note(note_id=row["note_id"], title=row["title"], body=row["body"])
                if row
                else None
            )
            if note is not None:
                connection.execute("DELETE FROM notes WHERE note_id = ?", (note_id,))
                connection.execute("DELETE FROM publications WHERE note_id = ?", (note_id,))
            if idempotency_key is not None:
                connection.execute(
                    "INSERT INTO deleted_operations(operation_key, note_json) VALUES (?, ?)",
                    (idempotency_key, note.model_dump_json() if note else None),
                )
        return note, note is not None

    def publish(
        self,
        note_id: str,
        audience: Literal["team", "public"],
        *,
        idempotency_key: str | None = None,
    ) -> tuple[Literal["team", "public"] | None, bool]:
        with self._connection(write=True) as connection:
            if idempotency_key is not None:
                operation = connection.execute(
                    "SELECT audience FROM published_operations WHERE operation_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if operation is not None:
                    return operation["audience"], False
            exists = connection.execute(
                "SELECT 1 FROM notes WHERE note_id = ?", (note_id,)
            ).fetchone()
            if exists is None:
                return None, False
            connection.execute(
                "INSERT INTO publications(note_id, audience) VALUES (?, ?) "
                "ON CONFLICT(note_id) DO UPDATE SET audience = excluded.audience",
                (note_id, audience),
            )
            if idempotency_key is not None:
                connection.execute(
                    "INSERT INTO published_operations(operation_key, note_id, audience) "
                    "VALUES (?, ?, ?)",
                    (idempotency_key, note_id, audience),
                )
        return audience, True

    def publication_for(self, note_id: str) -> Literal["team", "public"] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT audience FROM publications WHERE note_id = ?", (note_id,)
            ).fetchone()
        return row["audience"] if row else None

    def connect_provider(self, provider: Literal["github", "google"]) -> None:
        with self._connection(write=True) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO connected_providers(provider) VALUES (?)", (provider,)
            )

    def is_provider_connected(self, provider: Literal["github", "google"]) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM connected_providers WHERE provider = ?", (provider,)
            ).fetchone()
        return row is not None
