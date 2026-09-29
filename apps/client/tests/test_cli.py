"""Tests for user-facing client commands."""

import json

import pytest
from mcp_stateless_client.cli import main


def test_verify_json_output(live_server_url: str, capsys: pytest.CaptureFixture[str]) -> None:
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


@pytest.mark.parametrize(
    ("policy", "expected_action"),
    [("accept", "created"), ("decline", "declined"), ("cancel", "cancelled")],
)
def test_call_command_handles_mrtr_policies_over_http(
    live_server_url: str,
    capsys: pytest.CaptureFixture[str],
    policy: str,
    expected_action: str,
) -> None:
    exit_code = main(
        [
            "call",
            "create_note",
            "--arguments",
            '{"body": "Created by the CLI."}',
            "--url",
            live_server_url,
            "--elicitation-policy",
            policy,
            "--output",
            "json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    outcome = payload["structuredContent"]
    assert outcome["action"] == expected_action
    if policy == "accept":
        assert outcome["note"]["title"] == "Elicited title"
    else:
        assert outcome["note"] is None


def test_call_command_interactively_collects_form_values(
    live_server_url: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = iter(("a", "Interactive title"))
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    exit_code = main(
        [
            "call",
            "create_note",
            "--arguments",
            '{"body": "Created interactively."}',
            "--url",
            live_server_url,
            "--elicitation-policy",
            "interactive",
            "--output",
            "json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["structuredContent"]["note"]["title"] == "Interactive title"


def test_call_command_accepts_delete_confirmation_over_http(
    live_server_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "call",
            "delete_note",
            "--arguments",
            '{"note_id": "2"}',
            "--url",
            live_server_url,
            "--elicitation-policy",
            "accept",
            "--output",
            "json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["structuredContent"]["action"] == "deleted"


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
