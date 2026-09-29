"""Protocol-level tests for deterministic argument completion."""

import pytest
from mcp import Client
from mcp.server import MCPServer
from mcp_types import PromptReference, ResourceTemplateReference


@pytest.mark.anyio
async def test_completes_prompt_note_ids_and_styles(server: MCPServer) -> None:
    async with Client(server) as client:
        note_ids = await client.complete(
            PromptReference(name="summarize_note"),
            {"name": "note_id", "value": ""},
        )
        styles = await client.complete(
            PromptReference(name="summarize_note"),
            {"name": "style", "value": "b"},
        )

    assert note_ids.completion.values == ["1", "2", "3"]
    assert note_ids.completion.total == 3
    assert note_ids.completion.has_more is False
    assert styles.completion.values == ["brief"]


@pytest.mark.anyio
async def test_completes_resource_template_note_id(server: MCPServer) -> None:
    async with Client(server) as client:
        result = await client.complete(
            ResourceTemplateReference(uri="notes://{note_id}"),
            {"name": "note_id", "value": "2"},
        )

    assert result.completion.values == ["2"]
