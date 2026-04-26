import threading
import logger

_lock = threading.Lock()
_application = None
_socket_client = None

def init(app, socket):
    global _application, _socket_client
    with _lock:
        _application = app
        _socket_client = socket


def createCommand(action: str, options: dict) -> dict:
    with _lock:
        application = _application
    command = {
        "application": application,
        "action": action,
        "options": options,
    }
    return command


def sendCommand(command: dict):
    with _lock:
        sc = _socket_client
    response = sc.send_message_blocking(command)
    logger.log(f"Final response: {response['status']}")
    return response