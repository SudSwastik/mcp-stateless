"""Opt-in OAuth resource-server settings for deployment integrations."""

from __future__ import annotations

import os
from collections.abc import Mapping
from urllib.parse import urlsplit

from mcp.server.auth.settings import AuthSettings


class AuthenticationConfigurationError(ValueError):
    """Raised when the OAuth resource-server profile is incomplete or unsafe."""


def auth_settings_from_env(
    environ: Mapping[str, str] | None = None,
) -> AuthSettings | None:
    """Load optional OAuth resource-server settings; local mode stays unauthenticated."""
    values = os.environ if environ is None else environ
    mode = values.get("MCP_AUTH_MODE", "none").strip().casefold()
    if mode == "none":
        return None
    if mode != "oauth":
        raise AuthenticationConfigurationError("MCP_AUTH_MODE must be 'none' or 'oauth'")

    issuer_url = values.get("MCP_OAUTH_ISSUER_URL", "").strip()
    resource_server_url = values.get("MCP_PUBLIC_BASE_URL", "").strip()
    if not issuer_url or not resource_server_url:
        raise AuthenticationConfigurationError(
            "OAuth mode requires MCP_OAUTH_ISSUER_URL and MCP_PUBLIC_BASE_URL"
        )
    for name, value in (
        ("MCP_OAUTH_ISSUER_URL", issuer_url),
        ("MCP_PUBLIC_BASE_URL", resource_server_url),
    ):
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise AuthenticationConfigurationError(f"{name} must be an absolute HTTPS URL")

    scopes = values.get("MCP_REQUIRED_SCOPES", "").split()
    try:
        return AuthSettings.model_validate(
            {
                "issuer_url": issuer_url,
                "resource_server_url": resource_server_url,
                "required_scopes": scopes or None,
                "validate_token_resource": True,
            }
        )
    except ValueError as exc:
        raise AuthenticationConfigurationError(f"Invalid OAuth settings: {exc}") from exc
