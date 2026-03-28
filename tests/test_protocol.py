"""Tests for the bridge TCP protocol — request/response format and wire encoding."""

import json
import socket
import threading
import time
import uuid

import pytest


def _send_request(port: int, command: str, params: dict, timeout: float = 5.0) -> dict:
    """Send a single newline-delimited JSON request and read the response."""
    request = {"id": str(uuid.uuid4()), "command": command, "params": params}
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
        sock.sendall((json.dumps(request) + "\n").encode("utf-8"))
        buffer = b""
        sock.settimeout(timeout)
        while b"\n" not in buffer:
            chunk = sock.recv(65536)
            if not chunk:
                raise ConnectionError("Connection closed before response")
            buffer += chunk
    line = buffer.split(b"\n", 1)[0]
    return json.loads(line.decode("utf-8"))


class FakeBridgeServer:
    """Minimal TCP server that echoes a fixed response for tests."""

    def __init__(self, port: int, response: dict):
        self._port = port
        self._response = response
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.settimeout(1.0)
        self._server.bind(("127.0.0.1", port))
        self._server.listen(1)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._running = False

    def start(self):
        self._running = True
        self._thread.start()
        time.sleep(0.05)  # Allow the thread to start listening

    def stop(self):
        self._running = False
        self._server.close()

    def _serve(self):
        while self._running:
            try:
                conn, _ = self._server.accept()
            except OSError:
                break
            try:
                buffer = b""
                while b"\n" not in buffer:
                    chunk = conn.recv(4096)
                    if not chunk:
                        return
                    buffer += chunk
                conn.sendall(
                    (json.dumps(self._response) + "\n").encode("utf-8")
                )
            finally:
                conn.close()


class TestProtocolEncoding:
    """Verify the newline-delimited JSON wire format."""

    def test_request_is_valid_json_followed_by_newline(self):
        request = {
            "id": "abc-123",
            "command": "scene.get_info",
            "params": {},
        }
        wire = (json.dumps(request) + "\n").encode("utf-8")
        lines = wire.split(b"\n")
        assert lines[-1] == b""
        parsed = json.loads(lines[0])
        assert parsed["command"] == "scene.get_info"

    def test_response_success_shape(self):
        response = {
            "id": "abc-123",
            "success": True,
            "result": {"source_count": 1},
        }
        encoded = (json.dumps(response) + "\n").encode("utf-8")
        decoded = json.loads(encoded.split(b"\n")[0])
        assert decoded["success"] is True
        assert decoded["result"]["source_count"] == 1

    def test_response_error_shape(self):
        response = {
            "id": "abc-123",
            "success": False,
            "error": "Source 'foo' not found",
        }
        encoded = (json.dumps(response) + "\n").encode("utf-8")
        decoded = json.loads(encoded.split(b"\n")[0])
        assert decoded["success"] is False
        assert "foo" in decoded["error"]

    def test_request_id_is_preserved_in_response(self):
        req_id = str(uuid.uuid4())
        response = {"id": req_id, "success": True, "result": {}}
        decoded = json.loads((json.dumps(response) + "\n").encode("utf-8").split(b"\n")[0])
        assert decoded["id"] == req_id

    def test_unicode_params_survive_round_trip(self):
        params = {"filepath": "/données/résultat.vtu"}
        wire = (json.dumps({"id": "x", "command": "source.open_file", "params": params}) + "\n").encode("utf-8")
        decoded = json.loads(wire.split(b"\n")[0])
        assert decoded["params"]["filepath"] == "/données/résultat.vtu"


class TestFakeBridgeIntegration:
    """Integration tests against a minimal fake bridge server."""

    def test_roundtrip_success_response(self):
        fake_response = {"id": "ignored", "success": True, "result": {"source_count": 0}}
        srv = FakeBridgeServer(port=19876, response=fake_response)
        srv.start()
        try:
            resp = _send_request(19876, "scene.get_info", {})
            assert resp["success"] is True
            assert resp["result"]["source_count"] == 0
        finally:
            srv.stop()

    def test_roundtrip_error_response(self):
        fake_response = {
            "id": "ignored",
            "success": False,
            "error": "command failed",
        }
        srv = FakeBridgeServer(port=19877, response=fake_response)
        srv.start()
        try:
            resp = _send_request(19877, "scene.get_info", {})
            assert resp["success"] is False
            assert "failed" in resp["error"]
        finally:
            srv.stop()

    def test_connection_refused_raises(self):
        with pytest.raises(OSError):
            _send_request(19878, "scene.get_info", {}, timeout=1.0)
