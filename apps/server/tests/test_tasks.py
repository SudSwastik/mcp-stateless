"""Task lifecycle tests for deterministic note reindexing."""

from pathlib import Path

import pytest
from mcp import Client
from mcp.client import advertise
from mcp.server import MCPServer
from mcp_stateless_server.server import create_server
from mcp_stateless_server.tasks import (
    TASKS_EXTENSION_ID,
    ReindexTaskStore,
    TaskState,
    TaskUpdateParams,
    TaskUpdateRequest,
)
from mcp_types import (
    CancelTaskRequest,
    CancelTaskRequestParams,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    GetTaskRequest,
    GetTaskRequestParams,
)


def _task_client(server: MCPServer) -> Client:
    return Client(
        server,
        mode="2026-07-28",
        extensions=[advertise(TASKS_EXTENSION_ID)],
    )


@pytest.mark.anyio
async def test_reindex_task_progresses_through_input_to_completion() -> None:
    server = create_server()
    async with _task_client(server) as client:
        started = await client.call_tool("reindex_notes", {})
        assert started.structured_content is not None
        task = TaskState.model_validate(started.structured_content["task"])
        task_id = task.task_id
        assert task.status == "working"
        assert task.poll_interval_ms == 250

        waiting = await client.session.send_request(
            GetTaskRequest(params=GetTaskRequestParams(task_id=task_id)), TaskState
        )
        assert waiting.status == "input_required"
        assert waiting.poll_interval_ms is None
        assert waiting.input_requests is not None
        prompt: ElicitRequest = waiting.input_requests[
            "reindex_notes:include_archived"
        ]
        assert isinstance(prompt.params, ElicitRequestFormParams)

        resumed = await client.session.send_request(
            TaskUpdateRequest(
                params=TaskUpdateParams(
                    task_id=task_id,
                    input_responses={
                        "reindex_notes:include_archived": ElicitResult(
                            action="accept", content={"include_archived": True}
                        )
                    },
                )
            ),
            TaskState,
        )
        assert resumed.status == "working"
        assert resumed.poll_interval_ms == 50

        completed = await client.session.send_request(
            GetTaskRequest(params=GetTaskRequestParams(task_id=task_id)), TaskState
        )

    assert completed.status == "completed"
    assert completed.result == {
        "indexed_note_ids": ["1", "2", "3"],
        "include_archived": True,
    }
    assert completed.poll_interval_ms is None


@pytest.mark.anyio
async def test_reindex_task_is_cancelled_idempotently() -> None:
    async with _task_client(create_server()) as client:
        started = await client.call_tool("reindex_notes", {})
        task_id = TaskState.model_validate(started.structured_content["task"]).task_id
        cancelled = await client.session.send_request(
            CancelTaskRequest(params=CancelTaskRequestParams(task_id=task_id)), TaskState
        )
        repeated = await client.session.send_request(
            CancelTaskRequest(params=CancelTaskRequestParams(task_id=task_id)), TaskState
        )

    assert cancelled.status == "cancelled"
    assert repeated.status == "cancelled"


@pytest.mark.anyio
async def test_reindex_task_failure_and_declined_input_are_terminal() -> None:
    async with _task_client(create_server()) as client:
        failed_start = await client.call_tool(
            "reindex_notes", {"simulate_failure": True}
        )
        failed_id = TaskState.model_validate(failed_start.structured_content["task"]).task_id
        prompt = await client.session.send_request(
            GetTaskRequest(params=GetTaskRequestParams(task_id=failed_id)), TaskState
        )
        failed_input = await client.session.send_request(
            TaskUpdateRequest(
                params=TaskUpdateParams(
                    task_id=failed_id,
                    input_responses={
                        "reindex_notes:include_archived": ElicitResult(
                            action="accept", content={"include_archived": False}
                        )
                    },
                )
            ),
            TaskState,
        )
        failed = await client.session.send_request(
            GetTaskRequest(params=GetTaskRequestParams(task_id=failed_id)), TaskState
        )

        declined_start = await client.call_tool("reindex_notes", {})
        declined_id = TaskState.model_validate(declined_start.structured_content["task"]).task_id
        await client.session.send_request(
            GetTaskRequest(params=GetTaskRequestParams(task_id=declined_id)), TaskState
        )
        declined = await client.session.send_request(
            TaskUpdateRequest(
                params=TaskUpdateParams(
                    task_id=declined_id,
                    input_responses={
                        "reindex_notes:include_archived": ElicitResult(action="decline")
                    },
                )
            ),
            TaskState,
        )

    assert prompt.status == "input_required"
    assert failed_input.status == "working"
    assert failed.status == "failed"
    assert declined.status == "failed"


