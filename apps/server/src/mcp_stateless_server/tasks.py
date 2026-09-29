"""Stateless Tasks-style lifecycle for long-running note reindexing."""

from __future__ import annotations

import hmac
import json
import secrets
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Literal

from mcp.server.context import ServerRequestContext
from mcp.server.extension import Extension, MethodBinding
from mcp.server.mcpserver import authenticated_principal, require_client_extension
from mcp.shared.exceptions import MCPError
from mcp_types import (
    CancelTaskRequestParams,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    GetTaskRequestParams,
    InputResponses,
    Request,
    RequestParams,
    TaskStatus,
)
from pydantic import BaseModel, ConfigDict, Field

TASKS_EXTENSION_ID = "com.mcpstateless/tasks"
TASKS_PROTOCOL_VERSIONS = frozenset({"2026-07-28"})
TASK_RESPONSE_KEY = "reindex_notes:include_archived"
TASK_TTL_MS = 60_000
TASK_EARLY_POLL_MS = 250
TASK_LATE_POLL_MS = 50


class TaskUpdateParams(RequestParams):
    """Task-time elicitation answers sent by the client."""

    task_id: str
    input_responses: InputResponses


class TaskUpdateRequest(Request[TaskUpdateParams, Literal["tasks/update"]]):
    """Client request for responding to task-time elicitation."""

    method: Literal["tasks/update"] = "tasks/update"
    params: TaskUpdateParams


class TaskState(BaseModel):
    """Public, explicit task handle and its current state."""

    model_config = ConfigDict(populate_by_name=True)

    task_id: str
    status: TaskStatus
    status_message: str | None = None
    created_at: str
    last_updated_at: str
    ttl_ms: int = Field(alias="ttlMs")
    poll_interval_ms: int | None = Field(default=None, alias="pollIntervalMs")
    input_requests: dict[str, ElicitRequest] | None = Field(default=None, alias="inputRequests")
    result: dict[str, Any] | None = None


class ReindexNotesResult(BaseModel):
    """Reindex outcome, optionally carrying a task handle."""

    action: Literal["completed", "failed", "task_started"]
    task: TaskState | None = None
    indexed_note_ids: list[str] | None = None


@dataclass(slots=True)
class _TaskRecord:
    state: TaskState
    owner: str
    expires_at: float
    note_ids: tuple[str, ...]
    fail: bool
    include_archived: bool | None = None
    input_request: ElicitRequest | None = None


