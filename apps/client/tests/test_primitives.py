"""Black-box tests for SDK-backed primitive operations."""

import asyncio
import json

import pytest
from mcp_stateless_client.config import ClientConfig
from mcp_stateless_client.discovery import ProtocolError
from mcp_stateless_client.primitives import (
    _collect_pages,
    call_tool,
    compatibility_report,
    complete_argument,
    get_prompt,
    inspect_catalog,
    read_resource,
)
from mcp_types import PromptReference, ResourceTemplateReference, TextContent, TextResourceContents


def test_inspects_all_advertised_catalogs(live_server_url: str) -> None:
    catalog = inspect_catalog(ClientConfig(server_url=live_server_url))

    assert [tool.name for tool in catalog.tools] == [
        "add",
        "create_note",
        "delete_note",
        "publish_note",
        "search_notes",
    ]
    assert [str(resource.uri) for resource in catalog.resources] == [
        "notes://all",
        "notes://stats",
    ]
    assert [template.uri_template for template in catalog.resource_templates] == [
        "notes://{note_id}"
    ]
    assert [prompt.name for prompt in catalog.prompts] == ["summarize_note"]


def test_calls_tool_without_discovery_handshake(live_server_url: str) -> None:
    result = call_tool(
        ClientConfig(server_url=live_server_url),
        "add",
        {"a": 7, "b": 8},
    )

    assert result.is_error is False
    assert result.structured_content == {"result": 15}


def test_reads_resource(live_server_url: str) -> None:
    result = read_resource(ClientConfig(server_url=live_server_url), "notes://1")

    content = result.contents[0]
    assert isinstance(content, TextResourceContents)
    assert json.loads(content.text)["title"] == "Protocol overview"


def test_renders_prompt(live_server_url: str) -> None:
    result = get_prompt(
        ClientConfig(server_url=live_server_url),
        "summarize_note",
        {"note_id": "1", "style": "brief"},
    )

    content = result.messages[0].content
    assert isinstance(content, TextContent)
    assert "one sentence" in content.text


def test_preserves_tool_level_errors(live_server_url: str) -> None:
    result = call_tool(ClientConfig(server_url=live_server_url), "unknown", {})

    assert result.is_error is True
    assert result.content


def test_builds_primitive_compatibility_report(live_server_url: str) -> None:
    report = compatibility_report(ClientConfig(server_url=live_server_url))

    assert report.passed is True
    assert {check.name for check in report.primitive_checks} == {
        "completion",
        "prompt_catalog",
        "resource_catalog",
        "tool_catalog",
        "tool_schemas",
    }


def test_requests_stable_prompt_and_resource_completions(live_server_url: str) -> None:
    config = ClientConfig(server_url=live_server_url)

    styles = complete_argument(
        config,
        PromptReference(name="summarize_note"),
        "style",
        "d",
    )
    note_ids = complete_argument(
        config,
        ResourceTemplateReference(uri="notes://{note_id}"),
        "note_id",
    )

    assert styles.completion.values == ["detailed"]
    assert note_ids.completion.values == ["1", "2", "3"]


def test_rejects_repeated_pagination_cursor() -> None:
    async def repeated_page(cursor: str | None) -> tuple[list[str], str | None]:
        return (["first"] if cursor is None else ["second"], "same-cursor")

    with pytest.raises(ProtocolError, match="repeated pagination cursor"):
        asyncio.run(_collect_pages(repeated_page))
