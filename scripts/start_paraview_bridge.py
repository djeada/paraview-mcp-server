#!/usr/bin/env python3
"""Start the ParaView bridge server.

Run this with pvpython:

    pvpython scripts/start_paraview_bridge.py [--host 127.0.0.1] [--port 9876]
    pvpython scripts/start_paraview_bridge.py --server-host 127.0.0.1 --server-port 11111

The bridge will listen for JSON commands from the paraview-mcp-server process.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger("start_paraview_bridge")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the ParaView TCP bridge server.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=9876, help="Port to listen on")
    parser.add_argument("--server-host", help="Optional pvserver host to connect to before starting the bridge")
    parser.add_argument("--server-port", type=int, default=11111, help="pvserver port used with --server-host")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Add the repo root to sys.path so 'bridge' package is importable.
    import os

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    from bridge.server import ParaViewBridgeServer

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

    logger.info("ParaView bridge ready on %s:%s — press Ctrl+C to stop.", args.host, args.port)
    try:
        while True:
            if process_server_events is not None:
                process_server_events()
            time.sleep(0.1)
    except KeyboardInterrupt:
        logger.info("Shutting down ParaView bridge.")
        server.stop()


if __name__ == "__main__":
    main()
