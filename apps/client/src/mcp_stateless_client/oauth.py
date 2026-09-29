"""OAuth client-credentials transport using the MCP SDK provider."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx2
from mcp.client.auth.extensions.client_credentials import ClientCredentialsOAuthProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


@dataclass(slots=True)
class InMemoryOAuthTokenStorage:
    """Keep short-lived client-credentials tokens only for this CLI invocation."""

    tokens: OAuthToken | None = None
    client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client_info = client_info


@dataclass(frozen=True, slots=True)
class OAuthClientCredentials:
    """Credentials and issuer pinning for OAuth client-credentials grant."""

    issuer_url: str
    client_id: str
    client_secret: str = field(repr=False)
    scope: str | None = None
    storage: InMemoryOAuthTokenStorage = field(
        default_factory=InMemoryOAuthTokenStorage, repr=False
    )

    def provider(self, server_url: str) -> ClientCredentialsOAuthProvider:
        return ClientCredentialsOAuthProvider(
            server_url=server_url,
            storage=self.storage,
            client_id=self.client_id,
            client_secret=self.client_secret,
            scope=self.scope,
            issuer=self.issuer_url,
        )


@asynccontextmanager
async def oauth_http_client(
    server_url: str,
    credentials: OAuthClientCredentials,
    timeout_seconds: float,
) -> AsyncIterator[httpx2.AsyncClient]:
    """Yield an HTTPS-only, non-redirecting HTTP client with OAuth auth hooks."""
    async with httpx2.AsyncClient(
        auth=credentials.provider(server_url),
        timeout=timeout_seconds,
        verify=True,
        follow_redirects=False,
    ) as client:
        yield client


@asynccontextmanager
async def oauth_streamable_transport(
    server_url: str,
    credentials: OAuthClientCredentials,
    timeout_seconds: float,
) -> AsyncIterator[Any]:
    """Keep the authenticated HTTP client alive for the MCP transport lifetime."""
    async with (
        oauth_http_client(server_url, credentials, timeout_seconds) as http_client,
        streamable_http_client(server_url, http_client=http_client) as streams,
    ):
        yield streams
