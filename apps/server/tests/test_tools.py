"""Protocol-level tests for core tools."""

import pytest
from mcp import Client
from mcp.server import MCPServer


@pytest.mark.anyio
async def test_lists_core_tools(server: MCPServer) -> None:
    async with Client(server) as client:
        result = await client.list_tools()

    assert [tool.name for tool in result.tools] == ["add", "search_notes"]


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
    }
