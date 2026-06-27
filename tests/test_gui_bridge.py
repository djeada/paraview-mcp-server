"""Tests for the ParaView GUI bridge lifecycle helpers."""

from __future__ import annotations

import json
import socket
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from bridge import gui_bridge


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
    with patch("bridge.command_handler.CommandHandler", return_value=MagicMock()):
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


def test_start_gui_bridge_is_idempotent(fake_interactor):
    with patch("bridge.command_handler.CommandHandler", return_value=MagicMock()):
        first = gui_bridge.start_gui_bridge(port=0)
        second = gui_bridge.start_gui_bridge(port=0)

    assert second == {
        "host": first["host"],
        "port": first["port"],
        "running": True,
        "already_running": True,
    }


def test_stop_gui_bridge_stops_running_server(fake_interactor):
    with patch("bridge.command_handler.CommandHandler", return_value=MagicMock()):
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
    with patch("bridge.command_handler.CommandHandler", return_value=handler):
        started = gui_bridge.start_gui_bridge(port=0)

    with socket.create_connection((started["host"], started["port"]), timeout=1) as client:
        request = {"id": "abc", "command": "scene.get_info", "params": {}}
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
