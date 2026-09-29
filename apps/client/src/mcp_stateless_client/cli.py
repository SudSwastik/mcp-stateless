"""Command-line interface for MCP discovery, verification, and primitives."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any, cast

from mcp_types import (
    CallToolResult,
    GetPromptResult,
    ReadResourceResult,
    TextContent,
    TextResourceContents,
)

from mcp_stateless_client.config import ClientConfig, ConfigurationError
from mcp_stateless_client.discovery import ClientError
from mcp_stateless_client.primitives import (
    CommandInputError,
    PrimitiveCatalog,
    call_tool,
    compatibility_report,
    get_prompt,
    inspect_catalog,
    read_resource,
)


def _add_connection_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--url", help="MCP Streamable HTTP endpoint")
    parser.add_argument("--protocol-version", help="pinned MCP protocol version")
    parser.add_argument("--timeout", type=float, help="request timeout in seconds")
    parser.add_argument("--output", choices=("text", "json"), help="output format")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mcp-stateless-client")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser(
        "inspect", help="show discovery metadata and primitive catalogs"
    )
    _add_connection_options(inspect_parser)
    verify_parser = subparsers.add_parser(
        "verify", help="run wire and primitive compatibility checks"
    )
    _add_connection_options(verify_parser)

    call_parser = subparsers.add_parser("call", help="call a tool")
    call_parser.add_argument("tool", help="tool name")
    call_parser.add_argument("--arguments", default="{}", help="JSON object of tool arguments")
    _add_connection_options(call_parser)

    read_parser = subparsers.add_parser("read", help="read a resource")
    read_parser.add_argument("uri", help="resource URI")
    _add_connection_options(read_parser)

    prompt_parser = subparsers.add_parser("prompt", help="render a prompt")
    prompt_parser.add_argument("name", help="prompt name")
    prompt_parser.add_argument(
        "--arguments", default="{}", help="JSON object of string prompt arguments"
    )
    _add_connection_options(prompt_parser)
    return parser


def _config(args: argparse.Namespace) -> ClientConfig:
    return ClientConfig.from_env(
        server_url=args.url,
        protocol_version=args.protocol_version,
        request_timeout_seconds=args.timeout,
        output_format=args.output,
    )


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _parse_arguments(value: str, *, strings_only: bool = False) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise CommandInputError(f"--arguments must be valid JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise CommandInputError("--arguments must be a JSON object")
    if strings_only and not all(
        isinstance(key, str) and isinstance(item, str) for key, item in parsed.items()
    ):
        raise CommandInputError("prompt --arguments values must all be strings")
    return cast(dict[str, Any], parsed)


def _dump_model(model: Any) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        model.model_dump(by_alias=True, mode="json", exclude_none=True),
    )


def _print_inspection(catalog: PrimitiveCatalog, config: ClientConfig) -> None:
    observation = catalog.discovery
    identity = observation.server_info
    capabilities = observation.result.capabilities.model_dump(exclude_none=True)
    print(f"Endpoint: {config.server_url}")
    print(f"Protocol: {', '.join(observation.result.supported_versions)}")
    print(
        "Server: "
        + (f"{identity.name} {identity.version}" if identity is not None else "not provided")
    )
    print(f"Capabilities: {', '.join(sorted(capabilities)) or 'none'}")
    print(
        f"Cache: {observation.result.cache_scope}, ttl={observation.result.ttl_ms}ms"
    )
    print(
        "Session header: "
        + (observation.headers.get("mcp-session-id") or "absent (stateless)")
    )
    tool_names = ", ".join(tool.name for tool in catalog.tools) or "none"
    print(f"Tools ({len(catalog.tools)}): {tool_names}")
    print(
        f"Resources ({len(catalog.resources)}): "
        + (", ".join(str(resource.uri) for resource in catalog.resources) or "none")
    )
    print(
        f"Resource templates ({len(catalog.resource_templates)}): "
        + (
            ", ".join(template.uri_template for template in catalog.resource_templates)
            or "none"
        )
    )
    print(
        f"Prompts ({len(catalog.prompts)}): "
        + (", ".join(prompt.name for prompt in catalog.prompts) or "none")
    )


def _print_tool_result(result: CallToolResult) -> None:
    if result.structured_content is not None:
        _print_json(result.structured_content)
        return
    for content in result.content:
        if isinstance(content, TextContent):
            print(content.text)
        else:
            _print_json(_dump_model(content))


def _print_resource_result(result: ReadResourceResult) -> None:
    for content in result.contents:
        if isinstance(content, TextResourceContents):
            print(content.text)
        else:
            print(f"[{content.mime_type or 'application/octet-stream'} base64 blob]")


def _print_prompt_result(result: GetPromptResult) -> None:
    if result.description:
        print(result.description)
    for message in result.messages:
        if isinstance(message.content, TextContent):
            print(f"[{message.role}] {message.content.text}")
        else:
            print(f"[{message.role}]")
            _print_json(_dump_model(message.content))


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return its process exit status."""
    args = _parser().parse_args(argv)
    config: ClientConfig | None = None
    try:
        config = _config(args)
        if args.command == "inspect":
            catalog = inspect_catalog(config)
            if config.output_format == "json":
                _print_json(catalog.to_dict())
            else:
                _print_inspection(catalog, config)
            return 0

        if args.command == "verify":
            report = compatibility_report(config)
            if config.output_format == "json":
                _print_json(report.to_dict())
            else:
                for check in report.checks:
                    marker = "PASS" if check.passed else "FAIL"
                    print(f"[{marker}] {check.name}: {check.detail}")
                print("Verification passed." if report.passed else "Verification failed.")
            return 0 if report.passed else 1

        if args.command == "call":
            tool_result = call_tool(config, args.tool, _parse_arguments(args.arguments))
            if config.output_format == "json":
                _print_json(_dump_model(tool_result))
            else:
                _print_tool_result(tool_result)
            return 1 if tool_result.is_error else 0

        if args.command == "read":
            resource_result = read_resource(config, args.uri)
            if config.output_format == "json":
                _print_json(_dump_model(resource_result))
            else:
                _print_resource_result(resource_result)
            return 0

        prompt_arguments = _parse_arguments(args.arguments, strings_only=True)
        prompt_result = get_prompt(
            config,
            args.name,
            cast(dict[str, str], prompt_arguments),
        )
        if config.output_format == "json":
            _print_json(_dump_model(prompt_result))
        else:
            _print_prompt_result(prompt_result)
        return 0
    except (ConfigurationError, ClientError) as exc:
        output_format = config.output_format if config is not None else args.output
        if output_format == "json":
            category = exc.category if isinstance(exc, ClientError) else "configuration"
            _print_json({"passed": False, "errorType": category, "error": str(exc)})
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 2


def entrypoint() -> None:
    """Console-script adapter."""
    raise SystemExit(main())
