"""Black-box client for stateless MCP servers."""

from mcp_stateless_client.config import ClientConfig
from mcp_stateless_client.discovery import discover, verify

__all__ = ["ClientConfig", "discover", "verify"]
__version__ = "0.1.0"
