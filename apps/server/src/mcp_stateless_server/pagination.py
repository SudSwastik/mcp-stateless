"""Opaque, stateless cursor encoding for deterministic note search."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

_CURSOR_VERSION = 1
_CURSOR_DOMAIN_KEY = b"mcp-stateless/search-notes/cursor/v1"
_SIGNATURE_BYTES = 16


class CursorError(ValueError):
    """A search cursor is malformed, stale, or bound to different arguments."""


def query_fingerprint(query: str) -> str:
    """Return a stable digest for the normalized query."""
    normalized = query.casefold().strip().encode()
    return hashlib.sha256(normalized).hexdigest()[:16]


def snapshot_fingerprint(values: list[str]) -> str:
    """Return a stable digest for the ordered result snapshot."""
    encoded = json.dumps(values, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def _signature(payload: bytes) -> bytes:
    return hmac.digest(_CURSOR_DOMAIN_KEY, payload, "sha256")[:_SIGNATURE_BYTES]


def encode_cursor(*, query: str, limit: int, snapshot: str, offset: int) -> str:
    """Encode the next page position into an opaque URL-safe token."""
    payload = json.dumps(
        [_CURSOR_VERSION, query_fingerprint(query), limit, snapshot, offset],
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload + _signature(payload)).decode().rstrip("=")


def _decode_payload(cursor: str) -> list[Any]:
    try:
        padding = "=" * (-len(cursor) % 4)
        decoded = base64.b64decode(cursor + padding, altchars=b"-_", validate=True)
        if len(decoded) <= _SIGNATURE_BYTES:
            raise ValueError
        payload = decoded[:-_SIGNATURE_BYTES]
        signature = decoded[-_SIGNATURE_BYTES:]
        if not hmac.compare_digest(signature, _signature(payload)):
            raise ValueError
        value = json.loads(payload)
    except (UnicodeEncodeError, ValueError, json.JSONDecodeError) as exc:
        raise CursorError("Invalid search cursor") from exc
    if not isinstance(value, list) or len(value) != 5:
        raise CursorError("Invalid search cursor")
    return value


def decode_cursor(
    cursor: str,
    *,
    query: str,
    limit: int,
    snapshot: str,
    total: int,
) -> int:
    """Validate a cursor's bindings and return its result offset."""
    version, encoded_query, encoded_limit, encoded_snapshot, offset = _decode_payload(cursor)
    if version != _CURSOR_VERSION:
        raise CursorError("Unsupported search cursor version")
    if encoded_query != query_fingerprint(query):
        raise CursorError("Search cursor does not match the query")
    if encoded_limit != limit:
        raise CursorError("Search cursor does not match the page size")
    if encoded_snapshot != snapshot:
        raise CursorError("Search cursor is stale")
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 < offset < total:
        raise CursorError("Invalid search cursor offset")
    return offset
