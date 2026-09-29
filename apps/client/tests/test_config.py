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
        }
    )

    assert config.server_url == "https://example.test/mcp"
    assert config.request_timeout_seconds == 2.5
    assert config.output_format == "json"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("MCP_SERVER_URL", "localhost:8000/mcp"),
        ("MCP_REQUEST_TIMEOUT_SECONDS", "0"),
        ("MCP_OUTPUT_FORMAT", "yaml"),
    ],
)
def test_rejects_invalid_environment_configuration(field: str, value: str) -> None:
    with pytest.raises(ConfigurationError):
        ClientConfig.from_env({field: value})
