"""Sequential multi-round-trip elicitation tests for note publication."""

from typing import Any, Literal, cast

import pytest
from mcp import Client
from mcp.client.session import ClientRequestContext, ElicitationFnT
from mcp.server.mcpserver import RequestStateSecurity
from mcp_stateless_server.server import create_server
from mcp_stateless_server.store import NoteStore
from mcp_types import ElicitRequestParams, ElicitResult, ErrorData, InputRequiredResult

ElicitationAction = Literal["accept", "decline", "cancel"]


def _callback(actions: list[tuple[ElicitationAction, dict[str, Any] | None]]) -> ElicitationFnT:
    remaining = iter(actions)

    async def respond(
        _context: ClientRequestContext,
        _params: ElicitRequestParams,
    ) -> ElicitResult | ErrorData:
        action, content = next(remaining)
        return ElicitResult(action=action, content=content)

    return cast(ElicitationFnT, respond)


@pytest.mark.anyio
async def test_publish_note_elicits_audience_then_confirmation_across_servers() -> None:
    store = NoteStore()
    security = RequestStateSecurity(keys=[b"p" * 32])
    servers = [
        create_server(store, request_state_security=security)
        for _ in range(3)
    ]
    async with Client(
        servers[0], mode="2026-07-28", elicitation_callback=_callback([])
    ) as client:
        first = await client.session.call_tool(
            "publish_note", {"note_id": "2"}, allow_input_required=True
        )
    assert isinstance(first, InputRequiredResult)
    assert first.request_state is not None
    assert first.input_requests is not None
    audience_key = next(iter(first.input_requests))
    assert "resolve_publish_audience" in audience_key

    async with Client(
        servers[1], mode="2026-07-28", elicitation_callback=_callback([])
    ) as client:
        second = await client.session.call_tool(
            "publish_note",
            {"note_id": "2"},
            request_state=first.request_state,
            input_responses={
                audience_key: ElicitResult(action="accept", content={"audience": "public"})
            },
            allow_input_required=True,
        )
    assert isinstance(second, InputRequiredResult)
    assert second.request_state is not None
    assert second.input_requests is not None
    confirmation_key = next(iter(second.input_requests))
    assert "resolve_publish_confirmation" in confirmation_key

    async with Client(
        servers[2], mode="2026-07-28", elicitation_callback=_callback([])
    ) as client:
        completed = await client.session.call_tool(
            "publish_note",
            {"note_id": "2"},
            request_state=second.request_state,
            input_responses={
                audience_key: ElicitResult(action="accept", content={"audience": "public"}),
                confirmation_key: ElicitResult(action="accept", content={"confirm": True}),
            },
            allow_input_required=True,
        )
        replay = await client.session.call_tool(
            "publish_note",
            {"note_id": "2"},
            request_state=second.request_state,
            input_responses={
                audience_key: ElicitResult(action="accept", content={"audience": "public"}),
                confirmation_key: ElicitResult(action="accept", content={"confirm": True}),
            },
            allow_input_required=True,
        )

    assert not isinstance(completed, InputRequiredResult)
    assert not isinstance(replay, InputRequiredResult)
    assert completed.structured_content == {
        "action": "published",
        "note_id": "2",
        "audience": "public",
    }
    assert replay.structured_content == completed.structured_content
    assert store.publication_for("2") == "public"


@pytest.mark.anyio
async def test_publish_note_stops_without_mutation_when_a_round_is_declined_or_cancelled() -> None:
    for second_action in ("decline", "cancel"):
        store = NoteStore()
        async with Client(
            create_server(store),
            mode="2026-07-28",
            elicitation_callback=_callback(
                [("accept", {"audience": "team"}), (second_action, None)]
            ),
        ) as client:
            result = await client.call_tool("publish_note", {"note_id": "1"})

        assert result.is_error is False
        assert result.structured_content == {
            "action": "declined" if second_action == "decline" else "cancelled",
            "note_id": "1",
            "audience": None,
        }
        assert store.publication_for("1") is None


@pytest.mark.anyio
async def test_publish_note_can_be_declined_before_asking_for_confirmation() -> None:
    store = NoteStore()
    async with Client(
        create_server(store),
        mode="2026-07-28",
        elicitation_callback=_callback([("decline", None)]),
    ) as client:
        result = await client.call_tool("publish_note", {"note_id": "1"})

    assert result.structured_content == {
        "action": "declined",
        "note_id": "1",
        "audience": None,
    }
    assert store.publication_for("1") is None
