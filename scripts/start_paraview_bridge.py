#!/usr/bin/env python3
"""Start the ParaView bridge server.

Run this with pvpython:

    pvpython scripts/start_paraview_bridge.py [--host 127.0.0.1] [--port 9876]
    pvpython scripts/start_paraview_bridge.py --server-host 127.0.0.1 --server-port 11111

The bridge listens for JSON commands from the paraview-mcp-server process.

pvpython does not share the MCP server's virtualenv, so the ``paraview_mcp_bridge``
package must be importable. ``paraview-mcp-launch`` arranges that by setting
PYTHONPATH; when running this script by hand from a checkout it falls back to
locating the package next to this file.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import os
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger("start_paraview_bridge")


def _ensure_bridge_importable() -> None:
    """Put the directory containing ``paraview_mcp_bridge`` on sys.path."""
    try:
        import paraview_mcp_bridge  # noqa: F401, PLC0415

        return
    except ImportError:
        pass

    here = Path(__file__).resolve().parent
    candidates = [
        here.parent / "src",  # source checkout: <root>/src/paraview_mcp_bridge
        here.parent,  # installed package data: <pkg>/_scripts/..
        Path.cwd() / "src",
        Path.cwd(),
    ]
    for candidate in candidates:
        if (candidate / "paraview_mcp_bridge" / "server.py").is_file():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            return
    searched = "\n  ".join(str(path) for path in candidates)
    raise SystemExit(f"Could not import 'paraview_mcp_bridge'. Looked in:\n  {searched}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the ParaView TCP bridge server.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=9876, help="Port to listen on")
    parser.add_argument("--server-host", help="Optional pvserver host to connect to before starting the bridge")
    parser.add_argument("--server-port", type=int, default=11111, help="pvserver port used with --server-host")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    _ensure_bridge_importable()

    from paraview_mcp_bridge import runtime
    from paraview_mcp_bridge.server import ParaViewBridgeServer

    process_server_events = None
    if args.server_host:
        from paraview.simple import Connect

        logger.info("Connecting bridge runtime to pvserver at %s:%s.", args.server_host, args.server_port)
        Connect(args.server_host, args.server_port)
        try:
            from paraview.collaboration import processServerEvents

            process_server_events = processServerEvents
        except ImportError:
            process_server_events = None

    server = ParaViewBridgeServer(host=args.host, port=args.port)
    server.start()

    if server.token:
        logger.info("Bridge token written to %s (readable by this user only).", runtime.token_file_path())
    else:
        logger.warning(
            "Bridge authentication is disabled (%s=1). Any local process can execute Python in this session.",
            runtime.DISABLE_AUTH_ENV,
        )

    logger.info("ParaView bridge ready on %s:%s — press Ctrl+C to stop.", server.host, server.port)
    try:
        while True:
            if process_server_events is not None:
                process_server_events()
            time.sleep(0.1)
    except KeyboardInterrupt:
        logger.info("Shutting down ParaView bridge.")
        server.stop()
        if server.token:
            # Leave no stale token behind for the next bridge to trip over.
            with contextlib.suppress(OSError):
                os.remove(runtime.token_file_path())


if __name__ == "__main__":
    main()