@pytest.mark.anyio
async def test_reindex_falls_back_to_synchronous_result_without_task_capability() -> None:
    async with Client(create_server(), mode="2026-07-28") as client:
        result = await client.call_tool("reindex_notes", {})

    assert result.structured_content == {
        "action": "completed",
        "task": None,
        "indexed_note_ids": ["1", "2", "3"],
    }


def test_task_ids_are_private_and_expire() -> None:
    now = [0.0]
    tasks = ReindexTaskStore(clock=lambda: now[0])
    task = tasks.create("alice", ["1"])

    assert tasks.get(task.task_id, "bob") is None
    assert tasks.get(task.task_id, "alice", advance=False) is not None
    now[0] = 61.0
    assert tasks.get(task.task_id, "alice") is None


@pytest.mark.anyio
async def test_task_handle_can_resume_on_another_server_instance() -> None:
    task_store = ReindexTaskStore()
    first_server = create_server(task_store=task_store)
    second_server = create_server(task_store=task_store)
    async with _task_client(first_server) as client:
        started = await client.call_tool("reindex_notes", {})
        task_id = TaskState.model_validate(started.structured_content["task"]).task_id

    async with _task_client(second_server) as client:
        waiting = await client.session.send_request(
            GetTaskRequest(params=GetTaskRequestParams(task_id=task_id)), TaskState
        )

    assert waiting.status == "input_required"
    assert waiting.input_requests is not None


@pytest.mark.anyio
async def test_task_handle_transitions_are_shared_by_separate_sqlite_stores(
    tmp_path: Path,
) -> None:
    database = tmp_path / "state.sqlite3"
    first_store = ReindexTaskStore(database_path=database)
    second_store = ReindexTaskStore(database_path=database)
    first_server = create_server(task_store=first_store)
    second_server = create_server(task_store=second_store)

    async with _task_client(first_server) as creator:
        started = await creator.call_tool("reindex_notes", {})
        assert started.structured_content is not None
        task_id = TaskState.model_validate(started.structured_content["task"]).task_id

    async with _task_client(second_server) as poller:
        waiting = await poller.session.send_request(
            GetTaskRequest(params=GetTaskRequestParams(task_id=task_id)), TaskState
        )

    assert waiting.status == "input_required"
    assert waiting.input_requests is not None
    assert isinstance(
        waiting.input_requests["reindex_notes:include_archived"].params,
        ElicitRequestFormParams,
    )

    async with _task_client(first_server) as responder:
        resumed = await responder.session.send_request(
            TaskUpdateRequest(
                params=TaskUpdateParams(
                    task_id=task_id,
                    input_responses={
                        "reindex_notes:include_archived": ElicitResult(
                            action="accept", content={"include_archived": True}
                        )
                    },
                )
            ),
            TaskState,
        )
    async with _task_client(second_server) as poller:
        completed = await poller.session.send_request(
            GetTaskRequest(params=GetTaskRequestParams(task_id=task_id)), TaskState
        )

    assert resumed.status == "working"
    assert completed.status == "completed"
    assert completed.result == {
        "indexed_note_ids": ["1", "2", "3"],
        "include_archived": True,
    }


def test_persisted_task_expiry_is_enforced_across_store_instances(tmp_path: Path) -> None:
    now = [0.0]
    database = tmp_path / "tasks.sqlite3"
    creator = ReindexTaskStore(database_path=database, clock=lambda: now[0])
    task = creator.create("alice", ["1"])

    now[0] = 61.0
    reader = ReindexTaskStore(database_path=database, clock=lambda: now[0])
    assert reader.get(task.task_id, "alice") is None
