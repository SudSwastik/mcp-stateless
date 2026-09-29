"""Protocol-level tests for core prompts."""

import pytest
from mcp import Client
from mcp.server import MCPServer
from mcp.types import EmbeddedResource, TextContent, TextResourceContents


@pytest.mark.anyio
async def test_lists_summary_prompt(server: MCPServer) -> None:
    async with Client(server) as client:
        result = await client.list_prompts()

    assert [prompt.name for prompt in result.prompts] == ["summarize_note"]


@pytest.mark.anyio
async def test_renders_summary_prompt(server: MCPServer) -> None:
    async with Client(server) as client:
        result = await client.get_prompt(
            "summarize_note",
            {"note_id": "1", "style": "brief"},
        )

    assert len(result.messages) == 2
    instruction = result.messages[0].content
    embedded = result.messages[1].content
    assert isinstance(instruction, TextContent)
    assert "one sentence" in instruction.text
    assert "Protocol overview" in instruction.text
    assert isinstance(embedded, EmbeddedResource)
    assert isinstance(embedded.resource, TextResourceContents)
    assert embedded.resource.uri == "notes://1"
    assert "MCP requests use JSON-RPC." in embedded.resource.text
