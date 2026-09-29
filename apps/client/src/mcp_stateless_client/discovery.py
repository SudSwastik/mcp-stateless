"""Raw HTTP discovery and stateless transport verification."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, ClassVar, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from httpx2 import TransportError as HttpTransportError
from mcp.client.auth import OAuthFlowError
from mcp_types import (
    HEADER_MISMATCH,
    SERVER_INFO_META_KEY,
    DiscoverResult,
    Implementation,
)
from pydantic import ValidationError

from mcp_stateless_client.config import ClientConfig
from mcp_stateless_client.oauth import oauth_http_client

CLIENT_NAME = "mcp-stateless-client"
CLIENT_VERSION = "0.1.0"


class ClientError(RuntimeError):
    """Base error reported by the compatibility client."""

    category: ClassVar[str] = "client"


class TransportError(ClientError):
    """The endpoint could not be reached or returned an unreadable response."""

    category = "transport"


class ProtocolError(ClientError):
    """The peer returned an invalid or unsuccessful MCP response."""

    category = "protocol"


@dataclass(frozen=True, slots=True)
class RawHttpResponse:
    """HTTP response details needed for wire-level checks."""

    status: int
    headers: Mapping[str, str]
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class DiscoveryObservation:
    """Validated discovery result plus its wire envelope."""

    request_id: int
    result: DiscoverResult
    server_info: Implementation | None
    status: int
    headers: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "status": self.status,
            "headers": dict(self.headers),
            "serverInfo": (
                self.server_info.model_dump(by_alias=True, mode="json", exclude_none=True)
                if self.server_info is not None
                else None
            ),
            "discovery": self.result.model_dump(
                by_alias=True, mode="json", exclude_none=True
            ),
        }


@dataclass(frozen=True, slots=True)
class VerificationCheck:
    """One named compatibility assertion."""

    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, str | bool]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class VerificationReport:
    """Machine-readable result of the discovery compatibility checks."""

    server_url: str
    protocol_version: str
    checks: tuple[VerificationCheck, ...]
    discovery: DiscoveryObservation

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "serverUrl": self.server_url,
            "protocolVersion": self.protocol_version,
            "passed": self.passed,
            "checks": [check.to_dict() for check in self.checks],
            "discovery": self.discovery.to_dict(),
        }


def _discover_request(config: ClientConfig, request_id: int) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "server/discover",
        "params": {
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": config.protocol_version,
                "io.modelcontextprotocol/clientCapabilities": {},
                "io.modelcontextprotocol/clientInfo": {
                    "name": CLIENT_NAME,
                    "version": CLIENT_VERSION,
                },
            }
        },
    }


def _decode_payload(data: bytes, url: str) -> Mapping[str, Any]:
    try:
        decoded = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransportError(f"{url} returned a response that is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise ProtocolError("JSON-RPC response must be an object")
    return cast(dict[str, Any], decoded)


def _post_json(
    config: ClientConfig,
    payload: Mapping[str, Any],
    *,
    method_header: str,
) -> RawHttpResponse:
    body = json.dumps(payload, separators=(",", ":")).encode()
    if config.oauth is not None:
        try:
            return asyncio.run(
                _post_json_oauth(config, body, method_header=method_header)
            )
        except OAuthFlowError as exc:
            raise ProtocolError("OAuth client-credentials authorization failed") from exc
        except (HttpTransportError, TimeoutError, OSError) as exc:
            raise TransportError(f"Could not connect to {config.server_url}: {exc}") from exc
    request = Request(
        config.server_url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json, text/event-stream",
            "Connection": "close",
            "Content-Type": "application/json",
            "Mcp-Method": method_header,
            "MCP-Protocol-Version": config.protocol_version,
        },
    )
    try:
        with urlopen(request, timeout=config.request_timeout_seconds) as response:
            status = response.status
            headers = {key.casefold(): value for key, value in response.headers.items()}
            response_body = response.read()
    except HTTPError as exc:
        status = exc.code
        headers = {key.casefold(): value for key, value in exc.headers.items()}
        response_body = exc.read()
    except (URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise TransportError(f"Could not connect to {config.server_url}: {reason}") from exc

    return RawHttpResponse(
        status=status,
        headers=headers,
        payload=_decode_payload(response_body, config.server_url),
    )


async def _post_json_oauth(
    config: ClientConfig,
    body: bytes,
    *,
    method_header: str,
) -> RawHttpResponse:
    if config.oauth is None:
        raise AssertionError("OAuth request requires configured client credentials")
    async with oauth_http_client(
        config.server_url,
        config.oauth,
        config.request_timeout_seconds,
    ) as client:
        response = await client.post(
            config.server_url,
            content=body,
            headers={
                "Accept": "application/json, text/event-stream",
                "Connection": "close",
                "Content-Type": "application/json",
                "Mcp-Method": method_header,
                "MCP-Protocol-Version": config.protocol_version,
            },
        )
    return RawHttpResponse(
        status=response.status_code,
        headers={key.casefold(): value for key, value in response.headers.items()},
        payload=_decode_payload(response.content, config.server_url),
    )


def _error_description(response: RawHttpResponse) -> str | None:
    error = response.payload.get("error")
    if not isinstance(error, dict):
        if 200 <= response.status < 300:
            return None
        return f"HTTP {response.status} without a JSON-RPC error"

    code = error.get("code")
    message = error.get("message", "Unknown JSON-RPC error")
    description = f"JSON-RPC error {code}: {message}"
    data = error.get("data")
    if isinstance(data, dict):
        requested = data.get("requested")
        supported = data.get("supported")
        if requested is not None or supported is not None:
            description += f" (requested={requested!r}, supported={supported!r})"
    return description


def _server_info(result: DiscoverResult) -> Implementation | None:
    if result.meta is None:
        return None
    raw = result.meta.get(SERVER_INFO_META_KEY)
    if raw is None:
        return None
    try:
        return Implementation.model_validate(raw)
    except ValidationError as exc:
        raise ProtocolError("Discovery returned invalid server identity metadata") from exc


def discover(config: ClientConfig, *, request_id: int = 1) -> DiscoveryObservation:
    """Send and validate one pinned modern discovery request."""
    response = _post_json(
        config,
        _discover_request(config, request_id),
        method_header="server/discover",
    )
    if (description := _error_description(response)) is not None:
        raise ProtocolError(description)
    if response.payload.get("jsonrpc") != "2.0":
        raise ProtocolError("Discovery response has an invalid JSON-RPC version")
    if response.payload.get("id") != request_id:
        raise ProtocolError(
            f"Discovery response ID mismatch: expected {request_id!r}, "
            f"received {response.payload.get('id')!r}"
        )
    raw_result = response.payload.get("result")
    try:
        result = DiscoverResult.model_validate(raw_result)
    except ValidationError as exc:
        raise ProtocolError(f"Discovery result does not match the MCP schema: {exc}") from exc
    if config.protocol_version not in result.supported_versions:
        raise ProtocolError(
            f"Server does not support pinned protocol {config.protocol_version!r}; "
            f"advertised {result.supported_versions!r}"
        )
    return DiscoveryObservation(
        request_id=request_id,
        result=result,
        server_info=_server_info(result),
        status=response.status,
        headers=response.headers,
    )


def _routing_mismatch_check(config: ClientConfig) -> VerificationCheck:
    response = _post_json(
        config,
        _discover_request(config, 3),
        method_header="tools/list",
    )
    error = response.payload.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    passed = not 200 <= response.status < 300 and code == HEADER_MISMATCH
    return VerificationCheck(
        name="header_body_routing",
        passed=passed,
        detail=(
            f"mismatch rejected with HTTP {response.status} and JSON-RPC {code}"
            if passed
            else (
                f"expected HTTP error and JSON-RPC {HEADER_MISMATCH}; "
                f"got HTTP {response.status}, {code}"
            )
        ),
    )


def _concurrent_request_check(config: ClientConfig) -> VerificationCheck:
    request_ids = (10, 11, 12, 13)
    with ThreadPoolExecutor(max_workers=len(request_ids)) as executor:
        observations = tuple(
            executor.map(lambda request_id: discover(config, request_id=request_id), request_ids)
        )

    correlated = tuple(observation.request_id for observation in observations) == request_ids
    stateless = all("mcp-session-id" not in observation.headers for observation in observations)
    passed = correlated and stateless
    return VerificationCheck(
        name="concurrent_stateless_requests",
        passed=passed,
        detail=(
            "four concurrent requests preserved their IDs without protocol sessions"
            if passed
            else "concurrent requests lost correlation or returned protocol session state"
        ),
    )


def verify(config: ClientConfig) -> VerificationReport:
    """Run non-mutating wire checks against independent HTTP requests."""
    first = discover(config, request_id=1)
    second = discover(config, request_id=2)
    first_session = first.headers.get("mcp-session-id")
    second_session = second.headers.get("mcp-session-id")
    capability_names = sorted(
        key
        for key, value in first.result.capabilities.model_dump(exclude_none=True).items()
        if value is not None
    )
    identity = first.server_info
    checks = (
        VerificationCheck(
            name="jsonrpc_correlation",
            passed=first.request_id == 1 and second.request_id == 2,
            detail="independent responses preserved request IDs 1 and 2",
        ),
        VerificationCheck(
            name="protocol_version",
            passed=config.protocol_version in first.result.supported_versions,
            detail=f"server advertises {config.protocol_version}",
        ),
        VerificationCheck(
            name="server_identity",
            passed=identity is not None,
            detail=(
                f"{identity.name} {identity.version}"
                if identity is not None
                else "server identity metadata is missing"
            ),
        ),
        VerificationCheck(
            name="capabilities",
            passed=bool(capability_names),
            detail=(
                ", ".join(capability_names)
                if capability_names
                else "server advertised no capabilities"
            ),
        ),
        VerificationCheck(
            name="stateless_transport",
            passed=first_session is None and second_session is None,
            detail=(
                "two Connection: close requests succeeded without Mcp-Session-Id"
                if first_session is None and second_session is None
                else "server returned protocol session state"
            ),
        ),
        _routing_mismatch_check(config),
        _concurrent_request_check(config),
    )
    return VerificationReport(
        server_url=config.server_url,
        protocol_version=config.protocol_version,
        checks=checks,
        discovery=first,
    )
