"""Launch a server-backed ParaView GUI session with the MCP bridge attached."""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path


def _repo_root() -> Path:
    package_root = Path(__file__).resolve().parents[2]
    if (package_root / "scripts" / "start_paraview_bridge.py").is_file():
        return package_root
    return Path.cwd()


def _wait_for_port(host: str, port: int, *, timeout: float, name: str) -> None:
    deadline = time.monotonic() + timeout
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for {name} on {host}:{port}: {last_error}")


def _wait_for_listen_port(port: int, *, timeout: float, name: str) -> None:
    deadline = time.monotonic() + timeout
    needle = f":{port:04X}"
    while time.monotonic() < deadline:
        try:
            lines = Path("/proc/net/tcp").read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for line in lines[1:]:
            columns = line.split()
            if len(columns) >= 4 and columns[1].endswith(needle) and columns[3] == "0A":
                return
        time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for {name} to listen on port {port}")


def _ensure_port_available(host: str, port: int, *, name: str) -> None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
    except OSError as exc:
        raise RuntimeError(f"{name} port is already in use on {host}:{port}") from exc


def _terminate(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _start_bridge(
    *,
    pvpython: str,
    bridge_script: Path,
    bridge_host: str,
    bridge_port: int,
    server_host: str,
    server_port: int,
    repo_root: Path,
) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [
            pvpython,
            str(bridge_script),
            "--host",
            bridge_host,
            "--port",
            str(bridge_port),
            "--server-host",
            server_host,
            "--server-port",
            str(server_port),
        ],
        cwd=str(repo_root),
    )


def _wait_for_gui_with_bridge_supervision(
    *,
    gui_proc: subprocess.Popen[bytes],
    bridge_proc: subprocess.Popen[bytes],
    pvpython: str,
    bridge_script: Path,
    bridge_host: str,
    bridge_port: int,
    server_host: str,
    server_port: int,
    repo_root: Path,
) -> int:
    try:
        while True:
            try:
                return gui_proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

            bridge_returncode = bridge_proc.poll()
            if bridge_returncode is None:
                continue

            print(
                f"ParaView MCP bridge exited with code {bridge_returncode}; restarting on {bridge_host}:{bridge_port}",
                flush=True,
            )
            bridge_proc = _start_bridge(
                pvpython=pvpython,
                bridge_script=bridge_script,
                bridge_host=bridge_host,
                bridge_port=bridge_port,
                server_host=server_host,
                server_port=server_port,
                repo_root=repo_root,
            )
            _wait_for_port(bridge_host, bridge_port, timeout=20, name="ParaView MCP bridge")
            print(f"ParaView MCP bridge ready on {bridge_host}:{bridge_port}", flush=True)
    finally:
        _terminate(bridge_proc)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Start pvserver, attach the ParaView MCP bridge, and launch a ParaView GUI "
            "connected to the same server-backed session."
        )
    )
    parser.add_argument("--paraview", default=os.environ.get("PARAVIEW_BIN", "paraview"), help="ParaView executable")
    parser.add_argument("--pvserver", default=os.environ.get("PVSERVER_BIN", "pvserver"), help="pvserver executable")
    parser.add_argument("--pvpython", default=os.environ.get("PVPYTHON_BIN", "pvpython"), help="pvpython executable")
    parser.add_argument("--server-host", default="127.0.0.1", help="Host used by local clients to reach pvserver")
    parser.add_argument("--server-port", type=int, default=11111, help="pvserver port")
    parser.add_argument("--bridge-host", default="127.0.0.1", help="MCP bridge bind host")
    parser.add_argument("--bridge-port", type=int, default=9876, help="MCP bridge bind port")
    parser.add_argument(
        "paraview_args",
        nargs=argparse.REMAINDER,
        help="Extra arguments passed to ParaView. Prefix them with --, for example: -- --data file.vtu",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = _repo_root()
    bridge_script = repo_root / "scripts" / "start_paraview_bridge.py"
    if not bridge_script.is_file():
        raise SystemExit(f"Could not find bridge script: {bridge_script}")

    paraview = shutil.which(args.paraview) or args.paraview
    pvserver = shutil.which(args.pvserver) or args.pvserver
    pvpython = shutil.which(args.pvpython) or args.pvpython
    extra_args = list(args.paraview_args)
    if extra_args[:1] == ["--"]:
        extra_args = extra_args[1:]

    server_proc: subprocess.Popen[bytes] | None = None
    bridge_proc: subprocess.Popen[bytes] | None = None
    gui_proc: subprocess.Popen[bytes] | None = None

    try:
        _ensure_port_available("127.0.0.1", args.server_port, name="pvserver")
        _ensure_port_available(args.bridge_host, args.bridge_port, name="ParaView MCP bridge")

        server_proc = subprocess.Popen(
            [
                pvserver,
                "--multi-clients",
                f"--server-port={args.server_port}",
                "--bind-address=127.0.0.1",
            ]
        )
        _wait_for_listen_port(args.server_port, timeout=20, name="pvserver")

        print(f"Launching ParaView GUI connected to cs://{args.server_host}:{args.server_port}", flush=True)
        gui_proc = subprocess.Popen(
            [
                paraview,
                "--server-url",
                f"cs://{args.server_host}:{args.server_port}",
                *extra_args,
            ]
        )
        time.sleep(3)

        bridge_proc = _start_bridge(
            pvpython=pvpython,
            bridge_script=bridge_script,
            bridge_host=args.bridge_host,
            bridge_port=args.bridge_port,
            server_host=args.server_host,
            server_port=args.server_port,
            repo_root=repo_root,
        )
        _wait_for_port(args.bridge_host, args.bridge_port, timeout=20, name="ParaView MCP bridge")
        print(f"ParaView MCP bridge ready on {args.bridge_host}:{args.bridge_port}", flush=True)
        return _wait_for_gui_with_bridge_supervision(
            gui_proc=gui_proc,
            bridge_proc=bridge_proc,
            pvpython=pvpython,
            bridge_script=bridge_script,
            bridge_host=args.bridge_host,
            bridge_port=args.bridge_port,
            server_host=args.server_host,
            server_port=args.server_port,
            repo_root=repo_root,
        )
    except KeyboardInterrupt:
        return 130
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        _terminate(gui_proc)
        _terminate(bridge_proc)
        _terminate(server_proc)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
