"""Client driver for the mcp-stateless task extension."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from mcp import Client
from mcp.client import advertise
from mcp_types import (
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    GetTaskRequest,
    GetTaskRequestParams,
    Implementation,
    Request,
    RequestParams,
    TaskStatus,
)
from pydantic import BaseModel, ConfigDict, Field

from mcp_stateless_client.config import ClientConfig
from mcp_stateless_client.discovery import CLIENT_NAME, CLIENT_VERSION, ProtocolError

TASKS_EXTENSION_ID = "com.mcpstateless/tasks"
TASK_RESPONSE_KEY = "reindex_notes:include_archived"


class TaskState(BaseModel):
    """Task state returned by the task extension methods."""

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


class _TaskUpdateParams(RequestParams):
    task_id: str
    input_responses: dict[str, ElicitResult]


class _TaskUpdateRequest(Request[_TaskUpdateParams, Literal["tasks/update"]]):
    method: Literal["tasks/update"] = "tasks/update"
    params: _TaskUpdateParams


type _Sleep = Callable[[float], Awaitable[None]]


async def reindex_notes(
    config: ClientConfig,
    *,
    include_archived: bool = False,
    sleep: _Sleep = asyncio.sleep,
    max_polls: int = 20,
) -> TaskState:
    """Run the task-aware reindex flow and respect server poll intervals."""
    if max_polls < 1:
        raise ValueError("max_polls must be positive")
    client = Client(
        config.server_url,
        mode=config.protocol_version,
        client_info=Implementation(name=CLIENT_NAME, version=CLIENT_VERSION),
        read_timeout_seconds=config.request_timeout_seconds,
        cache=config.response_cache,
        extensions=[advertise(TASKS_EXTENSION_ID)],
    )
    async with client:
        started = await client.call_tool("reindex_notes", {})
        if started.is_error or started.structured_content is None:
            raise ProtocolError("Server did not return a reindex task handle")
        raw_task = started.structured_content.get("task")
        if not isinstance(raw_task, dict):
            raise ProtocolError("Server did not create a reindex task for this client")
        state = TaskState.model_validate(raw_task)

        for _ in range(max_polls):
            if state.status in {"completed", "failed", "cancelled"}:
                return state
            if state.status == "input_required":
                state = await _answer_task_input(client, state, include_archived)
                continue
            if state.status != "working":
                raise ProtocolError(f"Unsupported task status: {state.status}")
            await sleep(max(state.poll_interval_ms or 0, 0) / 1000)
            state = await client.session.send_request(
                GetTaskRequest(params=GetTaskRequestParams(task_id=state.task_id)), TaskState
            )
        raise ProtocolError(f"Reindex task exceeded the {max_polls}-poll client limit")


async def _answer_task_input(
    client: Client,
    state: TaskState,
    include_archived: bool,
) -> TaskState:
    requests = state.input_requests or {}
    request = requests.get(TASK_RESPONSE_KEY)
    if request is None or not isinstance(request.params, ElicitRequestFormParams):
        raise ProtocolError("Task requested unsupported or missing input")
    params = _TaskUpdateParams(
        task_id=state.task_id,
        input_responses={
            TASK_RESPONSE_KEY: ElicitResult(
                action="accept", content={"include_archived": include_archived}
            )
        },
    )
    request_model = _TaskUpdateRequest(params=params)
    return await client.session.send_request(request_model, TaskState)
