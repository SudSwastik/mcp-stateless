"""Tests for client configuration."""

import pytest
from mcp_stateless_client.config import ClientConfig, ConfigurationError


def test_loads_environment_configuration() -> None:
    config = ClientConfig.from_env(
        {
            "MCP_SERVER_URL": "https://example.test/mcp",
            "MCP_PROTOCOL_VERSION": "2026-07-28",
            "MCP_REQUEST_TIMEOUT_SECONDS": "2.5",
            "MCP_OUTPUT_FORMAT": "json",
            "MCP_ELICITATION_POLICY": "decline",
        }
    )

    assert config.server_url == "https://example.test/mcp"
    assert config.request_timeout_seconds == 2.5
    assert config.output_format == "json"
    assert config.elicitation_policy == "decline"


def test_defaults_to_interactive_elicitation_policy() -> None:
    assert ClientConfig.from_env({}).elicitation_policy == "interactive"


def test_loads_issuer_pinned_oauth_client_credentials_without_exposing_secret() -> None:
    config = ClientConfig.from_env(
        {
            "MCP_SERVER_URL": "https://mcp.example/mcp",
            "MCP_OAUTH_ISSUER_URL": "https://identity.example/",
            "MCP_OAUTH_CLIENT_ID": "notes-client",
            "MCP_OAUTH_CLIENT_SECRET": "sensitive-client-secret",
            "MCP_OAUTH_SCOPE": "notes:read notes:write",
        }
    )

    assert config.oauth is not None
    assert config.oauth.issuer_url == "https://identity.example/"
    assert config.oauth.client_id == "notes-client"
    assert config.oauth.scope == "notes:read notes:write"
    assert "sensitive-client-secret" not in repr(config)


@pytest.mark.parametrize(
    "environment",
    [
        {"MCP_OAUTH_CLIENT_ID": "notes-client"},
        {
            "MCP_SERVER_URL": "http://mcp.example/mcp",
            "MCP_OAUTH_ISSUER_URL": "https://identity.example/",
            "MCP_OAUTH_CLIENT_ID": "notes-client",
            "MCP_OAUTH_CLIENT_SECRET": "secret",
        },
        {
            "MCP_OAUTH_ISSUER_URL": "http://identity.example/",
            "MCP_OAUTH_CLIENT_ID": "notes-client",
            "MCP_OAUTH_CLIENT_SECRET": "secret",
        },
    ],
)
def test_rejects_incomplete_or_insecure_oauth_configuration(
    environment: dict[str, str],
) -> None:
    with pytest.raises(ConfigurationError):
        ClientConfig.from_env(environment)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("MCP_SERVER_URL", "localhost:8000/mcp"),
        ("MCP_REQUEST_TIMEOUT_SECONDS", "0"),
        ("MCP_OUTPUT_FORMAT", "yaml"),
        ("MCP_ELICITATION_POLICY", "approve-everything"),
    ],
)
def test_rejects_invalid_environment_configuration(field: str, value: str) -> None:
    with pytest.raises(ConfigurationError):
        ClientConfig.from_env({field: value})
