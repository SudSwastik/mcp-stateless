"""Command-line interface for MCP discovery and verification."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from mcp_stateless_client.config import ClientConfig, ConfigurationError
from mcp_stateless_client.discovery import ClientError, DiscoveryObservation, discover, verify


def _add_connection_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--url", help="MCP Streamable HTTP endpoint")
    parser.add_argument("--protocol-version", help="pinned MCP protocol version")
    parser.add_argument("--timeout", type=float, help="request timeout in seconds")
    parser.add_argument("--output", choices=("text", "json"), help="output format")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mcp-stateless-client")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect", help="show server discovery metadata")
    _add_connection_options(inspect_parser)
    verify_parser = subparsers.add_parser("verify", help="run stateless wire checks")
    _add_connection_options(verify_parser)
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


def _print_inspection(observation: DiscoveryObservation, config: ClientConfig) -> None:
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


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return its process exit status."""
    args = _parser().parse_args(argv)
    try:
        config = _config(args)
        if args.command == "inspect":
            observation = discover(config)
            if config.output_format == "json":
                _print_json(observation.to_dict())
            else:
                _print_inspection(observation, config)
            return 0

        report = verify(config)
        if config.output_format == "json":
            _print_json(report.to_dict())
        else:
            for check in report.checks:
                marker = "PASS" if check.passed else "FAIL"
                print(f"[{marker}] {check.name}: {check.detail}")
            print("Verification passed." if report.passed else "Verification failed.")
        return 0 if report.passed else 1
    except (ConfigurationError, ClientError) as exc:
        if getattr(args, "output", None) == "json":
            _print_json({"passed": False, "error": str(exc)})
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 2


def entrypoint() -> None:
    """Console-script adapter."""
    raise SystemExit(main())
