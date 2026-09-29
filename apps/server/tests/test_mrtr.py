"""Modern multi-round-trip elicitation tests for note mutations."""

from typing import Any, Literal, cast

import pytest
from mcp import Client
from mcp.client.session import ClientRequestContext, ElicitationFnT
from mcp.server.mcpserver import RequestStateSecurity
from mcp.shared.exceptions import MCPError
from mcp_stateless_server.server import create_server
from mcp_stateless_server.store import NoteStore
from mcp_types import (
    ElicitRequestParams,
    ElicitResult,
    ErrorData,
    InputRequiredResult,
    InputResponses,
)

ElicitationAction = Literal["accept", "decline", "cancel"]


def _callback(
    action: ElicitationAction,
    content: dict[str, Any] | None = None,
) -> ElicitationFnT:
    async def respond(
        _context: ClientRequestContext,
        _params: ElicitRequestParams,
    ) -> ElicitResult | ErrorData:
        return ElicitResult(action=action, content=content)

    return cast(ElicitationFnT, respond)


@pytest.mark.anyio
async def test_create_note_elicits_missing_title_and_creates_after_accept() -> None:
    store = NoteStore()
    server = create_server(store)
    async with Client(
        server,
        mode="2026-07-28",
        elicitation_callback=_callback("accept", {"title": "Elicited title"}),
    ) as client:
        result = await client.call_tool("create_note", {"body": "Created through MRTR."})

    assert result.is_error is False
    assert result.structured_content == {
        "action": "created",
        "note": {
            "note_id": "4",
            "title": "Elicited title",
            "body": "Created through MRTR.",
        },
    }
    assert store.get("4") is not None


@pytest.mark.anyio
@pytest.mark.parametrize("action", ["decline", "cancel"])
async def test_create_note_decline_or_cancel_does_not_mutate(
    action: ElicitationAction,
) -> None:
    store = NoteStore()
    async with Client(
        create_server(store),
        mode="2026-07-28",
        elicitation_callback=_callback(action),
    ) as client:
        result = await client.call_tool("create_note", {"body": "No mutation."})

    assert result.is_error is False
    assert result.structured_content == {
        "action": "declined" if action == "decline" else "cancelled",
        "note": None,
    }
    assert store.get("4") is None


@pytest.mark.anyio
async def test_delete_note_requires_and_honors_confirmation() -> None:
    store = NoteStore()
    async with Client(
        create_server(store),
        mode="2026-07-28",
        elicitation_callback=_callback("accept", {"confirm": True}),
    ) as client:
        result = await client.call_tool("delete_note", {"note_id": "2"})

    assert result.is_error is False
    assert result.structured_content == {
        "action": "deleted",
        "note": {
            "note_id": "2",
            "title": "Stateless core",
            "body": "Modern requests carry their own context.",
        },
    }
    assert store.get("2") is None


@pytest.mark.anyio
@pytest.mark.parametrize("action", ["decline", "cancel"])
async def test_delete_note_decline_or_cancel_preserves_note(
    action: ElicitationAction,
) -> None:
    store = NoteStore()
    async with Client(
        create_server(store),
        mode="2026-07-28",
        elicitation_callback=_callback(action),
    ) as client:
        result = await client.call_tool("delete_note", {"note_id": "2"})

    assert result.is_error is False
    assert result.structured_content == {
        "action": "declined" if action == "decline" else "cancelled",
        "note": None,
    }
    assert store.get("2") is not None


@pytest.mark.anyio
async def test_request_state_rejects_tampering_and_replay_is_idempotent() -> None:
    store = NoteStore()
    security = RequestStateSecurity(keys=[b"m" * 32])
    first_server = create_server(store, request_state_security=security)
    retry_server = create_server(store, request_state_security=security)
    async with Client(
        first_server,
        mode="2026-07-28",
        elicitation_callback=_callback("accept", {"title": "unused"}),
    ) as client:
        first = await client.session.call_tool(
            "create_note",
            {"body": "Protected operation."},
            allow_input_required=True,
        )
        assert isinstance(first, InputRequiredResult)
        assert first.input_requests is not None
        response_key = next(iter(first.input_requests))
        responses: InputResponses = {
            response_key: ElicitResult(action="accept", content={"title": "Replay-safe"})
        }
        assert first.request_state is not None
        token = first.request_state
        tampered = ("A" if token[0] != "A" else "B") + token[1:]

    async with Client(
        retry_server,
        mode="2026-07-28",
        elicitation_callback=_callback("accept", {"title": "unused"}),
    ) as client:
        with pytest.raises(MCPError) as error:
            await client.session.call_tool(
                "create_note",
                {"body": "Protected operation."},
                input_responses=responses,
                request_state=tampered,
                allow_input_required=True,
            )
        assert error.value.code == -32602

        completed = await client.session.call_tool(
            "create_note",
            {"body": "Protected operation."},
            input_responses=responses,
            request_state=token,
            allow_input_required=True,
        )
        replay = await client.session.call_tool(
            "create_note",
            {"body": "Protected operation."},
            input_responses=responses,
            request_state=token,
            allow_input_required=True,
        )

    assert not isinstance(completed, InputRequiredResult)
    assert not isinstance(replay, InputRequiredResult)
    assert completed.structured_content == replay.structured_content
    assert len(store.list_notes()) == 4
