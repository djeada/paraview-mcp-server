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
        patch("paraview_mcp_server.launcher.time.sleep"),
        patch("paraview_mcp_server.launcher.subprocess.Popen", side_effect=fake_popen),
        patch("paraview_mcp_server.launcher.shutil.which", side_effect=lambda value: value),
    ):
        launcher.main(["--", "--data", "disk.vtu"])

    assert "--data" in calls[1]
    assert "disk.vtu" in calls[1]
    assert "--" not in calls[1]
