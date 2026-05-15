"""
Auto-launch and manage the adb-mcp WebSocket proxy as a subprocess.

The proxy must be running before the MCP server can communicate with
Photoshop.  This module starts the proxy (if not already listening),
waits for it to be ready, and tears it down when the MCP server exits.
"""

import atexit
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import logger

_log = logger.get_logger("proxy_manager")

_PROXY_DIR = Path(__file__).resolve().parent.parent / "adb-proxy-socket"
_PROXY_SCRIPT = _PROXY_DIR / "proxy.js"

_proxy_process: subprocess.Popen | None = None


def _port_from_url(url: str) -> int:
    """Extract the port number from a URL like 'http://localhost:3001'."""
    try:
        return int(url.rsplit(":", 1)[-1].strip("/"))
    except (ValueError, IndexError):
        return 3001


def _is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def _cleanup() -> None:
    global _proxy_process
    if _proxy_process is not None and _proxy_process.poll() is None:
        _log.info("Shutting down proxy (pid=%d)", _proxy_process.pid)
        _proxy_process.terminate()
        try:
            _proxy_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _proxy_process.kill()
        _proxy_process = None


def ensure_proxy(proxy_url: str, startup_timeout: float = 10.0) -> None:
    """
    Ensure the proxy is running.  If it's already listening on the
    expected port, do nothing.  Otherwise, spawn it as a child process
    and wait for it to accept connections.
    """
    global _proxy_process

    port = _port_from_url(proxy_url)

    if _is_port_open(port):
        _log.info("Proxy already listening on port %d — skipping launch", port)
        return

    if not _PROXY_SCRIPT.exists():
        _log.error("Proxy script not found at %s", _PROXY_SCRIPT)
        raise FileNotFoundError(f"Proxy script not found: {_PROXY_SCRIPT}")

    env = os.environ.copy()
    env["ADB_MCP_PROXY_PORT"] = str(port)

    _log.info("Starting proxy: node %s (port %d)", _PROXY_SCRIPT, port)
    _proxy_process = subprocess.Popen(
        ["node", str(_PROXY_SCRIPT)],
        cwd=str(_PROXY_DIR),
        env=env,
        stdout=sys.stderr,
        stderr=sys.stderr,
    )

    atexit.register(_cleanup)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    deadline = time.monotonic() + startup_timeout
    while time.monotonic() < deadline:
        if _proxy_process.poll() is not None:
            raise RuntimeError(
                f"Proxy exited immediately with code {_proxy_process.returncode}"
            )
        if _is_port_open(port):
            _log.info("Proxy is ready on port %d (pid=%d)", port, _proxy_process.pid)
            return
        time.sleep(0.2)

    _cleanup()
    raise RuntimeError(
        f"Proxy did not start within {startup_timeout}s on port {port}"
    )
