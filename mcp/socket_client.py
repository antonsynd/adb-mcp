# MIT License
#
# Copyright (c) 2025 Mike Chambers
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Optional

import socketio

import logger

_log = logger.get_logger("socket_client")

TOKEN_FILE = Path.home() / ".adb-mcp" / "token"

# Sentinel placed in the response queue when the connection drops mid-command.
_CONNECTION_LOST = object()


def _read_auth_token() -> str:
    """Read the auth token written by the proxy at startup."""
    try:
        return TOKEN_FILE.read_text().strip()
    except OSError as e:
        raise RuntimeError(
            f"Cannot read auth token from {TOKEN_FILE}. "
            "Make sure the proxy is running first."
        ) from e


@dataclass
class _Config:
    application: Optional[str] = None
    proxy_url: Optional[str] = None
    proxy_timeout: Optional[int] = None


_config = _Config()
_config_lock = threading.Lock()


class AppError(Exception):
    pass


class _PersistentClient:
    """
    Maintains a single persistent Socket.IO connection to the proxy.

    Only one command may be in flight at a time (serialized via _send_lock).
    If the connection drops while a command is awaiting a response, that command
    fails immediately with a clear error — it is never silently requeued, since
    the command may have already executed on the plugin side.
    """

    def __init__(self) -> None:
        # Guards _sio and _connected
        self._state_lock = threading.Lock()
        # Serializes command sends so only one is in flight at a time
        self._send_lock = threading.Lock()
        self._sio: Optional[socketio.Client] = None
        self._connected: bool = False
        # Single queue: one waiter at a time (enforced by _send_lock)
        self._response_queue: Queue[Any] = Queue()

    def _is_connected(self) -> bool:
        with self._state_lock:
            return self._connected and self._sio is not None

    def _build_sio(self) -> socketio.Client:
        """Create and wire up a new socketio.Client."""
        sio = socketio.Client(logger=False, reconnection=False)

        @sio.event
        def connect() -> None:
            _log.info("Persistent connection established (sid=%s)", sio.sid)
            with self._state_lock:
                self._connected = True

        @sio.event
        def packet_response(data: Any) -> None:
            status = (
                data.get("status", "<unknown>")
                if isinstance(data, dict)
                else "<unknown>"
            )
            _log.info("Received packet_response: status=%s", status)
            _log.debug("Full response: %s", json.dumps(data, default=str))
            self._response_queue.put(data)

        @sio.event
        def disconnect() -> None:
            _log.info("Persistent connection disconnected")
            with self._state_lock:
                self._connected = False
                self._sio = None
            # Signal any blocked send() that the connection was lost.
            # Using a sentinel object avoids confusion with a real None response.
            self._response_queue.put(_CONNECTION_LOST)

        @sio.event
        def connect_error(error: Any) -> None:
            _log.error("Connection error: %s", error)
            with self._state_lock:
                self._connected = False
                self._sio = None

        return sio

    def _connect(self, proxy_url: str, application: str) -> None:
        """
        Establish a new connection. Blocks until connected or raises.
        Must be called while holding _send_lock so only one connect attempt
        runs at a time.
        """
        auth_token = _read_auth_token()
        sio = self._build_sio()
        _log.info("Connecting to proxy at %s (app=%s)...", proxy_url, application)
        try:
            sio.connect(proxy_url, transports=["websocket"], auth={"token": auth_token})
        except Exception as e:
            raise RuntimeError(
                f"Could not connect to proxy at {proxy_url} for application "
                f"'{application}'. Make sure the proxy is running. "
                f"Original error: {e}"
            ) from e
        with self._state_lock:
            self._sio = sio
        # Drain any stale sentinels from a previous disconnect
        self._drain_queue()

    def _drain_queue(self) -> None:
        """Discard any leftover items in the response queue."""
        while True:
            try:
                self._response_queue.get_nowait()
            except Empty:
                break

    def send(
        self,
        command: dict[str, Any],
        application: str,
        proxy_url: str,
        wait_timeout: int,
    ) -> dict[str, Any]:
        """
        Send a command and block until a response arrives or timeout elapses.
        Serialized: only one command in flight at a time.
        """
        with self._send_lock:
            # Connect if needed
            if not self._is_connected():
                self._connect(proxy_url, application)
            else:
                # Drain stale items (e.g. a _CONNECTION_LOST sentinel from a
                # previous disconnect that arrived between sends)
                self._drain_queue()

            action = (
                command.get("action", "<unknown>")
                if isinstance(command, dict)
                else "<unknown>"
            )
            _log.info("Sending command '%s' to application '%s'", action, application)

            with self._state_lock:
                sio = self._sio

            if sio is None:
                raise RuntimeError(
                    "Connection became unavailable just before sending. "
                    "Will reconnect on next call."
                )

            sio.emit(
                "command_packet",
                {
                    "type": "command",
                    "application": application,
                    "command": command,
                },
            )

            try:
                response = self._response_queue.get(timeout=wait_timeout)
            except Empty:
                raise RuntimeError(
                    f"Command '{action}' timed out after {wait_timeout}s. "
                    "Make sure Photoshop is running and the MCP plugin is connected."
                )

            if response is _CONNECTION_LOST:
                raise RuntimeError(
                    f"Connection lost while awaiting response for '{action}' — "
                    "the command may or may not have executed. "
                    "Reconnect and retry only if the operation is idempotent."
                )

            if response is None:
                raise RuntimeError(f"Received null response for command '{action}'.")

            if isinstance(response, dict) and response.get("status") == "FAILURE":
                raise AppError(
                    f"Error returned from {application}: {response.get('message', '<no message>')}"
                )

            return response  # type: ignore[no-any-return]


# Module-level singleton — shared across all calls in a process
_client = _PersistentClient()


def send_message_blocking(
    command: dict[str, Any], timeout: Optional[int] = None
) -> Optional[dict[str, Any]]:
    """
    Send a command to the proxy and block until the response arrives.

    Args:
        command: The command dict to send
        timeout: Max seconds to wait; falls back to the configured default

    Returns:
        The response dict from the proxy/plugin
    """
    with _config_lock:
        application = _config.application
        proxy_url = _config.proxy_url
        proxy_timeout = _config.proxy_timeout

    if not application or not proxy_url or not proxy_timeout:
        _log.error("Socket client not configured. Call configure() first.")
        return None

    wait_timeout = timeout if timeout is not None else proxy_timeout

    return _client.send(
        command=command,
        application=application,
        proxy_url=proxy_url,
        wait_timeout=wait_timeout,
    )


def configure(
    app: Optional[str] = None,
    url: Optional[str] = None,
    timeout: Optional[int] = None,
) -> None:
    with _config_lock:
        if app:
            _config.application = app
        if url:
            _config.proxy_url = url
        if timeout:
            _config.proxy_timeout = timeout

    _log.info(
        "Socket client configured: app=%s, url=%s, timeout=%s",
        _config.application,
        _config.proxy_url,
        _config.proxy_timeout,
    )
