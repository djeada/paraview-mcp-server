"""Start the MCP bridge inside an already-open ParaView GUI session.

Run from ParaView:

    Tools -> Python Shell -> Run Script

Select this file. The script attaches the TCP bridge to ParaView's GUI event
loop and returns immediately, so MCP commands modify this open ParaView session.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

SCRIPT_PATH = globals().get("__file__")
ROOT_CANDIDATES = []
if SCRIPT_PATH:
    ROOT_CANDIDATES.append(Path(SCRIPT_PATH).resolve().parents[1])
ROOT_CANDIDATES.extend([Path.cwd(), Path.cwd().parent])

for candidate in ROOT_CANDIDATES:
    if (candidate / "bridge" / "gui_bridge.py").is_file():
        repo_root = str(candidate)
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
        break

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
