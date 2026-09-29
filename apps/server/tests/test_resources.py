"""Protocol-level tests for core resources."""

import json

import pytest
from mcp import Client
from mcp.server import MCPServer
from mcp.server.subscriptions import InMemorySubscriptionBus
from mcp.shared.subscriptions import PromptsListChanged, ToolsListChanged
from mcp.types import TextResourceContents
from mcp_stateless_server.server import create_server


@pytest.mark.anyio
async def test_lists_static_and_template_resources(server: MCPServer) -> None:
    async with Client(server) as client:
        resources = await client.list_resources()
        templates = await client.list_resource_templates()

    assert [str(resource.uri) for resource in resources.resources] == [
        "notes://all",
        "notes://stats",
    ]
    assert [template.uri_template for template in templates.resource_templates] == [
        "notes://{note_id}"
    ]


@pytest.mark.anyio
async def test_reads_note_resource(server: MCPServer) -> None:
    async with Client(server) as client:
        result = await client.read_resource("notes://1")

    assert len(result.contents) == 1
    contents = result.contents[0]
    assert isinstance(contents, TextResourceContents)
    assert json.loads(contents.text) == {
        "note_id": "1",
        "title": "Protocol overview",
        "body": "MCP requests use JSON-RPC.",
    }


@pytest.mark.anyio
async def test_reads_structured_note_stats(server: MCPServer) -> None:
    async with Client(server) as client:
        result = await client.read_resource("notes://stats")

    contents = result.contents[0]
    assert isinstance(contents, TextResourceContents)
    assert json.loads(contents.text) == {"total_notes": 3, "total_words": 16}


@pytest.mark.anyio
async def test_listen_receives_requested_change_events_only() -> None:
    bus = InMemorySubscriptionBus()
    server = create_server(subscriptions=bus)

    async with Client(server) as client, client.listen(
        tools_list_changed=True
    ) as subscription:
        await bus.publish(PromptsListChanged())
        await bus.publish(ToolsListChanged())
        event = await anext(subscription)

    assert isinstance(event, ToolsListChanged)
