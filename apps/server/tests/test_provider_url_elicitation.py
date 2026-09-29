"""URL-mode authorization elicitation tests."""

from typing import Literal, cast

import pytest
from mcp import Client
from mcp.client.session import ClientRequestContext, ElicitationFnT
from mcp.server.mcpserver import RequestStateSecurity
from mcp_stateless_server.server import create_server
from mcp_stateless_server.store import NoteStore
from mcp_types import (
    ElicitRequestParams,
    ElicitRequestURLParams,
    ElicitResult,
    ErrorData,
    InputRequiredResult,
)

Action = Literal["accept", "decline", "cancel"]


def _callback(
    action: Action,
    seen: list[ElicitRequestURLParams],
) -> ElicitationFnT:
    async def respond(
        _context: ClientRequestContext,
        params: ElicitRequestParams,
    ) -> ElicitResult | ErrorData:
        assert isinstance(params, ElicitRequestURLParams)
        seen.append(params)
        return ElicitResult(action=action)

    return cast(ElicitationFnT, respond)


@pytest.mark.anyio
async def test_connect_provider_uses_url_mode_without_returning_credentials() -> None:
    store = NoteStore()
    seen: list[ElicitRequestURLParams] = []
    async with Client(
        create_server(store),
        mode="2026-07-28",
        elicitation_callback=_callback("accept", seen),
    ) as client:
        result = await client.call_tool("connect_provider", {"provider": "github"})

    assert result.is_error is False
    assert result.structured_content == {"action": "connected", "provider": "github"}
    assert store.is_provider_connected("github")
    assert len(seen) == 1
    assert seen[0].mode == "url"
    assert seen[0].url == "https://auth.example.test/github/authorize"
    assert "code=" not in seen[0].url
    assert "token=" not in seen[0].url
    assert "secret" not in str(result.structured_content).casefold()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("action", "expected"), [("decline", "declined"), ("cancel", "cancelled")]
)
async def test_connect_provider_decline_or_cancel_does_not_connect(
    action: Action,
    expected: str,
) -> None:
    store = NoteStore()
    async with Client(
        create_server(store),
        mode="2026-07-28",
        elicitation_callback=_callback(action, []),
    ) as client:
        result = await client.call_tool("connect_provider", {"provider": "google"})

    assert result.is_error is False
    assert result.structured_content == {"action": expected, "provider": "google"}
    assert not store.is_provider_connected("google")


@pytest.mark.anyio
async def test_connect_provider_request_resumes_on_another_server_without_credentials() -> None:
    store = NoteStore()
    security = RequestStateSecurity(keys=[b"u" * 32])
    first_server = create_server(store, request_state_security=security)
    retry_server = create_server(store, request_state_security=security)
    seen: list[ElicitRequestURLParams] = []

    async with Client(
        first_server,
        mode="2026-07-28",
        elicitation_callback=_callback("accept", seen),
    ) as client:
        pending = await client.session.call_tool(
            "connect_provider", {"provider": "google"}, allow_input_required=True
        )
    assert isinstance(pending, InputRequiredResult)
    assert pending.input_requests is not None
    assert pending.request_state is not None
    response_key, authorization_request = next(iter(pending.input_requests.items()))
    assert isinstance(authorization_request.params, ElicitRequestURLParams)

    async with Client(
        retry_server,
        mode="2026-07-28",
        elicitation_callback=_callback("accept", seen),
    ) as client:
        completed = await client.session.call_tool(
            "connect_provider",
            {"provider": "google"},
            request_state=pending.request_state,
            input_responses={response_key: ElicitResult(action="accept")},
            allow_input_required=True,
        )

    assert not isinstance(completed, InputRequiredResult)
    assert completed.structured_content == {"action": "connected", "provider": "google"}
    assert store.is_provider_connected("google")
    assert seen == []
