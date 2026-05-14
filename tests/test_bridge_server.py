"""Tests for the concrete bridge TCP server implementation."""

from __future__ import annotations

import json
import socket
import time
from unittest.mock import MagicMock, patch

from bridge.server import ParaViewBridgeServer


def _server_port(server: ParaViewBridgeServer) -> int:
    assert server._server_socket is not None
    return server._server_socket.getsockname()[1]


def _read_response(sock: socket.socket, timeout: float = 2.0) -> dict:
    buffer = b""
    sock.settimeout(timeout)
    while b"\n" not in buffer:
        chunk = sock.recv(65536)
        if not chunk:
            raise ConnectionError("Connection closed before response")
        buffer += chunk
    line = buffer.split(b"\n", 1)[0]
    return json.loads(line.decode("utf-8"))


class TestParaViewBridgeServer:
    def _make_server(self):
        handler = MagicMock()
        handler.handle.return_value = {"ok": True}
        patcher = patch("bridge.command_handler.CommandHandler", return_value=handler)
        command_handler_cls = patcher.start()
        self.addCleanup = getattr(self, "addCleanup", None)
        server = ParaViewBridgeServer(port=0)
        patcher.stop()
        assert command_handler_cls.called
        return server, handler

    def test_process_request_success(self):
        with patch("bridge.command_handler.CommandHandler") as command_handler_cls:
            handler = MagicMock()
            handler.handle.return_value = {"ok": True}
            command_handler_cls.return_value = handler
            server = ParaViewBridgeServer(port=0)

        response = server._process_request({"id": "abc", "command": "scene.get_info", "params": {}})

        assert response == {"id": "abc", "success": True, "result": {"ok": True}}
        handler.handle.assert_called_once_with("scene.get_info", {})

    def test_process_request_rejects_invalid_command(self):
        with patch("bridge.command_handler.CommandHandler") as command_handler_cls:
            command_handler_cls.return_value = MagicMock()
            server = ParaViewBridgeServer(port=0)

        response = server._process_request({"id": "abc", "command": None, "params": {}})

        assert response == {"id": "abc", "success": False, "error": "Missing or invalid command"}

    def test_process_request_rejects_non_object_params(self):
        with patch("bridge.command_handler.CommandHandler") as command_handler_cls:
            handler = MagicMock()
            command_handler_cls.return_value = handler
            server = ParaViewBridgeServer(port=0)

        response = server._process_request({"id": "abc", "command": "scene.get_info", "params": []})

        assert response == {"id": "abc", "success": False, "error": "Invalid params: expected JSON object"}
        handler.handle.assert_not_called()

    def test_process_request_requires_json_object(self):
        with patch("bridge.command_handler.CommandHandler") as command_handler_cls:
            command_handler_cls.return_value = MagicMock()
            server = ParaViewBridgeServer(port=0)

        try:
            server._process_request(["not", "an", "object"])  # type: ignore[arg-type]
        except TypeError as exc:
            assert "JSON object" in str(exc)
        else:
            raise AssertionError("Expected TypeError for non-object request")

    def test_socket_server_roundtrip_success(self):
        with patch("bridge.command_handler.CommandHandler") as command_handler_cls:
            handler = MagicMock()
            handler.handle.return_value = {"source_count": 1}
            command_handler_cls.return_value = handler
            server = ParaViewBridgeServer(port=0)

        server.start()
        try:
            with socket.create_connection(("127.0.0.1", _server_port(server)), timeout=2.0) as sock:
                sock.sendall(b'{"id":"abc","command":"scene.get_info","params":{}}\n')
                response = _read_response(sock)
        finally:
            server.stop()

        assert response == {"id": "abc", "success": True, "result": {"source_count": 1}}
        handler.handle.assert_called_once_with("scene.get_info", {})

    def test_socket_server_rejects_malformed_json(self):
        with patch("bridge.command_handler.CommandHandler") as command_handler_cls:
            command_handler_cls.return_value = MagicMock()
            server = ParaViewBridgeServer(port=0)

        server.start()
        try:
            with socket.create_connection(("127.0.0.1", _server_port(server)), timeout=2.0) as sock:
                sock.sendall(b'{"id":"abc","command":"scene.get_info"\n')
                response = _read_response(sock)
        finally:
            server.stop()

        assert response["id"] is None
        assert response["success"] is False

    def test_socket_server_rejects_invalid_params_shape(self):
        with patch("bridge.command_handler.CommandHandler") as command_handler_cls:
            handler = MagicMock()
            command_handler_cls.return_value = handler
            server = ParaViewBridgeServer(port=0)

        server.start()
        try:
            with socket.create_connection(("127.0.0.1", _server_port(server)), timeout=2.0) as sock:
                sock.sendall(b'{"id":"abc","command":"scene.get_info","params":[]}\n')
                response = _read_response(sock)
        finally:
            server.stop()

        assert response == {"id": "abc", "success": False, "error": "Invalid params: expected JSON object"}
        handler.handle.assert_not_called()

    def test_stop_closes_active_client_connections(self):
        with patch("bridge.command_handler.CommandHandler") as command_handler_cls:
            command_handler_cls.return_value = MagicMock()
            server = ParaViewBridgeServer(port=0)

        server.start()
        sock = socket.create_connection(("127.0.0.1", _server_port(server)), timeout=2.0)
        try:
            time.sleep(0.05)
            server.stop()
            sock.settimeout(2.0)
            assert sock.recv(1) == b""
        finally:
            sock.close()
