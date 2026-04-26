import threading
from typing import Any

import logger

_lock = threading.Lock()
_application: str | None = None
_socket_client: Any = None


def init(app: str, socket: Any) -> None:
    global _application, _socket_client
    with _lock:
        _application = app
        _socket_client = socket


def createCommand(action: str, options: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        application = _application
    command: dict[str, Any] = {
        "application": application,
        "action": action,
        "options": options,
    }
    return command


def sendCommand(command: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        sc = _socket_client
    response: dict[str, Any] = sc.send_message_blocking(command)
    logger.log(f"Final response: {response['status']}")
    return response
