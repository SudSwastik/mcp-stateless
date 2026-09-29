"""Application factory and ASGI entry point."""

import os
from typing import cast

from mcp.server import MCPServer
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.caching import CacheHint
from mcp.server.mcpserver import RequestStateSecurity
from mcp.server.subscriptions import InMemorySubscriptionBus, SubscriptionBus
from mcp_types.methods import CACHEABLE_METHODS, CacheableMethod
from starlette.types import ASGIApp

from mcp_stateless_server.apps import AppsExtension, register_apps
from mcp_stateless_server.auth import auth_settings_from_env, jwt_verifier_from_env
from mcp_stateless_server.completions import register_completions
from mcp_stateless_server.prompts import register_prompts
from mcp_stateless_server.resources import register_resources
from mcp_stateless_server.sqlite_store import SQLiteNoteStore
from mcp_stateless_server.store import NoteStore
from mcp_stateless_server.subscriptions import (
    CloseRedisBusOnShutdown,
    RedisSubscriptionBus,
)
from mcp_stateless_server.tasks import ReindexTaskStore, TasksExtension
from mcp_stateless_server.tools import register_tools


def create_server(
    store: NoteStore | None = None,
    *,
    subscriptions: SubscriptionBus | None = None,
    request_state_security: RequestStateSecurity | None = None,
    task_store: ReindexTaskStore | None = None,
    auth: AuthSettings | None = None,
    token_verifier: TokenVerifier | None = None,
) -> MCPServer:
    """Build an isolated MCP server instance."""
    if (auth is None) != (token_verifier is None):
        raise ValueError("OAuth protection requires both AuthSettings and a TokenVerifier")
    note_store = store or NoteStore()
    reindex_tasks = task_store or ReindexTaskStore()
    event_bus = subscriptions if subscriptions is not None else InMemorySubscriptionBus()
    server = MCPServer(
        "mcp-stateless-server",
        version="0.1.0",
        cache_hints={
            cast(CacheableMethod, method): CacheHint(ttl_ms=30_000, scope="public")
            for method in CACHEABLE_METHODS
        },
        subscriptions=event_bus,
        request_state_security=request_state_security,
        extensions=[TasksExtension(reindex_tasks), AppsExtension()],
        auth=auth,
        token_verifier=token_verifier,
    )
    register_tools(server, note_store, reindex_tasks)
    register_apps(server, note_store)
    register_resources(server, note_store)
    register_prompts(server, note_store)
    register_completions(server, note_store)
    return server


mcp_auth = auth_settings_from_env()
mcp_subscription_bus = (
    RedisSubscriptionBus.from_url(os.environ["MCP_SUBSCRIPTION_REDIS_URL"])
    if os.environ.get("MCP_SUBSCRIPTION_REDIS_URL")
    else None
)
mcp_state_path = os.environ.get("MCP_STATE_DB_PATH")
mcp = create_server(
    store=SQLiteNoteStore(mcp_state_path) if mcp_state_path else None,
    subscriptions=mcp_subscription_bus,
    auth=mcp_auth,
    token_verifier=jwt_verifier_from_env(mcp_auth),
)
_asgi_app: ASGIApp = mcp.streamable_http_app()
if mcp_subscription_bus is not None:
    _asgi_app = CloseRedisBusOnShutdown(_asgi_app, mcp_subscription_bus)
app = _asgi_app
