"""Black-box smoke check for the local multi-replica Compose deployment."""

from __future__ import annotations

import argparse
import asyncio
import uuid

from mcp import Client
from mcp.shared.subscriptions import ResourcesListChanged
from mcp_stateless_client.config import ClientConfig
from mcp_stateless_client.primitives import call_tool, compatibility_report
from mcp_stateless_client.tasks import reindex_notes


async def _check_shared_notifications(config: ClientConfig, title: str) -> None:
    client = Client(config.server_url, mode=config.protocol_version)
    async with client, client.listen(
        resources_list_changed=True,
        resource_subscriptions=("notes://all",),
    ) as subscription:
        mutation = asyncio.create_task(
            asyncio.to_thread(
                call_tool,
                config,
                "create_note",
                {"title": title, "body": "Redis subscription fan-out smoke check."},
            )
        )
        event = await asyncio.wait_for(anext(subscription), timeout=10)
        result = await mutation
        if result.is_error:
            raise RuntimeError("Could not create a note while testing subscriptions")
        if not isinstance(event, ResourcesListChanged):
            raise RuntimeError(f"Expected resources/list_changed; got {type(event).__name__}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000/mcp",
        help="load-balanced MCP endpoint URL",
    )
    args = parser.parse_args()
    config = ClientConfig(server_url=args.url)

    report = compatibility_report(config)
    if not report.passed:
        raise RuntimeError("MCP compatibility verification failed")
    print("PASS: protocol and primitive compatibility")

    marker = uuid.uuid4().hex
    title = f"Replica smoke {marker}"
    created = call_tool(
        config,
        "create_note",
        {"title": title, "body": "Shared SQLite state smoke check."},
    )
    if created.is_error:
        raise RuntimeError("Could not create a note through the gateway")
    search = call_tool(config, "search_notes", {"query": title})
    if search.is_error or search.structured_content is None:
        raise RuntimeError("Could not find the created note through a separate request")
    if search.structured_content.get("total") != 1:
        raise RuntimeError("The note created through the gateway was not shared")
    print("PASS: note mutation visible to a later load-balanced request")

    asyncio.run(_check_shared_notifications(config, f"{title} events"))
    print("PASS: Redis subscription event delivered through the gateway")

    task = asyncio.run(reindex_notes(config, include_archived=True))
    if task.status != "completed" or task.result is None:
        raise RuntimeError(f"Task did not complete successfully: {task.status}")
    if task.result.get("include_archived") is not True:
        raise RuntimeError("Task input update was not preserved across requests")
    print("PASS: reindex task completed across load-balanced requests")


if __name__ == "__main__":
    main()
