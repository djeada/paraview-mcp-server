"""Tests for the ParaView MCP launcher."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from paraview_mcp_server import launcher


def test_launcher_starts_gui_before_bridge():
    calls = []

    def fake_popen(cmd, **kwargs):
        proc = MagicMock()
        proc.poll.return_value = None
        proc.wait.return_value = 0
        proc.cmd = cmd
        calls.append((cmd, kwargs, proc))
        return proc

    with (
        patch("paraview_mcp_server.launcher._repo_root", return_value=Path.cwd()),
        patch("paraview_mcp_server.launcher._wait_for_listen_port"),
        patch("paraview_mcp_server.launcher._wait_for_port"),
        patch("paraview_mcp_server.launcher._ensure_port_available"),
        patch("paraview_mcp_server.launcher.time.sleep"),
        patch("paraview_mcp_server.launcher.subprocess.Popen", side_effect=fake_popen),
        patch("paraview_mcp_server.launcher.shutil.which", side_effect=lambda value: value),
    ):
        result = launcher.main([])

    assert result == 0
    assert calls[0][0][0] == "pvserver"
    assert "--multi-clients" in calls[0][0]
    assert calls[1][0][0] == "paraview"
    assert "--server-url" in calls[1][0]
    assert calls[2][0][0] == "pvpython"
    assert "--server-host" in calls[2][0]


def test_launcher_strips_separator_from_paraview_args():
    calls = []

    def fake_popen(cmd, **kwargs):
        proc = MagicMock()
        proc.poll.return_value = None
        proc.wait.return_value = 0
        calls.append(cmd)
        return proc

    with (
        patch("paraview_mcp_server.launcher._repo_root", return_value=Path.cwd()),
        patch("paraview_mcp_server.launcher._wait_for_listen_port"),
        patch("paraview_mcp_server.launcher._wait_for_port"),
        patch("paraview_mcp_server.launcher._ensure_port_available"),
        patch("paraview_mcp_server.launcher.time.sleep"),
        patch("paraview_mcp_server.launcher.subprocess.Popen", side_effect=fake_popen),
        patch("paraview_mcp_server.launcher.shutil.which", side_effect=lambda value: value),
    ):
        launcher.main(["--", "--data", "disk.vtu"])

    assert "--data" in calls[1]
    assert "disk.vtu" in calls[1]
    assert "--" not in calls[1]


def test_launcher_restarts_bridge_while_gui_is_running():
    gui_proc = MagicMock()
    gui_proc.wait.side_effect = [TimeoutError(), 0]

    dead_bridge = MagicMock()
    dead_bridge.poll.return_value = 9

    restarted_bridge = MagicMock()
    restarted_bridge.poll.return_value = None

    with (
        patch("paraview_mcp_server.launcher.subprocess.TimeoutExpired", TimeoutError),
        patch("paraview_mcp_server.launcher._start_bridge", return_value=restarted_bridge) as start_bridge,
        patch("paraview_mcp_server.launcher._wait_for_port") as wait_for_port,
        patch("paraview_mcp_server.launcher._terminate") as terminate,
    ):
        result = launcher._wait_for_gui_with_bridge_supervision(
            gui_proc=gui_proc,
            bridge_proc=dead_bridge,
            pvpython="pvpython",
            bridge_script=Path("bridge.py"),
            bridge_host="127.0.0.1",
            bridge_port=9876,
            server_host="127.0.0.1",
            server_port=11111,
            repo_root=Path.cwd(),
        )

    assert result == 0
    start_bridge.assert_called_once()
    wait_for_port.assert_called_once_with("127.0.0.1", 9876, timeout=20, name="ParaView MCP bridge")
    terminate.assert_called_once_with(restarted_bridge)


def test_launcher_fails_before_starting_processes_when_port_is_unavailable():
    with (
        patch("paraview_mcp_server.launcher._repo_root", return_value=Path.cwd()),
        patch("paraview_mcp_server.launcher._ensure_port_available", side_effect=RuntimeError("port busy")),
        patch("paraview_mcp_server.launcher.subprocess.Popen") as popen,
    ):
        result = launcher.main([])

    assert result == 1
    popen.assert_not_called()
