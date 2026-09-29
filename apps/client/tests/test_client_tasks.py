"""Client task polling tests."""

import asyncio

from mcp_stateless_client.config import ClientConfig
from mcp_stateless_client.tasks import reindex_notes


def test_client_respects_changing_task_poll_intervals(live_server_url: str) -> None:
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    state = asyncio.run(
        reindex_notes(
            ClientConfig(server_url=live_server_url),
            include_archived=True,
            sleep=record_sleep,
        )
    )

    assert state.status == "completed"
    assert state.result == {
        "indexed_note_ids": ["1", "2", "3"],
        "include_archived": True,
    }
    assert delays == [0.25, 0.05]
