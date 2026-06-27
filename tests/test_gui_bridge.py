"""Tests for the ParaView GUI bridge lifecycle helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from bridge import gui_bridge


def teardown_function(_function):
    gui_bridge.stop_gui_bridge()


def test_start_gui_bridge_is_non_blocking_and_reports_status():
    with patch("bridge.command_handler.CommandHandler", return_value=MagicMock()):
        status = gui_bridge.start_gui_bridge(port=0)

    assert status["running"] is True
    assert status["already_running"] is False
    assert status["host"] == "127.0.0.1"
    assert status["port"] > 0
    assert gui_bridge.gui_bridge_status() == {
        "host": status["host"],
        "port": status["port"],
        "running": True,
    }


def test_start_gui_bridge_is_idempotent():
    with patch("bridge.command_handler.CommandHandler", return_value=MagicMock()):
        first = gui_bridge.start_gui_bridge(port=0)
        second = gui_bridge.start_gui_bridge(port=0)

    assert first["running"] is True
    assert second == {
        "host": first["host"],
        "port": first["port"],
        "running": True,
        "already_running": True,
    }


def test_stop_gui_bridge_stops_running_server():
    with patch("bridge.command_handler.CommandHandler", return_value=MagicMock()):
        started = gui_bridge.start_gui_bridge(port=0)

    stopped = gui_bridge.stop_gui_bridge()

    assert stopped == {
        "host": started["host"],
        "port": started["port"],
        "running": False,
        "stopped": True,
    }
    assert gui_bridge.gui_bridge_status() == {"running": False}
