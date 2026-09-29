"""Black-box client for stateless MCP servers."""

from mcp_stateless_client.config import ClientConfig
from mcp_stateless_client.discovery import discover, verify
from mcp_stateless_client.primitives import (
    call_tool,
    complete_argument,
    get_prompt,
    read_resource,
)

__all__ = [
    "ClientConfig",
    "call_tool",
    "complete_argument",
    "discover",
    "get_prompt",
    "read_resource",
    "verify",
]
__version__ = "0.1.0"
