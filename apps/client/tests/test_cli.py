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


def test_call_command_returns_structured_json(
    live_server_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "call",
            "add",
            "--arguments",
            '{"a": 2, "b": 5}',
            "--url",
            live_server_url,
            "--output",
            "json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["structuredContent"] == {"result": 7}


def test_read_and_prompt_commands_render_text(
    live_server_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    read_exit = main(["read", "notes://1", "--url", live_server_url])
    read_output = capsys.readouterr().out
    prompt_exit = main(
        [
            "prompt",
            "summarize_note",
            "--arguments",
            '{"note_id": "1", "style": "brief"}',
            "--url",
            live_server_url,
        ]
    )
    prompt_output = capsys.readouterr().out

    assert read_exit == 0
    assert "Protocol overview" in read_output
    assert prompt_exit == 0
    assert "[user]" in prompt_output
    assert "one sentence" in prompt_output


def test_rejects_non_object_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["call", "add", "--arguments", "[]"])

    assert exit_code == 2
    assert "must be a JSON object" in capsys.readouterr().err


def test_tool_error_has_distinct_exit_status(
    live_server_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["call", "unknown", "--url", live_server_url])

    assert exit_code == 1
    assert capsys.readouterr().out


def test_protocol_error_has_clean_json_output(
    live_server_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "read",
            "notes://999",
            "--url",
            live_server_url,
            "--output",
            "json",
        ]
    )

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["errorType"] == "protocol"
    assert "Unknown note: 999" in payload["error"]
