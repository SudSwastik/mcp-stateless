"""Tests for user-facing client commands."""

import json

import pytest
from mcp_stateless_client.cli import main


def test_verify_json_output(
    live_server_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["verify", "--url", live_server_url, "--output", "json"])

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["passed"] is True
    assert payload["protocolVersion"] == "2026-07-28"


def test_connection_failure_is_clear(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        [
            "inspect",
            "--url",
            "http://127.0.0.1:1/mcp",
            "--timeout",
            "0.1",
        ]
    )

    assert exit_code == 2
    captured = capsys.readouterr()
    assert "Could not connect" in captured.err
