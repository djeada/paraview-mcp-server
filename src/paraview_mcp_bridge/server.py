"""ParaView bridge TCP server — listens for JSON commands and dispatches to handlers."""

import contextlib
import json
import logging
import socket
import threading
import traceback
import uuid

from paraview_mcp_bridge import runtime

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = 9876
BUFFER_SIZE = 65536
CLIENT_SOCKET_TIMEOUT = 1.0

# A request is one JSON line. Without a ceiling a peer that never sends a
# newline grows the receive buffer until the process dies.
MAX_REQUEST_BYTES = 8 * 1024 * 1024


class RequestTooLargeError(Exception):
    """Raised when a client exceeds :data:`MAX_REQUEST_BYTES` without a newline."""


def warn_if_not_loopback(host: str) -> None:
    """Log loudly when the bridge is about to accept non-local connections."""
    if runtime.is_loopback(host):
        return
    logger.warning(
        "ParaView bridge is binding to %s, which is not a loopback address. "
        "The bridge executes arbitrary Python inside ParaView; exposing it beyond "
        "localhost gives anyone who can reach this port control of this session.",
        host,
    )


class ParaViewBridgeServer:
    """TCP server that receives JSON commands and dispatches them to a CommandHandler."""

    def __init__(self, host: str = HOST, port: int = PORT, *, token: str | None = None):
        self._host = host
        self._port = port
        self._server_socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._client_sockets: set[socket.socket] = set()
        self._client_sockets_lock = threading.Lock()
        self._token = token
        # Import here so the bridge module can be imported without paraview installed.
        from paraview_mcp_bridge.command_handler import CommandHandler

        self._handler = CommandHandler()
        self._handler_lock = threading.Lock()

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def token(self) -> str | None:
        return self._token

    def start(self):
        if self._running:
            return
        if self._token is None and not runtime.auth_disabled():
            self._token = runtime.create_token()
        warn_if_not_loopback(self._host)
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.settimeout(1.0)
        self._server_socket.bind((self._host, self._port))
        self._host, self._port = self._server_socket.getsockname()[:2]
        self._server_socket.listen(5)
        self._running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        logger.info("ParaView bridge listening on %s:%s", self._host, self._port)

    def stop(self):
        self._running = False
        if self._server_socket:
            with contextlib.suppress(OSError):
                self._server_socket.shutdown(socket.SHUT_RDWR)
            self._server_socket.close()
            self._server_socket = None
        with self._client_sockets_lock:
            client_sockets = list(self._client_sockets)
            self._client_sockets.clear()
        for client_socket in client_sockets:
            with contextlib.suppress(OSError):
                client_socket.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(OSError):
                client_socket.close()
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    def _accept_loop(self):
        while self._running:
            try:
                assert self._server_socket is not None
                conn, addr = self._server_socket.accept()
                conn.settimeout(CLIENT_SOCKET_TIMEOUT)
                self._register_client_socket(conn)
                logger.info("Client connected from %s", addr)
                threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()
            except TimeoutError:
                continue
            except OSError:
                # The listening socket is gone; nothing can be accepted again.
                if self._running:
                    logger.error("ParaView bridge accept loop stopped unexpectedly")
                    self._running = False
                break

    def _register_client_socket(self, conn: socket.socket):
        with self._client_sockets_lock:
            self._client_sockets.add(conn)

    def _unregister_client_socket(self, conn: socket.socket):
        with self._client_sockets_lock:
            self._client_sockets.discard(conn)

    def _handle_client(self, conn: socket.socket):
        buffer = b""
        try:
            while self._running:
                try:
                    data = conn.recv(BUFFER_SIZE)
                except TimeoutError:
                    continue
                except OSError:
                    break
                if not data:
                    break
                buffer += data
                if b"\n" not in buffer and len(buffer) > MAX_REQUEST_BYTES:
                    logger.warning("Dropping client: request exceeded %d bytes without a newline", MAX_REQUEST_BYTES)
                    with contextlib.suppress(OSError):
                        conn.sendall(
                            json.dumps(
                                {
                                    "id": None,
                                    "success": False,
                                    "error": f"Request exceeded {MAX_REQUEST_BYTES} bytes without a newline",
                                }
                            ).encode("utf-8")
                            + b"\n"
                        )
                    break
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
                    try:
                        conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
                    except OSError:
                        return
        finally:
            self._unregister_client_socket(conn)
            with contextlib.suppress(OSError):
                conn.close()

    def _process_request(self, request: dict) -> dict:
        if not isinstance(request, dict):
            raise TypeError("Request must be a JSON object")

        req_id = request.get("id", str(uuid.uuid4()))
        command = request.get("command")
        params = request.get("params", {})
        if not runtime.tokens_match(self._token, request.get("token")):
            logger.warning("Rejected bridge request with a missing or invalid token")
            return {
                "id": req_id,
                "success": False,
                "error": (
                    "Missing or invalid bridge token. Read it from "
                    f"{runtime.token_file_path()} or set {runtime.DISABLE_AUTH_ENV}=1 on the bridge "
                    "to turn authentication off."
                ),
            }
        if not isinstance(command, str) or not command.strip():
            return {"id": req_id, "success": False, "error": "Missing or invalid command"}
        if not isinstance(params, dict):
            return {"id": req_id, "success": False, "error": "Invalid params: expected JSON object"}
        try:
            with self._handler_lock:
                result = self._handler.handle(command, params)
            return {"id": req_id, "success": True, "result": result}
        except Exception as exc:
            logger.error("Command '%s' failed: %s\n%s", command, exc, traceback.format_exc())
            return {"id": req_id, "success": False, "error": str(exc)}
