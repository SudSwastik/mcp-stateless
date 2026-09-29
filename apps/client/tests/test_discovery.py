"""Black-box tests for raw stateless discovery."""

import pytest
from mcp_stateless_client.config import ClientConfig
from mcp_stateless_client.discovery import ProtocolError, discover, verify


def test_discovers_server_over_http(live_server_url: str) -> None:
    observation = discover(ClientConfig(server_url=live_server_url))

    assert observation.status == 200
    assert observation.request_id == 1
    assert observation.result.supported_versions == ["2026-07-28"]
    assert observation.server_info is not None
    assert observation.server_info.name == "mcp-stateless-server"
    assert "mcp-session-id" not in observation.headers


def test_verifies_stateless_wire_contract(live_server_url: str) -> None:
    report = verify(ClientConfig(server_url=live_server_url))

    assert report.passed is True
    assert {check.name for check in report.checks} == {
        "capabilities",
        "header_body_routing",
        "jsonrpc_correlation",
        "protocol_version",
        "server_identity",
        "stateless_transport",
    }


def test_reports_incompatible_pinned_version(live_server_url: str) -> None:
    config = ClientConfig(server_url=live_server_url, protocol_version="2099-01-01")

    with pytest.raises(ProtocolError, match="Unsupported protocol version"):
        discover(config)
