"""Redis-backed cross-process delivery for modern MCP subscription events."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from mcp.shared.subscriptions import (
    PromptsListChanged,
    ResourcesListChanged,
    ResourceUpdated,
    ServerEvent,
    ToolsListChanged,
)
from redis.asyncio import Redis
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


class RedisSubscriptionBus:
    """Fan subscription events between server replicas using Redis Pub/Sub.

    Pass one instance to ``create_server`` per process and close it during
    application shutdown. Redis Pub/Sub is intentionally best-effort: events
    only tell clients to refetch and are not a durable event log.
    """

    def __init__(self, redis: Redis, channel: str = "mcp:subscription-events") -> None:
        if not channel:
            raise ValueError("Redis subscription channel must not be empty")
        self._redis = redis
        self._channel = channel
        self._listeners: dict[object, Callable[[ServerEvent], None]] = {}
        self._task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self._closed = False

    @classmethod
    def from_url(
        cls, url: str, *, channel: str = "mcp:subscription-events"
    ) -> RedisSubscriptionBus:
        """Create a bus backed by a Redis URL (TLS URLs are supported)."""
        return cls(Redis.from_url(url, decode_responses=True), channel=channel)

    async def publish(self, event: ServerEvent) -> None:
        """Publish an event for every replica's local listen streams."""
        if self._closed:
            raise RuntimeError("Redis subscription bus is closed")
        await self._redis.publish(self._channel, _encode_event(event))

    async def start(self) -> None:
        """Wait until the Redis channel is subscribed before accepting requests."""
        if self._closed:
            raise RuntimeError("Redis subscription bus is closed")
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._listen())
        await self._ready.wait()
        if self._task.done():
            await self._task

    def subscribe(self, listener: Callable[[ServerEvent], None]) -> Callable[[], None]:
        """Register a local listener and lazily start the Redis subscriber."""
        if self._closed:
            raise RuntimeError("Redis subscription bus is closed")
        token = object()
        self._listeners[token] = listener
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._listen())

        def unsubscribe() -> None:
            self._listeners.pop(token, None)

        return unsubscribe

    async def aclose(self) -> None:
        """Stop the Redis listener and close its client connection."""
        if self._closed:
            return
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        await self._redis.aclose()

    async def _listen(self) -> None:
        pubsub = self._redis.pubsub()
        try:
            await pubsub.subscribe(self._channel)
            self._ready.set()
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message is None:
                    continue
                event = _decode_event(message.get("data"))
                if event is None:
                    logger.warning("ignoring malformed Redis subscription event")
                    continue
                for listener in list(self._listeners.values()):
                    try:
                        listener(event)
                    except Exception:
                        logger.exception("subscription listener raised; continuing")
        finally:
            self._ready.set()
            await pubsub.aclose()  # type: ignore[no-untyped-call]


class CloseRedisBusOnShutdown:
    """ASGI wrapper that closes the bus after the app's shutdown completes."""

    def __init__(self, app: ASGIApp, bus: RedisSubscriptionBus) -> None:
        self._app = app
        self._bus = bus

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") == "http":
            await self._bus.start()

        async def close_on_shutdown(message: Message) -> None:
            if message.get("type") == "lifespan.startup.complete":
                await self._bus.start()
            if message.get("type") in {
                "lifespan.shutdown.complete",
                "lifespan.shutdown.failed",
            }:
                await self._bus.aclose()
            await send(message)

        await self._app(scope, receive, close_on_shutdown)


def _encode_event(event: ServerEvent) -> str:
    if isinstance(event, ToolsListChanged):
        data: dict[str, Any] = {"type": "tools_list_changed"}
    elif isinstance(event, PromptsListChanged):
        data = {"type": "prompts_list_changed"}
    elif isinstance(event, ResourcesListChanged):
        data = {"type": "resources_list_changed"}
    elif isinstance(event, ResourceUpdated):
        data = {"type": "resource_updated", "uri": event.uri}
    else:
        raise TypeError(f"unsupported subscription event: {type(event).__name__}")
    return json.dumps(data, separators=(",", ":"))


def _decode_event(value: object) -> ServerEvent | None:
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(value, str):
        return None
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    event_type = data.get("type")
    if event_type == "tools_list_changed":
        return ToolsListChanged()
    if event_type == "prompts_list_changed":
        return PromptsListChanged()
    if event_type == "resources_list_changed":
        return ResourcesListChanged()
    if event_type == "resource_updated" and isinstance(data.get("uri"), str):
        return ResourceUpdated(uri=data["uri"])
    return None
