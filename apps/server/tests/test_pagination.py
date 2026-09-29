"""Unit tests for opaque stateless search cursors."""

import pytest
from mcp_stateless_server.pagination import (
    CursorError,
    decode_cursor,
    encode_cursor,
)


def test_cursor_round_trips_bound_offset() -> None:
    cursor = encode_cursor(query="MCP", limit=2, snapshot="snapshot-a", offset=2)

    assert (
        decode_cursor(
            cursor,
            query="mcp",
            limit=2,
            snapshot="snapshot-a",
            total=3,
        )
        == 2
    )


def test_cursor_rejects_tampering() -> None:
    cursor = encode_cursor(query="", limit=1, snapshot="snapshot-a", offset=1)
    tampered = ("A" if cursor[0] != "A" else "B") + cursor[1:]

    with pytest.raises(CursorError, match="Invalid search cursor"):
        decode_cursor(
            tampered,
            query="",
            limit=1,
            snapshot="snapshot-a",
            total=3,
        )


@pytest.mark.parametrize(
    ("query", "limit", "snapshot", "message"),
    [
        ("different", 1, "snapshot-a", "does not match the query"),
        ("", 2, "snapshot-a", "does not match the page size"),
        ("", 1, "snapshot-b", "is stale"),
    ],
)
def test_cursor_rejects_changed_bindings(
    query: str,
    limit: int,
    snapshot: str,
    message: str,
) -> None:
    cursor = encode_cursor(query="", limit=1, snapshot="snapshot-a", offset=1)

    with pytest.raises(CursorError, match=message):
        decode_cursor(
            cursor,
            query=query,
            limit=limit,
            snapshot=snapshot,
            total=3,
        )
