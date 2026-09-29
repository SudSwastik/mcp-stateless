"""Validated client configuration."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, cast
from urllib.parse import urlsplit

from mcp.client.caching import CacheConfig

DEFAULT_SERVER_URL = "http://127.0.0.1:8000/mcp"
DEFAULT_PROTOCOL_VERSION = "2026-07-28"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 15.0
OutputFormat = Literal["text", "json"]
ElicitationPolicy = Literal["interactive", "accept", "decline", "cancel"]


class ConfigurationError(ValueError):
    """Raised when client configuration is invalid."""


@dataclass(frozen=True, slots=True)
class ClientConfig:
    """Connection and rendering settings for one client invocation."""

    server_url: str = DEFAULT_SERVER_URL
    protocol_version: str = DEFAULT_PROTOCOL_VERSION
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS
    output_format: OutputFormat = "text"
    response_cache: CacheConfig = field(default_factory=CacheConfig)
    elicitation_policy: ElicitationPolicy | None = None

    def __post_init__(self) -> None:
        parsed = urlsplit(self.server_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConfigurationError("MCP_SERVER_URL must be an absolute http:// or https:// URL")
        if not self.protocol_version.strip():
            raise ConfigurationError("MCP_PROTOCOL_VERSION must not be empty")
        if not math.isfinite(self.request_timeout_seconds) or self.request_timeout_seconds <= 0:
            raise ConfigurationError("MCP_REQUEST_TIMEOUT_SECONDS must be a positive number")
        if self.output_format not in {"text", "json"}:
            raise ConfigurationError("MCP_OUTPUT_FORMAT must be 'text' or 'json'")
        if self.elicitation_policy not in {None, "interactive", "accept", "decline", "cancel"}:
            raise ConfigurationError(
                "MCP_ELICITATION_POLICY must be 'interactive', 'accept', 'decline', or 'cancel'"
            )

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        server_url: str | None = None,
        protocol_version: str | None = None,
        request_timeout_seconds: float | None = None,
        output_format: str | None = None,
        elicitation_policy: str | None = None,
    ) -> ClientConfig:
        """Load environment defaults and apply explicit CLI overrides."""
        values = os.environ if environ is None else environ
        timeout_text = values.get(
            "MCP_REQUEST_TIMEOUT_SECONDS", str(DEFAULT_REQUEST_TIMEOUT_SECONDS)
        )
        try:
            environment_timeout = float(timeout_text)
        except ValueError as exc:
            raise ConfigurationError(
                "MCP_REQUEST_TIMEOUT_SECONDS must be a positive number"
            ) from exc

        chosen_output = output_format or values.get("MCP_OUTPUT_FORMAT", "text")
        return cls(
            server_url=server_url or values.get("MCP_SERVER_URL", DEFAULT_SERVER_URL),
            protocol_version=protocol_version
            or values.get("MCP_PROTOCOL_VERSION", DEFAULT_PROTOCOL_VERSION),
            request_timeout_seconds=(
                request_timeout_seconds
                if request_timeout_seconds is not None
                else environment_timeout
            ),
            output_format=cast(OutputFormat, chosen_output),
            elicitation_policy=cast(
                ElicitationPolicy,
                elicitation_policy or values.get("MCP_ELICITATION_POLICY", "interactive"),
            ),
        )
