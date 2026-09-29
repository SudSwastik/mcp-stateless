"""Protocol tests for server cache TTL hints."""

import pytest
from mcp import Client
from mcp.client.caching import CacheConfig, InMemoryResponseCacheStore
from mcp.server import MCPServer
from mcp.server.caching import CacheHint
from mcp_types import TextResourceContents


@pytest.mark.anyio
async def test_zero_ttl_resource_is_not_reused_from_client_cache() -> None:
    reads = 0
    server = MCPServer(
        "zero-ttl-server",
        version="1.0",
        cache_hints={"resources/read": CacheHint(ttl_ms=0, scope="private")},
    )

    @server.resource("test://counter")
    def counter() -> str:
        nonlocal reads
        reads += 1
        return str(reads)

    config = CacheConfig(
        store=InMemoryResponseCacheStore(),
        partition="zero-ttl-test",
        target_id="zero-ttl-server",
    )
    async with Client(server, cache=config) as client:
        first = await client.read_resource("test://counter")
        second = await client.read_resource("test://counter")

    assert isinstance(first.contents[0], TextResourceContents)
    assert isinstance(second.contents[0], TextResourceContents)
    assert [first.contents[0].text, second.contents[0].text] == ["1", "2"]
