#!/usr/bin/env python3
"""Start the ParaView bridge server.

Run this with pvpython:

    pvpython scripts/start_paraview_bridge.py [--host 127.0.0.1] [--port 9876]

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
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Add the repo root to sys.path so 'bridge' package is importable.
    import os

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    from bridge.server import ParaViewBridgeServer

    server = ParaViewBridgeServer(host=args.host, port=args.port)
    server.start()

    logger.info("ParaView bridge ready on %s:%s — press Ctrl+C to stop.", args.host, args.port)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down ParaView bridge.")
        server.stop()


if __name__ == "__main__":
    main()
