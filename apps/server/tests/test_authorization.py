"""Black-box tests for the SDK-backed OAuth resource-server boundary."""

from __future__ import annotations

import time

import pytest
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from mcp_stateless_server.auth import (
    AuthenticationConfigurationError,
    auth_settings_from_env,
)
from mcp_stateless_server.server import create_server
from starlette.testclient import TestClient

RESOURCE_URL = "https://notes.example/mcp"
ISSUER_URL = "https://identity.example/"
TEST_TRANSPORT_SECURITY = TransportSecuritySettings(allowed_hosts=["127.0.0.1"])


class TestTokenVerifier:
    """Small deterministic verifier used only to exercise the SDK middleware."""

    async def verify_token(self, token: str) -> AccessToken | None:
        now = int(time.time())
        access_tokens = {
            "valid": AccessToken(
                token="valid",
                client_id="test-client",
                scopes=["notes:read"],
                expires_at=now + 60,
                resource=RESOURCE_URL,
            ),
            "expired": AccessToken(
                token="expired",
                client_id="test-client",
                scopes=["notes:read"],
                expires_at=now - 60,
                resource=RESOURCE_URL,
            ),
            "wrong-audience": AccessToken(
                token="wrong-audience",
                client_id="test-client",
                scopes=["notes:read"],
                expires_at=now + 60,
                resource="https://other.example/mcp",
            ),
            "insufficient-scope": AccessToken(
                token="insufficient-scope",
                client_id="test-client",
                scopes=["notes:write"],
                expires_at=now + 60,
                resource=RESOURCE_URL,
            ),
        }
        return access_tokens.get(token)


def _auth_settings() -> AuthSettings:
    return AuthSettings.model_validate(
        {
            "issuer_url": ISSUER_URL,
            "resource_server_url": RESOURCE_URL,
            "required_scopes": ["notes:read"],
            "validate_token_resource": True,
        }
    )


def _discover_request(authorization: str | None = None) -> tuple[dict[str, str], dict[str, object]]:
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Mcp-Method": "server/discover",
        "MCP-Protocol-Version": "2026-07-28",
    }
    if authorization is not None:
        headers["Authorization"] = authorization
    return headers, {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "server/discover",
        "params": {
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientCapabilities": {},
                "io.modelcontextprotocol/clientInfo": {"name": "auth-test", "version": "0"},
            }
        },
    }


def test_auth_mode_is_unauthenticated_by_default() -> None:
    assert auth_settings_from_env({}) is None
    assert auth_settings_from_env({"MCP_AUTH_MODE": "none"}) is None


def test_oauth_mode_requires_complete_https_configuration() -> None:
    with pytest.raises(AuthenticationConfigurationError, match="requires"):
        auth_settings_from_env({"MCP_AUTH_MODE": "oauth"})

    with pytest.raises(AuthenticationConfigurationError, match="HTTPS"):
        auth_settings_from_env(
            {
                "MCP_AUTH_MODE": "oauth",
                "MCP_OAUTH_ISSUER_URL": "http://identity.example/",
                "MCP_PUBLIC_BASE_URL": RESOURCE_URL,
            }
        )


def test_oauth_settings_include_required_scopes_and_resource_validation() -> None:
    settings = auth_settings_from_env(
        {
            "MCP_AUTH_MODE": "oauth",
            "MCP_OAUTH_ISSUER_URL": ISSUER_URL,
            "MCP_PUBLIC_BASE_URL": RESOURCE_URL,
            "MCP_REQUIRED_SCOPES": "notes:read notes:write",
        }
    )

    assert settings is not None
    assert settings.required_scopes == ["notes:read", "notes:write"]
    assert settings.validate_token_resource is True


def test_server_factory_requires_auth_and_verifier_together() -> None:
    with pytest.raises(ValueError, match="both AuthSettings and a TokenVerifier"):
        create_server(auth=_auth_settings())


def test_valid_bearer_token_can_discover_over_http() -> None:
    server = create_server(auth=_auth_settings(), token_verifier=TestTokenVerifier())
    with TestClient(
        server.streamable_http_app(
            stateless_http=True, transport_security=TEST_TRANSPORT_SECURITY
        ),
        base_url="http://127.0.0.1",
    ) as client:
        headers, body = _discover_request("Bearer valid")
        response = client.post("/mcp", headers=headers, json=body)

    assert response.status_code == 200
    assert response.json()["result"]["supportedVersions"] == ["2026-07-28"]


def test_missing_token_returns_protected_resource_metadata_challenge() -> None:
    server = create_server(auth=_auth_settings(), token_verifier=TestTokenVerifier())
    with TestClient(
        server.streamable_http_app(
            stateless_http=True, transport_security=TEST_TRANSPORT_SECURITY
        ),
        base_url="http://127.0.0.1",
    ) as client:
        headers, body = _discover_request()
        response = client.post("/mcp", headers=headers, json=body)

    assert response.status_code == 401
    assert "www-authenticate" in response.headers
    assert "oauth-protected-resource" in response.headers["www-authenticate"]


def test_protected_resource_metadata_publishes_the_configured_issuer() -> None:
    server = create_server(auth=_auth_settings(), token_verifier=TestTokenVerifier())
    with TestClient(
        server.streamable_http_app(
            stateless_http=True, transport_security=TEST_TRANSPORT_SECURITY
        ),
        base_url="http://127.0.0.1",
    ) as client:
        response = client.get("/.well-known/oauth-protected-resource/mcp")

    assert response.status_code == 200
    metadata = response.json()
    assert metadata["resource"] == RESOURCE_URL
    assert metadata["authorization_servers"] == [ISSUER_URL]


@pytest.mark.parametrize(
    ("token", "expected_status"),
    [
        ("unknown", 401),
        ("expired", 401),
        ("wrong-audience", 401),
        ("insufficient-scope", 403),
    ],
)
def test_rejects_invalid_bearer_tokens(token: str, expected_status: int) -> None:
    server = create_server(auth=_auth_settings(), token_verifier=TestTokenVerifier())
    with TestClient(
        server.streamable_http_app(
            stateless_http=True, transport_security=TEST_TRANSPORT_SECURITY
        ),
        base_url="http://127.0.0.1",
    ) as client:
        headers, body = _discover_request(f"Bearer {token}")
        response = client.post("/mcp", headers=headers, json=body)

    assert response.status_code == expected_status
