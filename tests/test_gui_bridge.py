"""Tests for the ParaView GUI bridge lifecycle helpers."""

from __future__ import annotations

import json
import socket
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from paraview_mcp_bridge import gui_bridge


class FakeInteractor:
    def __init__(self):
        self.callback = None
        self.removed_observer = None
        self.destroyed_timer = None

    def AddObserver(self, event_name, callback):  # noqa: N802
        assert event_name == "TimerEvent"
        self.callback = callback
        return 100

    def CreateRepeatingTimer(self, interval_ms):  # noqa: N802
        assert interval_ms > 0
        return 200

    def DestroyTimer(self, timer_id):  # noqa: N802
        self.destroyed_timer = timer_id

    def RemoveObserver(self, observer_id):  # noqa: N802
        self.removed_observer = observer_id


class FakeRenderWindow:
    def __init__(self, interactor):
        self._interactor = interactor

    def GetInteractor(self):  # noqa: N802
        return self._interactor


class FakeView:
    def __init__(self, interactor):
        self._interactor = interactor

    def GetRenderWindow(self):  # noqa: N802
        return FakeRenderWindow(self._interactor)


@pytest.fixture
def fake_interactor(monkeypatch):
    interactor = FakeInteractor()
    paraview_module = ModuleType("paraview")
    paraview_module.fromGUI = True
    simple_module = ModuleType("paraview.simple")
    simple_module.GetActiveViewOrCreate = MagicMock(return_value=FakeView(interactor))
    monkeypatch.setitem(sys.modules, "paraview", paraview_module)
    monkeypatch.setitem(sys.modules, "paraview.simple", simple_module)
    yield interactor
    gui_bridge.stop_gui_bridge()


def test_start_gui_bridge_is_non_blocking_and_reports_status(fake_interactor):
    with patch("paraview_mcp_bridge.command_handler.CommandHandler", return_value=MagicMock()):
        status = gui_bridge.start_gui_bridge(port=0)

    assert fake_interactor.callback is not None
    assert status["running"] is True
    assert status["already_running"] is False
    assert status["host"] == "127.0.0.1"
    assert status["port"] > 0
    assert gui_bridge.gui_bridge_status() == {
        "host": status["host"],
        "port": status["port"],
        "running": True,
    }
    assert status["token_file"], "a started GUI bridge must publish a token"


def test_start_gui_bridge_is_idempotent(fake_interactor):
    with patch("paraview_mcp_bridge.command_handler.CommandHandler", return_value=MagicMock()):
        first = gui_bridge.start_gui_bridge(port=0)
        second = gui_bridge.start_gui_bridge(port=0)

    assert second == {
        "host": first["host"],
        "port": first["port"],
        "running": True,
        "already_running": True,
        "token_file": first["token_file"],
    }


def test_stop_gui_bridge_stops_running_server(fake_interactor):
    with patch("paraview_mcp_bridge.command_handler.CommandHandler", return_value=MagicMock()):
        started = gui_bridge.start_gui_bridge(port=0)

    stopped = gui_bridge.stop_gui_bridge()

    assert stopped == {
        "host": started["host"],
        "port": started["port"],
        "running": False,
        "stopped": True,
    }
    assert fake_interactor.destroyed_timer == 200
    assert fake_interactor.removed_observer == 100
    assert gui_bridge.gui_bridge_status() == {"running": False}


def test_gui_bridge_processes_socket_request_from_poll_callback(fake_interactor):
    handler = MagicMock()
    handler.handle.return_value = {"source_count": 0}
    with patch("paraview_mcp_bridge.command_handler.CommandHandler", return_value=handler):
        started = gui_bridge.start_gui_bridge(port=0)

    token = gui_bridge._SERVER.token
    with socket.create_connection((started["host"], started["port"]), timeout=1) as client:
        request = {"id": "abc", "command": "scene.get_info", "params": {}, "token": token}
        client.sendall((json.dumps(request) + "\n").encode("utf-8"))
        assert fake_interactor.callback is not None
        fake_interactor.callback(None, "TimerEvent")
        fake_interactor.callback(None, "TimerEvent")
        response = client.recv(65536)

    assert json.loads(response.decode("utf-8")) == {
        "id": "abc",
        "success": True,
        "result": {"source_count": 0},
    }
    handler.handle.assert_called_once_with("scene.get_info", {})


