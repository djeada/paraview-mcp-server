"""Tests for bridge runtime state, auth tokens, and launcher discovery."""

from __future__ import annotations

import os
import socket
import stat
import sys
from pathlib import Path

import pytest

from paraview_mcp_bridge import runtime
from paraview_mcp_server import launcher


class TestTokenLifecycle:
    def test_created_token_is_owner_readable_only(self, isolated_state_dir):
        token = runtime.create_token()
        path = runtime.token_file_path()

        assert token
        assert path.read_text(encoding="utf-8") == token
        if os.name == "posix":
            mode = stat.S_IMODE(path.stat().st_mode)
            assert mode == 0o600, f"token file must not be group/world readable, got {mode:o}"

    def test_state_dir_is_private(self, isolated_state_dir):
        path = runtime.state_dir()
        if os.name == "posix":
            assert stat.S_IMODE(path.stat().st_mode) == 0o700

    def test_read_token_returns_none_without_a_bridge(self, isolated_state_dir):
        assert runtime.read_token() is None

    def test_env_token_wins_over_the_file(self, isolated_state_dir, monkeypatch):
        runtime.create_token()
        monkeypatch.setenv(runtime.TOKEN_ENV, "from-env")
        assert runtime.read_token() == "from-env"

    def test_tokens_match_is_permissive_only_when_unset(self):
        assert runtime.tokens_match(None, None) is True
        assert runtime.tokens_match("a", "a") is True
        assert runtime.tokens_match("a", "b") is False
        assert runtime.tokens_match("a", None) is False
        assert runtime.tokens_match("a", 42) is False

    def test_session_log_follows_the_private_state_dir(self, isolated_state_dir):
        """It used to be a fixed /tmp path: a symlink target, shared across users."""
        path = runtime.session_log_path()
        assert path.parent == isolated_state_dir

    def test_session_log_honours_an_explicit_override(self, tmp_path, monkeypatch):
        override = tmp_path / "custom.log"
        monkeypatch.setenv("PARAVIEW_MCP_SESSION_LOG", str(override))
        assert runtime.session_log_path() == override

    @pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
    def test_private_append_refuses_to_follow_a_symlink(self, isolated_state_dir, tmp_path):
        target = tmp_path / "target.log"
        link = isolated_state_dir / "link.log"
        target.write_text("", encoding="utf-8")
        link.symlink_to(target)

        with pytest.raises(OSError):
            runtime.open_private_append(link)


class TestLoopbackDetection:
    @pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.5"])
    def test_loopback_hosts(self, host):
        assert runtime.is_loopback(host) is True

    @pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.com"])
    def test_non_loopback_hosts(self, host):
        assert runtime.is_loopback(host) is False


class TestLauncherDiscovery:
    def test_finds_the_bridge_script_in_a_source_checkout(self):
        script = launcher.find_bridge_script()
        assert script.is_file()
        assert script.name == launcher.BRIDGE_SCRIPT_NAME

    def test_bridge_python_path_exposes_the_bridge_package(self):
        entries = launcher.bridge_python_path().split(os.pathsep)
        assert (Path(entries[0]) / "paraview_mcp_bridge" / "server.py").is_file()

    def test_bridge_python_path_preserves_existing_entries(self, monkeypatch):
        monkeypatch.setenv("PYTHONPATH", "/some/existing")
        entries = launcher.bridge_python_path().split(os.pathsep)
        assert "/some/existing" in entries

    def test_missing_script_reports_where_it_looked(self, monkeypatch):
        monkeypatch.setattr(launcher, "_candidate_script_dirs", lambda: [Path("/nonexistent")])
        with pytest.raises(SystemExit, match="Looked in"):
            launcher.find_bridge_script()


class TestPortProbe:
    def test_reports_a_bound_port_as_in_use(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            port = sock.getsockname()[1]
            assert launcher._port_in_use("127.0.0.1", port) is True

    def test_reports_a_free_port_as_available(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        assert launcher._port_in_use("127.0.0.1", port) is False

    def test_wait_returns_once_the_port_is_taken(self):
        """Replaces a /proc/net/tcp parse that silently never matched off Linux."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            port = sock.getsockname()[1]
            launcher._wait_for_listen_port(port, timeout=2, name="test", host="127.0.0.1")

    def test_wait_times_out_on_a_free_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        with pytest.raises(RuntimeError, match="Timed out"):
            launcher._wait_for_listen_port(port, timeout=0.5, name="test", host="127.0.0.1")

    def test_probe_works_without_the_proc_filesystem(self, monkeypatch):
        """The old implementation parsed /proc/net/tcp and was Linux-only."""
        real_read_text = Path.read_text

        def deny_proc(self, *args, **kwargs):
            if str(self).startswith("/proc/"):
                raise OSError("no /proc on this platform")
            return real_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", deny_proc)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            port = sock.getsockname()[1]
            assert launcher._port_in_use("127.0.0.1", port) is True
            launcher._wait_for_listen_port(port, timeout=2, name="test", host="127.0.0.1")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only script layout")
def test_bridge_start_script_locates_the_package_without_an_install():
    """pvpython has its own interpreter, so the script must self-locate."""
    script = Path(__file__).resolve().parents[1] / "scripts" / "start_paraview_bridge.py"
    source = script.read_text(encoding="utf-8")
    assert "_ensure_bridge_importable" in source
    assert "paraview_mcp_bridge" in source
