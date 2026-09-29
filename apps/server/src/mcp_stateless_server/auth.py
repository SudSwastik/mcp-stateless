"""Opt-in OAuth resource-server settings for deployment integrations."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from typing import Any, cast
from urllib.parse import urlsplit

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError, PyJWTError
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings


class AuthenticationConfigurationError(ValueError):
    """Raised when the OAuth resource-server profile is incomplete or unsafe."""


class JwtJwksTokenVerifier(TokenVerifier):
    """Verify signed OAuth JWT access tokens using a configured HTTPS JWKS endpoint."""

    _ALLOWED_ALGORITHMS = (
        "RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"
    )

    def __init__(self, *, issuer_url: str, audience: str, jwks_url: str) -> None:
        _require_https("MCP_OAUTH_JWKS_URL", jwks_url)
        self._issuer_url = issuer_url
        self._audience = audience
        self._jwks = PyJWKClient(jwks_url, cache_jwk_set=True)

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return verified principal data, or None for any invalid/untrusted token."""
        try:
            claims = await asyncio.to_thread(self._decode, token)
        except (PyJWTError, PyJWKClientError, OSError, TypeError, ValueError):
            return None

        client_id = claims.get("client_id", claims.get("azp"))
        if not isinstance(client_id, str) or not client_id:
            return None
        scopes = _scopes_from_claims(claims)
        subject = claims.get("sub")
        expires_at = claims.get("exp")
        return AccessToken(
            token=token,
            client_id=client_id,
            scopes=scopes,
            expires_at=int(cast(float, expires_at)),
            resource=self._audience,
            subject=subject if isinstance(subject, str) else None,
            claims=dict(claims),
        )

    def _decode(self, token: str) -> dict[str, Any]:
        signing_key = self._jwks.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=self._ALLOWED_ALGORITHMS,
            audience=self._audience,
            issuer=self._issuer_url,
            options={"require": ["exp", "iss", "aud"]},
        )


def _scopes_from_claims(claims: Mapping[str, Any]) -> list[str]:
    scope = claims.get("scope")
    if isinstance(scope, str):
        return sorted(set(scope.split()))
    delegated_scopes = claims.get("scp")
    if isinstance(delegated_scopes, list) and all(
        isinstance(item, str) and item for item in delegated_scopes
    ):
        return sorted(set(delegated_scopes))
    return []


def _require_https(name: str, value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise AuthenticationConfigurationError(f"{name} must be an absolute HTTPS URL")


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
        _require_https(name, value)

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


def jwt_verifier_from_env(
    auth: AuthSettings | None,
    environ: Mapping[str, str] | None = None,
) -> JwtJwksTokenVerifier | None:
    """Build a strict JWKS verifier for OAuth mode; return None for local mode."""
    if auth is None:
        return None
    values = os.environ if environ is None else environ
    jwks_url = values.get("MCP_OAUTH_JWKS_URL", "").strip()
    if not jwks_url:
        raise AuthenticationConfigurationError(
            "OAuth mode requires MCP_OAUTH_JWKS_URL for JWT signature verification"
        )
    return JwtJwksTokenVerifier(
        issuer_url=str(auth.issuer_url),
        audience=str(auth.resource_server_url),
        jwks_url=jwks_url,
    )
