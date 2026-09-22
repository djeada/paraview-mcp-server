"""Helpers for starting the bridge from an already-open ParaView GUI session."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import select
import socket
import traceback
import uuid
from dataclasses import dataclass
from typing import Any

from paraview_mcp_bridge import runtime
from paraview_mcp_bridge.server import BUFFER_SIZE, HOST, MAX_REQUEST_BYTES, PORT, warn_if_not_loopback

logger = logging.getLogger(__name__)

# Requests handled per GUI timer tick. Draining the whole backlog in one tick
# would stall ParaView's event loop; leaving the backlog untouched would strand
# it (see poll()), so the budget is a compromise.
MAX_REQUESTS_PER_POLL = 8


@dataclass
class _ClientState:
    sock: socket.socket
    buffer: bytes = b""


class ParaViewGuiBridgeServer:
    """Nonblocking TCP bridge polled from ParaView's GUI event loop."""

    def __init__(self, host: str = HOST, port: int = PORT, poll_interval_ms: int = 50, *, token: str | None = None):
        self._host = host
        self._port = port
        self._token = token
        self._poll_interval_ms = poll_interval_ms
        self._server_socket: socket.socket | None = None
        self._clients: dict[socket.socket, _ClientState] = {}
        self._running = False
        self._interactor: Any | None = None
        self._observer_id: int | None = None
        self._timer_id: int | None = None
        # Import here so this module can be imported without ParaView installed.
        from paraview_mcp_bridge.command_handler import CommandHandler

        self._handler = CommandHandler()

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

    def start(self) -> None:
        if self._running:
            return
        if self._token is None and not runtime.auth_disabled():
            self._token = runtime.create_token()
        warn_if_not_loopback(self._host)
        self._interactor = self._get_render_window_interactor()
        if not callable(getattr(self._interactor, "AddObserver", None)):
            raise RuntimeError("ParaView render window interactor does not support VTK observers")
        if not callable(getattr(self._interactor, "CreateRepeatingTimer", None)):
            raise RuntimeError("ParaView render window interactor does not support repeating timers")

        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.setblocking(False)
        self._server_socket.bind((self._host, self._port))
        self._host, self._port = self._server_socket.getsockname()[:2]
        self._server_socket.listen(5)

        self._observer_id = self._interactor.AddObserver("TimerEvent", self._on_timer)
        self._timer_id = self._interactor.CreateRepeatingTimer(self._poll_interval_ms)
        os.environ["PARAVIEW_MCP_GUI_BRIDGE"] = "1"
        self._running = True
        logger.info("ParaView GUI bridge listening on %s:%s", self._host, self._port)

    def stop(self) -> None:
        self._running = False
        if self._interactor is not None and self._timer_id is not None:
            destroy_timer = getattr(self._interactor, "DestroyTimer", None)
            if callable(destroy_timer):
                with contextlib.suppress(Exception):
                    destroy_timer(self._timer_id)
        if self._interactor is not None and self._observer_id is not None:
            remove_observer = getattr(self._interactor, "RemoveObserver", None)
            if callable(remove_observer):
                with contextlib.suppress(Exception):
                    remove_observer(self._observer_id)
        self._timer_id = None
        self._observer_id = None
        self._interactor = None
        os.environ.pop("PARAVIEW_MCP_GUI_BRIDGE", None)

        for client in list(self._clients):
            self._close_client(client)
        if self._server_socket is not None:
            with contextlib.suppress(OSError):
                self._server_socket.close()
            self._server_socket = None

    def _on_timer(self, _obj: Any, _event: str) -> None:
        self.poll()

    def poll(self) -> None:
        """Process pending socket work without blocking the GUI event loop."""
        if not self._running or self._server_socket is None:
            return
        sockets = [self._server_socket, *self._clients]
        try:
            readable, _, errored = select.select(sockets, [], sockets, 0)
        except OSError:
            return

        for sock in errored:
            if sock is self._server_socket:
                logger.error("ParaView GUI bridge server socket failed")
                self.stop()
                return
            self._close_client(sock)

        for sock in readable:
            if sock is self._server_socket:
                self._accept_ready_clients()
            else:
                self._receive_into_buffer(sock)

        self._process_buffered_requests()

    def _accept_ready_clients(self) -> None:
        if self._server_socket is None:
            return
        while True:
            try:
                conn, addr = self._server_socket.accept()
            except BlockingIOError:
                break
            except OSError:
                break
            conn.setblocking(False)
            self._clients[conn] = _ClientState(conn)
            logger.info("Client connected from %s", addr)

    def _receive_into_buffer(self, sock: socket.socket) -> None:
        """Move readable bytes into the client's buffer without handling them."""
        state = self._clients.get(sock)
        if state is None:
            return
        try:
            data = sock.recv(BUFFER_SIZE)
        except BlockingIOError:
            return
        except OSError:
            self._close_client(sock)
            return
        if not data:
            self._close_client(sock)
            return

        state.buffer += data
        if b"\n" not in state.buffer and len(state.buffer) > MAX_REQUEST_BYTES:
            logger.warning("Dropping client: request exceeded %d bytes without a newline", MAX_REQUEST_BYTES)
            self._send_response(
                sock,
                {
                    "id": None,
                    "success": False,
                    "error": f"Request exceeded {MAX_REQUEST_BYTES} bytes without a newline",
                },
            )
            self._close_client(sock)

    def _process_buffered_requests(self) -> None:
        """Handle complete requests already sitting in client buffers.

        select() only reports *kernel* readability, so anything already copied
        into a client buffer is invisible to it. Requests that arrived in the
        same read as an earlier one must therefore be drained from here, or a
        client that pipelines two requests never gets a second response.
        """
        budget = MAX_REQUESTS_PER_POLL
        for sock in list(self._clients):
            while budget > 0:
                state = self._clients.get(sock)
                if state is None or b"\n" not in state.buffer:
                    break
                line, state.buffer = state.buffer.split(b"\n", 1)
                if not line.strip():
                    continue
                budget -= 1
                try:
                    request = json.loads(line.decode("utf-8"))
                    response = self._process_request(request)
                except Exception as exc:
                    response = {"id": None, "success": False, "error": str(exc)}
                self._send_response(sock, response)
            if budget <= 0:
                break

    def has_pending_requests(self) -> bool:
        """Whether any client buffer still holds an unhandled request."""
        return any(b"\n" in state.buffer for state in self._clients.values())

    def _send_response(self, sock: socket.socket, response: dict[str, Any]) -> None:
        try:
            sock.sendall((json.dumps(response) + "\n").encode("utf-8"))
        except OSError:
            self._close_client(sock)

    def _close_client(self, sock: socket.socket) -> None:
        self._clients.pop(sock, None)
        with contextlib.suppress(OSError):
            sock.close()

    def _process_request(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise TypeError("Request must be a JSON object")

        req_id = request.get("id", str(uuid.uuid4()))
        command = request.get("command")
        params = request.get("params", {})
        if not runtime.tokens_match(self._token, request.get("token")):
            logger.warning("Rejected GUI bridge request with a missing or invalid token")
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
            result = self._handler.handle(command, params)
            return {"id": req_id, "success": True, "result": result}
        except Exception as exc:
            logger.error("Command '%s' failed: %s\n%s", command, exc, traceback.format_exc())
            return {"id": req_id, "success": False, "error": str(exc)}

    @staticmethod
    def _get_render_window_interactor() -> Any:
        import paraview  # noqa: PLC0415
        import paraview.simple as pvs  # noqa: PLC0415

        if not getattr(paraview, "fromGUI", False):
            raise RuntimeError(
                "The live GUI bridge must be started from ParaView's Python Shell with Run Script. "
                "Starting it with 'paraview --script' runs too early in ParaView startup and is not stable."
            )

        view = pvs.GetActiveViewOrCreate("RenderView")
        render_window = view.GetRenderWindow()
        interactor = render_window.GetInteractor()
        if interactor is None:
            raise RuntimeError("ParaView render window interactor is not available")
        return interactor


_SERVER: ParaViewGuiBridgeServer | None = None


def start_gui_bridge(host: str = HOST, port: int = PORT) -> dict[str, Any]:
    """Start the bridge inside the current ParaView GUI process."""
    global _SERVER
    if _SERVER is not None and _SERVER.is_running:
        return {
            "host": _SERVER.host,
            "port": _SERVER.port,
            "running": True,
            "already_running": True,
            "token_file": str(runtime.token_file_path()) if _SERVER.token else None,
        }

    server = ParaViewGuiBridgeServer(host=host, port=port)
    server.start()
    _SERVER = server
    return {
        "host": server.host,
        "port": server.port,
        "running": True,
        "already_running": False,
        "token_file": str(runtime.token_file_path()) if server.token else None,
    }


def stop_gui_bridge() -> dict[str, Any]:
    """Stop the bridge started by :func:`start_gui_bridge`."""
    global _SERVER
    if _SERVER is None:
        return {"running": False, "stopped": False}

    host = _SERVER.host
    port = _SERVER.port
    _SERVER.stop()
    _SERVER = None
    return {"host": host, "port": port, "running": False, "stopped": True}


def gui_bridge_status() -> dict[str, Any]:
    """Return the current GUI bridge status."""
    if _SERVER is None or not _SERVER.is_running:
        return {"running": False}
    return {"host": _SERVER.host, "port": _SERVER.port, "running": True}
