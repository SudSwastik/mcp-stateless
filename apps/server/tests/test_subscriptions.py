from __future__ import annotations

import asyncio

import pytest
from mcp.shared.subscriptions import (
    PromptsListChanged,
    ResourcesListChanged,
    ResourceUpdated,
    ToolsListChanged,
)
from mcp_stateless_server.subscriptions import (
    CloseRedisBusOnShutdown,
    RedisSubscriptionBus,
    _decode_event,
    _encode_event,
)
from starlette.types import Message, Receive, Scope, Send


@pytest.mark.parametrize(
    "event",
    [
        ToolsListChanged(),
        PromptsListChanged(),
        ResourcesListChanged(),
        ResourceUpdated(uri="notes://42"),
    ],
)
def test_redis_wire_encoding_round_trips_all_subscription_events(event: object) -> None:
    assert _decode_event(_encode_event(event)) == event  # type: ignore[arg-type]


@pytest.mark.parametrize("payload", [b"\xff", "not json", "[]", "{}", 42, None])
def test_redis_wire_decoder_ignores_malformed_or_unknown_messages(payload: object) -> None:
    assert _decode_event(payload) is None


class _FakePubSub:
    def __init__(self) -> None:
        self.messages: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self.channel: str | None = None
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        self.channel = channel

    async def get_message(
        self, *, ignore_subscribe_messages: bool, timeout: float
    ) -> dict[str, object] | None:
        assert ignore_subscribe_messages is True
        try:
            return await asyncio.wait_for(self.messages.get(), timeout=timeout)
        except TimeoutError:
            return None

    async def aclose(self) -> None:
        self.closed = True


class _FakeRedis:
    def __init__(self) -> None:
        self.subscriber = _FakePubSub()
        self.published: list[tuple[str, str]] = []
        self.closed = False

    def pubsub(self) -> _FakePubSub:
        return self.subscriber

    async def publish(self, channel: str, message: str) -> None:
        self.published.append((channel, message))
        await self.subscriber.messages.put({"data": message})

    async def aclose(self) -> None:
        self.closed = True


def test_redis_bus_fans_published_events_to_local_listeners() -> None:
    async def run() -> None:
        redis = _FakeRedis()
        bus = RedisSubscriptionBus(redis)  # type: ignore[arg-type]
        received: list[object] = []
        unsubscribe = bus.subscribe(received.append)
        await asyncio.sleep(0)

        event = ResourceUpdated(uri="notes://42")
        await bus.publish(event)
        for _ in range(10):
            if received:
                break
            await asyncio.sleep(0)

        assert received == [event]
        assert redis.published == [("mcp:subscription-events", _encode_event(event))]
        unsubscribe()
        unsubscribe()
        await bus.aclose()
        assert redis.subscriber.closed is True
        assert redis.closed is True
        with pytest.raises(RuntimeError, match="closed"):
            await bus.publish(event)

    asyncio.run(run())


def test_asgi_shutdown_closes_redis_bus() -> None:
    async def run() -> None:
        redis = _FakeRedis()
        bus = RedisSubscriptionBus(redis)  # type: ignore[arg-type]
        sent: list[Message] = []

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            await send({"type": "lifespan.startup.complete"})
            assert redis.subscriber.channel == "mcp:subscription-events"
            await send({"type": "lifespan.shutdown.complete"})

        async def receive() -> Message:
            return {"type": "lifespan.shutdown"}

        async def send(message: Message) -> None:
            sent.append(message)

        wrapped = CloseRedisBusOnShutdown(app, bus)
        await wrapped({"type": "lifespan"}, receive, send)

        assert sent == [
            {"type": "lifespan.startup.complete"},
            {"type": "lifespan.shutdown.complete"},
        ]
        assert redis.closed is True

    asyncio.run(run())
