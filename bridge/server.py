"""ParaView bridge TCP server — listens for JSON commands and dispatches to handlers."""

import json
import logging
import queue
import socket
import threading
import traceback
import uuid
from typing import Any

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = 9876
BUFFER_SIZE = 65536


class ParaViewBridgeServer:
    """TCP server that receives JSON commands and dispatches them to a CommandHandler."""

    def __init__(self, host: str = HOST, port: int = PORT):
        self._host = host
        self._port = port
        self._server_socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        # Import here so the bridge module can be imported without paraview installed.
        from bridge.command_handler import CommandHandler
        self._handler = CommandHandler()
        self._request_queue: queue.Queue[dict[str, Any]] = queue.Queue()

    def start(self):
        if self._running:
            return
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.settimeout(1.0)
        self._server_socket.bind((self._host, self._port))
        self._server_socket.listen(5)
        self._running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        logger.info("ParaView bridge listening on %s:%s", self._host, self._port)

    def stop(self):
        self._running = False
        if self._server_socket:
            self._server_socket.close()
            self._server_socket = None
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    def _accept_loop(self):
        while self._running:
            try:
                conn, addr = self._server_socket.accept()
                logger.info("Client connected from %s", addr)
                threading.Thread(
                    target=self._handle_client, args=(conn,), daemon=True
                ).start()
            except socket.timeout:
                continue
            except OSError:
                break

    def _handle_client(self, conn: socket.socket):
        buffer = b""
        try:
            while self._running:
                data = conn.recv(BUFFER_SIZE)
                if not data:
                    break
                buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        request = json.loads(line.decode("utf-8"))
                        response = self._process_request(request)
                    except Exception as exc:
                        response = {
                            "id": None,
                            "success": False,
                            "error": str(exc),
                        }
                    conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
        finally:
            conn.close()

    def _process_request(self, request: dict) -> dict:
        req_id = request.get("id", str(uuid.uuid4()))
        command = request.get("command", "")
        params = request.get("params", {})
        try:
            result = self._handler.handle(command, params)
            return {"id": req_id, "success": True, "result": result}
        except Exception as exc:
            logger.error("Command '%s' failed: %s\n%s", command, exc, traceback.format_exc())
            return {"id": req_id, "success": False, "error": str(exc)}
