"""Shared server-test fixtures."""

import pytest
from mcp.server import MCPServer
from mcp_stateless_server.server import create_server


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def server() -> MCPServer:
    return create_server()
