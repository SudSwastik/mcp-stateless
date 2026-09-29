"""Black-box fixtures for the standalone client package."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass

import pytest


@pytest.fixture
def restartable_server() -> Iterator[RestartableServer]:
    """Run a restartable server process; tests still cross only the HTTP boundary."""
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]

    server = RestartableServer(port)
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def live_server_url(restartable_server: RestartableServer) -> str:
    """Expose the subprocess endpoint to black-box client tests."""
    return restartable_server.url


@dataclass
class RestartableServer:
    port: int
    process: subprocess.Popen[str] | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"

    def start(self) -> None:
        self.process = subprocess.Popen(  # noqa: S603
            [
                sys.executable,
                "-m",
                "uvicorn",
                "mcp_stateless_server.server:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--log-level",
                "warning",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                stderr = self.process.stderr.read() if self.process.stderr is not None else ""
                pytest.fail(f"test server exited during startup: {stderr}")
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.1):
                    return
            except OSError:
                time.sleep(0.02)
        self.stop()
        pytest.fail("test server did not start within 10 seconds")

    def stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