class ReindexTaskStore:
    """Thread-safe, expiring tasks, optionally persisted for shared replicas."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] | None = None,
        database_path: str | Path | None = None,
    ) -> None:
        import time

        self._clock = clock or time.monotonic
        self._lock = RLock()
        self._tasks: dict[str, _TaskRecord] = {}
        self._database_path = str(database_path) if database_path is not None else None
        if self._database_path is not None:
            Path(self._database_path).parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self._database_path, timeout=15) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS reindex_tasks ("
                    "task_id TEXT PRIMARY KEY, record_json TEXT NOT NULL, expires_at REAL NOT NULL)"
                )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        """Serialize task transitions across threads and optional DB-backed replicas."""
        with self._lock:
            if self._database_path is None:
                yield
                return
            connection = sqlite3.connect(self._database_path, timeout=15)
            try:
                connection.execute("BEGIN IMMEDIATE")
                rows = connection.execute(
                    "SELECT task_id, record_json FROM reindex_tasks WHERE expires_at > ?",
                    (self._clock(),),
                ).fetchall()
                self._tasks = {
                    task_id: self._record_from_json(record_json) for task_id, record_json in rows
                }
                yield
                now = self._clock()
                connection.execute("DELETE FROM reindex_tasks WHERE expires_at <= ?", (now,))
                connection.executemany(
                    "INSERT INTO reindex_tasks(task_id, record_json, expires_at) "
                    "VALUES (?, ?, ?) ON CONFLICT(task_id) DO UPDATE SET "
                    "record_json = excluded.record_json, expires_at = excluded.expires_at",
                    [
                        (task_id, self._record_to_json(record), record.expires_at)
                        for task_id, record in self._tasks.items()
                        if record.expires_at > now
                    ],
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    @staticmethod
    def _record_to_json(record: _TaskRecord) -> str:
        return json.dumps(
            {
                "state": json.loads(record.state.model_dump_json(by_alias=True)),
                "owner": record.owner,
                "expires_at": record.expires_at,
                "note_ids": record.note_ids,
                "fail": record.fail,
                "include_archived": record.include_archived,
                "input_request": (
                    json.loads(record.input_request.model_dump_json(by_alias=True))
                    if record.input_request is not None
                    else None
                ),
            },
            separators=(",", ":"),
        )

    @staticmethod
    def _record_from_json(value: str) -> _TaskRecord:
        payload = json.loads(value)
        input_request = payload["input_request"]
        return _TaskRecord(
            state=TaskState.model_validate(payload["state"]),
            owner=payload["owner"],
            expires_at=payload["expires_at"],
            note_ids=tuple(payload["note_ids"]),
            fail=payload["fail"],
            include_archived=payload["include_archived"],
            input_request=ElicitRequest.model_validate(input_request)
            if input_request is not None
            else None,
        )

    def create(
        self,
        owner: str,
        note_ids: Sequence[str],
        *,
        fail: bool = False,
    ) -> TaskState:
        """Create an unguessable task with a bounded lifetime."""
        now = self._timestamp()
        state = TaskState(
            task_id=secrets.token_urlsafe(24),
            status="working",
            status_message="Reindex queued.",
            created_at=now,
            last_updated_at=now,
            ttlMs=TASK_TTL_MS,
            pollIntervalMs=TASK_EARLY_POLL_MS,
        )
        with self._transaction():
            self._tasks[state.task_id] = _TaskRecord(
                state=state,
                owner=owner,
                expires_at=self._clock() + TASK_TTL_MS / 1000,
                note_ids=tuple(note_ids),
                fail=fail,
            )
        return state

    def get(self, task_id: str, owner: str, *, advance: bool = True) -> TaskState | None:
        """Read and deterministically advance one task, hiding unauthorized IDs."""
        with self._transaction():
            record = self._record(task_id, owner)
            if record is None:
                return None
            state = record.state
            if advance and state.status == "working":
                if record.include_archived is None and record.input_request is None:
                    record.input_request = ElicitRequest(
                        params=ElicitRequestFormParams(
                            message="Include archived notes in this reindex?",
                            requested_schema={
                                "type": "object",
                                "properties": {"include_archived": {"type": "boolean"}},
                                "required": ["include_archived"],
                            },
                        )
                    )
                    state = state.model_copy(
                        update={
                            "status": "input_required",
                            "status_message": "Waiting for reindex options.",
                            "last_updated_at": self._timestamp(),
                            "poll_interval_ms": None,
                            "input_requests": {TASK_RESPONSE_KEY: record.input_request},
                        }
                    )
                elif record.include_archived is not None:
                    state = self._finish(record)
                record.state = state
            return state

    def update(self, task_id: str, owner: str, responses: InputResponses) -> TaskState | None:
        """Consume one task-time elicitation response exactly once."""
        with self._transaction():
            record = self._record(task_id, owner)
            if record is None:
                return None
            state = record.state
            if state.status == "input_required":
                response = responses.get(TASK_RESPONSE_KEY)
                if not isinstance(response, ElicitResult):
                    return state
                record.input_request = None
                if response.action == "accept" and response.content is not None:
                    include_archived = response.content.get("include_archived")
                    if not isinstance(include_archived, bool):
                        raise MCPError(code=-32602, message="Invalid task input response")
                    record.include_archived = include_archived
                    state = state.model_copy(
                        update={
                            "status": "working",
                            "status_message": "Reindex options accepted.",
                            "last_updated_at": self._timestamp(),
                            "poll_interval_ms": TASK_LATE_POLL_MS,
                            "input_requests": None,
                        }
                    )
                elif response.action == "cancel":
                    state = state.model_copy(
                        update={
                            "status": "cancelled",
                            "status_message": "Cancelled during task input.",
                            "last_updated_at": self._timestamp(),
                            "input_requests": None,
                        }
                    )
                else:
                    state = state.model_copy(
                        update={
                            "status": "failed",
                            "status_message": "Required reindex options were declined.",
                            "last_updated_at": self._timestamp(),
                            "input_requests": None,
                        }
                    )
                record.state = state
            return state

    def cancel(self, task_id: str, owner: str) -> TaskState | None:
        """Cancel a non-terminal task; terminal outcomes remain idempotent."""
        with self._transaction():
            record = self._record(task_id, owner)
            if record is None:
                return None
            if record.state.status in {"working", "input_required"}:
                record.input_request = None
                record.state = record.state.model_copy(
                    update={
                        "status": "cancelled",
                        "status_message": "Task cancelled by client.",
                        "last_updated_at": self._timestamp(),
                        "poll_interval_ms": None,
                        "input_requests": None,
                    }
                )
            return record.state

    def _finish(self, record: _TaskRecord) -> TaskState:
        if record.fail:
            return record.state.model_copy(
                update={
                    "status": "failed",
                    "status_message": "The deterministic reindex failed.",
                    "last_updated_at": self._timestamp(),
                    "poll_interval_ms": None,
                }
            )
        return record.state.model_copy(
            update={
                "status": "completed",
                "status_message": "Reindex complete.",
                "last_updated_at": self._timestamp(),
                "poll_interval_ms": None,
                "result": {
                    "indexed_note_ids": list(record.note_ids),
                    "include_archived": record.include_archived,
                },
            }
        )

    def _record(self, task_id: str, owner: str) -> _TaskRecord | None:
        record = self._tasks.get(task_id)
        if record is None:
            return None
        if record.expires_at <= self._clock():
            del self._tasks[task_id]
            return None
        if not hmac.compare_digest(record.owner, owner):
            return None
        return record

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def task_owner(ctx: ServerRequestContext[Any, Any]) -> str:
    """Bind every task operation to its authenticated principal when available."""
    return authenticated_principal(ctx) or "anonymous"


def _unknown_task() -> MCPError:
    return MCPError(code=-32602, message="Unknown, expired, or unauthorized task")


class TasksExtension(Extension):
    """Namespaced 2026 task lifecycle; deliberately omits a task-list endpoint."""

    identifier = TASKS_EXTENSION_ID

    def __init__(self, tasks: ReindexTaskStore) -> None:
        self._tasks = tasks

    def settings(self) -> dict[str, Any]:
        return {"methods": ["tasks/get", "tasks/update", "tasks/cancel"]}

    def methods(self) -> Sequence[MethodBinding]:
        return (
            MethodBinding(
                "tasks/get",
                GetTaskRequestParams,
                self._get,
                protocol_versions=TASKS_PROTOCOL_VERSIONS,
            ),
            MethodBinding(
                "tasks/update",
                TaskUpdateParams,
                self._update,
                protocol_versions=TASKS_PROTOCOL_VERSIONS,
            ),
            MethodBinding(
                "tasks/cancel",
                CancelTaskRequestParams,
                self._cancel,
                protocol_versions=TASKS_PROTOCOL_VERSIONS,
            ),
        )

    async def _get(
        self, ctx: ServerRequestContext[Any, Any], params: GetTaskRequestParams
    ) -> TaskState:
        require_client_extension(ctx, self.identifier)
        task = self._tasks.get(params.task_id, task_owner(ctx))
        if task is None:
            raise _unknown_task()
        return task

    async def _update(
        self, ctx: ServerRequestContext[Any, Any], params: TaskUpdateParams
    ) -> TaskState:
        require_client_extension(ctx, self.identifier)
        task = self._tasks.update(params.task_id, task_owner(ctx), params.input_responses)
        if task is None:
            raise _unknown_task()
        return task

    async def _cancel(
        self, ctx: ServerRequestContext[Any, Any], params: CancelTaskRequestParams
    ) -> TaskState:
        require_client_extension(ctx, self.identifier)
        task = self._tasks.cancel(params.task_id, task_owner(ctx))
        if task is None:
            raise _unknown_task()
        return task
