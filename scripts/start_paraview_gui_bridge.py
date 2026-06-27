"""Start the MCP bridge inside an already-open ParaView GUI session.

Run from ParaView:

    Tools -> Python Shell -> Run Script

Select this file. The script starts the TCP bridge in a background thread and
returns immediately, so the ParaView GUI remains usable. MCP commands will then
modify this open ParaView session.
"""

from __future__ import annotations

import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from bridge.gui_bridge import gui_bridge_status, start_gui_bridge, stop_gui_bridge  # noqa: E402

globals()["stop_gui_bridge"] = stop_gui_bridge
globals()["gui_bridge_status"] = gui_bridge_status


def main() -> None:
    host = os.environ.get("PARAVIEW_MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("PARAVIEW_MCP_PORT", "9876"))
    status = start_gui_bridge(host=host, port=port)
    state = "already running" if status["already_running"] else "started"
    print(f"ParaView MCP GUI bridge {state} on {status['host']}:{status['port']}")
    print("Verify from a terminal with:")
    print("  python scripts/paraview_bridge_request.py scene.get_info")
    print("Stop from the ParaView Python Shell with:")
    print("  stop_gui_bridge()")


main()