def test_gui_bridge_rejects_command_line_startup(monkeypatch):
    paraview_module = ModuleType("paraview")
    paraview_module.fromGUI = False
    simple_module = ModuleType("paraview.simple")
    monkeypatch.setitem(sys.modules, "paraview", paraview_module)
    monkeypatch.setitem(sys.modules, "paraview.simple", simple_module)

    with pytest.raises(RuntimeError, match="Python Shell"):
        gui_bridge.start_gui_bridge(port=0)


def test_gui_bridge_answers_pipelined_requests(fake_interactor):
    """Two requests in one write must both get answered.

    select() only reports kernel readability, so a second request already
    copied into the client buffer is invisible to it. Handling one request per
    readable event stranded the rest until new bytes arrived, hanging any
    client that batches.
    """
    handler = MagicMock()
    handler.handle.return_value = {"source_count": 0}
    with patch("paraview_mcp_bridge.command_handler.CommandHandler", return_value=handler):
        started = gui_bridge.start_gui_bridge(port=0)

    token = gui_bridge._SERVER.token
    payload = b""
    for index in (1, 2, 3):
        request = {"id": f"r{index}", "command": "scene.get_info", "params": {}, "token": token}
        payload += (json.dumps(request) + "\n").encode("utf-8")

    with socket.create_connection((started["host"], started["port"]), timeout=2) as client:
        client.sendall(payload)
        for _ in range(10):
            fake_interactor.callback(None, "TimerEvent")
        client.settimeout(1.0)
        received = b""
        while received.count(b"\n") < 3:
            chunk = client.recv(65536)
            if not chunk:
                break
            received += chunk

    ids = [json.loads(line)["id"] for line in received.split(b"\n") if line.strip()]
    assert ids == ["r1", "r2", "r3"]


def test_gui_bridge_poll_budget_leaves_backlog_for_next_tick(fake_interactor):
    """A burst must not be drained in one tick; the GUI event loop comes first."""
    handler = MagicMock()
    handler.handle.return_value = {"ok": True}
    with patch("paraview_mcp_bridge.command_handler.CommandHandler", return_value=handler):
        started = gui_bridge.start_gui_bridge(port=0)

    token = gui_bridge._SERVER.token
    count = gui_bridge.MAX_REQUESTS_PER_POLL + 3
    payload = b""
    for index in range(count):
        request = {"id": f"r{index}", "command": "scene.get_info", "params": {}, "token": token}
        payload += (json.dumps(request) + "\n").encode("utf-8")

    with socket.create_connection((started["host"], started["port"]), timeout=2) as client:
        client.sendall(payload)
        # First tick only accepts: the new socket was not in that select() set.
        fake_interactor.callback(None, "TimerEvent")
        assert handler.handle.call_count == 0

        # Second tick reads the burst and handles exactly one budget of it.
        fake_interactor.callback(None, "TimerEvent")
        assert handler.handle.call_count == gui_bridge.MAX_REQUESTS_PER_POLL
        assert gui_bridge._SERVER.has_pending_requests()

        # The backlog is drained from the buffer, with no new bytes arriving.
        fake_interactor.callback(None, "TimerEvent")
        assert handler.handle.call_count == count
        assert not gui_bridge._SERVER.has_pending_requests()


def test_gui_bridge_rejects_request_without_token(fake_interactor):
    handler = MagicMock()
    with patch("paraview_mcp_bridge.command_handler.CommandHandler", return_value=handler):
        started = gui_bridge.start_gui_bridge(port=0)

    with socket.create_connection((started["host"], started["port"]), timeout=2) as client:
        request = {"id": "abc", "command": "scene.get_info", "params": {}}
        client.sendall((json.dumps(request) + "\n").encode("utf-8"))
        for _ in range(5):
            fake_interactor.callback(None, "TimerEvent")
        client.settimeout(1.0)
        response = json.loads(client.recv(65536).decode("utf-8"))

    assert response["success"] is False
    assert "token" in response["error"]
    handler.handle.assert_not_called()
