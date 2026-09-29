"""Black-box tests for issuer-pinned OAuth client-credentials access."""

from __future__ import annotations

import json

import httpx2
import pytest
from mcp.shared.auth import OAuthMetadata, ProtectedResourceMetadata
from mcp_stateless_client.config import ClientConfig
from mcp_stateless_client.discovery import ProtocolError, discover
from mcp_stateless_client.primitives import call_tool

MCP_URL = "https://mcp.example/mcp"
ISSUER_URL = "https://identity.example"
RESOURCE_METADATA_URL = "https://mcp.example/.well-known/oauth-protected-resource/mcp"


@pytest.mark.parametrize(
    ("advertised_issuer", "should_succeed"),
    [(ISSUER_URL, True), ("https://attacker.example", False)],
)
def test_client_credentials_flow_authenticates_sdk_and_raw_http(
    monkeypatch: pytest.MonkeyPatch,
    advertised_issuer: str,
    should_succeed: bool,
) -> None:
    requests: list[httpx2.Request] = []
    token_requests = 0

    async def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal token_requests
        requests.append(request)
        if request.url == httpx2.URL(MCP_URL):
            authorization = request.headers.get("authorization")
            if authorization != "Bearer access-token":
                return httpx2.Response(
                    401,
                    headers={
                        "WWW-Authenticate": (
                            f'Bearer resource_metadata="{RESOURCE_METADATA_URL}"'
                        )
                    },
                    json={"error": "invalid_token"},
                    request=request,
                )
            body = json.loads(request.content)
            if body["method"] == "tools/call":
                result = {
                    "content": [{"type": "text", "text": "sum=7"}],
                    "structuredContent": {"result": 7},
                    "isError": False,
                    "resultType": "complete",
                }
            elif body["method"] == "tools/list":
                result = {
                    "tools": [],
                    "resultType": "complete",
                    "ttlMs": 0,
                    "cacheScope": "public",
                }
            elif body["method"] == "server/discover":
                result = {
                    "supportedVersions": ["2026-07-28"],
                    "capabilities": {},
                    "resultType": "complete",
                    "ttlMs": 0,
                    "cacheScope": "public",
                }
            else:
                raise AssertionError(f"unexpected MCP method {body['method']}")
            return httpx2.Response(
                200,
                headers={"Content-Type": "application/json"},
                json={"jsonrpc": "2.0", "id": body["id"], "result": result},
                request=request,
            )

        if str(request.url) == RESOURCE_METADATA_URL:
            resource_metadata = ProtectedResourceMetadata.model_validate(
                {
                    "resource": MCP_URL,
                    "authorization_servers": [advertised_issuer],
                    "bearer_methods_supported": ["header"],
                }
            )
            return httpx2.Response(
                200,
                json=resource_metadata.model_dump(by_alias=True, mode="json"),
                request=request,
            )

        if str(request.url) == f"{advertised_issuer}/.well-known/oauth-authorization-server":
            issuer_metadata = OAuthMetadata.model_validate(
                {
                    "issuer": advertised_issuer,
                    "authorization_endpoint": f"{advertised_issuer}/authorize",
                    "token_endpoint": f"{advertised_issuer}/token",
                    "response_types_supported": ["code"],
                    "grant_types_supported": ["client_credentials"],
                    "token_endpoint_auth_methods_supported": ["client_secret_basic"],
                }
            )
            return httpx2.Response(
                200,
                json=issuer_metadata.model_dump(by_alias=True, mode="json"),
                request=request,
            )

        if str(request.url) == f"{advertised_issuer}/token":
            token_requests += 1
            assert request.method == "POST"
            assert request.headers.get("authorization", "").startswith("Basic ")
            assert "grant_type=client_credentials" in request.content.decode()
            return httpx2.Response(
                200,
                json={
                    "access_token": "access-token",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": "notes:read",
                },
                request=request,
            )

        raise AssertionError(f"unexpected OAuth request: {request.method} {request.url}")

    transport = httpx2.MockTransport(handler)
    original_async_client = httpx2.AsyncClient

    def mock_async_client(**kwargs: object) -> httpx2.AsyncClient:
        return original_async_client(transport=transport, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx2, "AsyncClient", mock_async_client)
    config = ClientConfig.from_env(
        {
            "MCP_SERVER_URL": MCP_URL,
            "MCP_OAUTH_ISSUER_URL": ISSUER_URL,
            "MCP_OAUTH_CLIENT_ID": "notes-client",
            "MCP_OAUTH_CLIENT_SECRET": "test-secret",
            "MCP_OAUTH_SCOPE": "notes:read",
        }
    )

    if not should_succeed:
        with pytest.raises(ProtocolError, match="OAuth client-credentials authorization failed"):
            call_tool(config, "add", {"a": 3, "b": 4})
        assert token_requests == 0
        return

    result = call_tool(config, "add", {"a": 3, "b": 4})
    observation = discover(config, request_id=77)

    assert result.is_error is False
    assert result.structured_content == {"result": 7}
    assert observation.request_id == 77
    assert token_requests == 1
    authenticated_mcp_requests = [
        request
        for request in requests
        if request.url == httpx2.URL(MCP_URL) and request.headers.get("authorization")
    ]
    assert len(authenticated_mcp_requests) >= 3
    assert all(
        request.headers["authorization"] == "Bearer access-token"
        for request in authenticated_mcp_requests
    )
