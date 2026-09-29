"""Black-box tests for scoped response caching and event invalidation."""

from __future__ import annotations

import asyncio
import json

from mcp import Client
from mcp.client.caching import CacheConfig, InMemoryResponseCacheStore
from mcp.shared.subscriptions import ResourceUpdated
from mcp_stateless_client.config import ClientConfig
from mcp_stateless_client.primitives import call_tool, read_resource
from mcp_types import ReadResourceResult, TextResourceContents


def _note_count(result: ReadResourceResult) -> int:
    contents = result.contents
    assert isinstance(contents[0], TextResourceContents)
    return len(json.loads(contents[0].text))


def test_shared_client_cache_expires_by_server_ttl(live_server_url: str) -> None:
    now = [1_000.0]
    cache_store = InMemoryResponseCacheStore()
    config = ClientConfig(
        server_url=live_server_url,
        response_cache=CacheConfig(
            store=cache_store,
            partition="expiry-test",
            clock=lambda: now[0],
        ),
    )

    assert _note_count(read_resource(config, "notes://all")) == 3
    created = call_tool(
        config,
        "create_note",
        {"title": "Cache expiry", "body": "The cache will expire."},
    )
    assert created.is_error is False

    # A fresh client reuses the caller-supplied store, so the cached snapshot remains.
    assert _note_count(read_resource(config, "notes://all")) == 3
    now[0] += 31
    assert _note_count(read_resource(config, "notes://all")) == 4


def test_resource_event_replaces_only_matching_principal_cache(
    live_server_url: str,
) -> None:
    shared_store = InMemoryResponseCacheStore()
    alice = ClientConfig(
        server_url=live_server_url,
        response_cache=CacheConfig(store=shared_store, partition="alice"),
    )
    bob = ClientConfig(
        server_url=live_server_url,
        response_cache=CacheConfig(store=shared_store, partition="bob"),
    )
    assert _note_count(read_resource(alice, "notes://all")) == 3
    assert _note_count(read_resource(bob, "notes://all")) == 3

    async def create_while_listening() -> int:
        async with Client(
            alice.server_url,
            mode=alice.protocol_version,
            cache=alice.response_cache,
        ) as client, client.listen(
            resources_list_changed=True,
            resource_subscriptions=("notes://all",),
        ) as subscription:
            result = await client.call_tool(
                "create_note",
                {"title": "Scoped cache", "body": "Only Alice refreshes."},
            )
            assert result.is_error is False
            while True:
                event = await anext(subscription)
                if isinstance(event, ResourceUpdated) and event.uri == "notes://all":
                    break
            return _note_count(await client.read_resource("notes://all"))

    assert asyncio.run(create_while_listening()) == 4
    # Bob's private partition remains stale until its own TTL or notification.
    assert _note_count(read_resource(bob, "notes://all")) == 3
