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

import socketio
import threading
import json
from dataclasses import dataclass
from queue import Queue
from pathlib import Path
from typing import Optional
import logger

_log = logger.get_logger("socket_client")

TOKEN_FILE = Path.home() / ".adb-mcp" / "token"

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

def send_message_blocking(command, timeout=None):
    """
    Blocking function that connects to a Socket.IO server, sends a message,
    waits for a response, then disconnects.
    
    Args:
        command: The command to send
        timeout (int): Maximum time to wait for response in seconds
        
    Returns:
        dict: The response received from the server, or None if no response
    """
    # Read config atomically under lock
    with _config_lock:
        application = _config.application
        proxy_url = _config.proxy_url
        proxy_timeout = _config.proxy_timeout

    # Check if configuration is set
    if not application or not proxy_url or not proxy_timeout:
        _log.error("Socket client not configured. Call configure() first.")
        return None
    
    # Use provided timeout or default
    wait_timeout = timeout if timeout is not None else proxy_timeout
    
    # Create a standard (non-async) SocketIO client with WebSocket transport only
    sio = socketio.Client(logger=False)
    
    # Read auth token
    auth_token = _read_auth_token()
    
    # Use a queue to get the response from the event handler
    response_queue = Queue()
    
    connection_failed = [False]         

    @sio.event
    def connect():
        _log.debug("Connected to server with session ID: %s", sio.sid)
        
        # Send the command
        action = command.get("action", "<unknown>") if isinstance(command, dict) else "<unknown>"
        _log.info("Sending command '%s' to application '%s'", action, application)
        sio.emit('command_packet', {
            'type': "command",
            'application': application,
            'command': command
        })
    
    @sio.event
    def packet_response(data):
        status = data.get("status", "<unknown>") if isinstance(data, dict) else "<unknown>"
        action = command.get("action", "<unknown>") if isinstance(command, dict) else "<unknown>"
        _log.info("Received response for command '%s': status=%s", action, status)
        _log.debug("Full response: %s", data)
        response_queue.put(data)
        # Disconnect after receiving the response
        sio.disconnect()
    
    @sio.event
    def disconnect():
        _log.debug("Disconnected from server")
        # If we disconnect without response, put None in the queue
        if response_queue.empty():
            response_queue.put(None)
    
    @sio.event
    def connect_error(error):
        _log.error("Connection error: %s", error)
        connection_failed[0] = True
        response_queue.put(None)
    
    # Connect in a separate thread to avoid blocking the main thread during connection
    def connect_and_wait():
        try:
            sio.connect(proxy_url, transports=['websocket'], auth={"token": auth_token})
            # Keep the client running until disconnect is called
            sio.wait()
        except Exception as e:
            _log.error("Error in socket thread: %s", e)
            connection_failed[0] = True
            if response_queue.empty():
                response_queue.put(None)
            if sio.connected:
                sio.disconnect()
    
    # Start the client in a separate thread
    client_thread = threading.Thread(target=connect_and_wait)
    client_thread.daemon = True
    client_thread.start()
    
    try:
        # Wait for a response or timeout
        _log.debug("Waiting for response (timeout=%ss)...", wait_timeout)
        response = response_queue.get(timeout=wait_timeout)

        if connection_failed[0]:
            raise RuntimeError(f"Error: Could not connect to {application} command proxy server. Make sure that the proxy server is running listening on the correct url {proxy_url}.")

        if response:
            _log.debug("Response received (JSON): %s", json.dumps(response, default=str))

            if response["status"] == "FAILURE":
                raise AppError(f"Error returned from {application}: {response['message']}")
            
        return response
    except AppError:
        raise
    except Exception as e:
        _log.error("Error waiting for response: %s", e)
        if sio.connected:
            sio.disconnect()
  
        raise RuntimeError(f"Error: Could not connect to {application}. Connection Timed Out. Make sure that {application} is running and that the MCP Plugin is connected. Original error: {e}")
    finally:
        # Make sure client is disconnected
        if sio.connected:
            sio.disconnect()
        # Wait for the thread to finish (should be quick after disconnect)
        client_thread.join(timeout=5)
        if client_thread.is_alive():
            _log.warning("Socket client thread still alive after join timeout")

class AppError(Exception):
    pass

def configure(app=None, url=None, timeout=None):
    with _config_lock:
        if app:
            _config.application = app
        if url:
            _config.proxy_url = url
        if timeout:
            _config.proxy_timeout = timeout

    _log.info("Socket client configured: app=%s, url=%s, timeout=%s", _config.application, _config.proxy_url, _config.proxy_timeout)