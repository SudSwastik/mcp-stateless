"""Protocol-level tests for core tools."""

import pytest
from mcp import Client
from mcp.server import MCPServer
from mcp_types import ResourceLink, TextContent


@pytest.mark.anyio
async def test_lists_core_tools(server: MCPServer) -> None:
    async with Client(server) as client:
        result = await client.list_tools()

    assert [tool.name for tool in result.tools] == [
        "add",
        "create_note",
        "delete_note",
        "publish_note",
        "connect_provider",
        "search_notes",
        "reindex_notes",
        "note_dashboard",
    ]
    assert result.ttl_ms == 30_000
    assert result.cache_scope == "public"


@pytest.mark.anyio
async def test_create_note_returns_new_note(server: MCPServer) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "create_note", {"title": "Subscriptions", "body": "Changes are observable."}
        )

    assert result.is_error is False
    assert result.structured_content == {
        "action": "created",
        "note": {
            "note_id": "4",
            "title": "Subscriptions",
            "body": "Changes are observable.",
        },
    }


@pytest.mark.anyio
async def test_add_returns_structured_output(server: MCPServer) -> None:
    async with Client(server) as client:
        result = await client.call_tool("add", {"a": 2, "b": 3})

    assert result.is_error is False
    assert result.structured_content == {"result": 5}


@pytest.mark.anyio
async def test_search_notes_returns_matching_notes(server: MCPServer) -> None:
    async with Client(server) as client:
        result = await client.call_tool("search_notes", {"query": "MRTR", "limit": 5})

    assert result.is_error is False
    assert result.structured_content == {
        "query": "MRTR",
        "notes": [
            {
                "note_id": "3",
                "title": "Elicitation",
                "body": "MRTR pauses and resumes a request.",
            }
        ],
        "count": 1,
        "total": 1,
        "next_cursor": None,
    }
    assert isinstance(result.content[1], ResourceLink)
    assert result.content[1].uri == "notes://3"


@pytest.mark.anyio
async def test_search_notes_paginates_with_opaque_cursor(server: MCPServer) -> None:
    async with Client(server) as client:
        first = await client.call_tool("search_notes", {"query": "", "limit": 2})
        cursor = first.structured_content["next_cursor"]
        second = await client.call_tool(
            "search_notes",
            {"query": "", "limit": 2, "cursor": cursor},
        )

    assert [note["note_id"] for note in first.structured_content["notes"]] == ["1", "2"]
    assert first.structured_content["total"] == 3
    assert isinstance(cursor, str)
    assert [note["note_id"] for note in second.structured_content["notes"]] == ["3"]
    assert second.structured_content["next_cursor"] is None


@pytest.mark.anyio
async def test_search_notes_rejects_cursor_bound_to_other_query(server: MCPServer) -> None:
    async with Client(server) as client:
        first = await client.call_tool("search_notes", {"query": "", "limit": 1})
        result = await client.call_tool(
            "search_notes",
            {
                "query": "stateless",
                "limit": 1,
                "cursor": first.structured_content["next_cursor"],
            },
        )

    assert result.is_error is True
    content = result.content[0]
    assert isinstance(content, TextContent)
    assert "does not match the query" in content.text


@pytest.mark.anyio
async def test_search_notes_rejects_tampered_cursor(server: MCPServer) -> None:
    async with Client(server) as client:
        first = await client.call_tool("search_notes", {"query": "", "limit": 1})
        cursor = first.structured_content["next_cursor"]
        tampered = ("A" if cursor[0] != "A" else "B") + cursor[1:]
        result = await client.call_tool(
            "search_notes",
            {"query": "", "limit": 1, "cursor": tampered},
        )

    assert result.is_error is True
    content = result.content[0]
    assert isinstance(content, TextContent)
    assert "Invalid search cursor" in content.text
