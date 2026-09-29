"""Protocol-level tests for core prompts."""

import pytest
from mcp import Client
from mcp.server import MCPServer
from mcp.types import TextContent


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

    assert len(result.messages) == 1
    content = result.messages[0].content
    assert isinstance(content, TextContent)
    assert "Summarize the following note in one sentence." in content.text
    assert "Title: Protocol overview" in content.text
