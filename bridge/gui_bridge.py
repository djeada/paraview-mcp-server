"""Helpers for starting the bridge from an already-open ParaView GUI session."""

from __future__ import annotations

from typing import Any

from bridge.server import HOST, PORT, ParaViewBridgeServer

_SERVER: ParaViewBridgeServer | None = None


def start_gui_bridge(host: str = HOST, port: int = PORT) -> dict[str, Any]:
    """Start the bridge inside the current ParaView Python process.

    This function is intentionally non-blocking so it can be called from the
    ParaView GUI Python shell without freezing the application.
    """
    global _SERVER
    if _SERVER is not None and _SERVER.is_running:
        return {
            "host": _SERVER.host,
            "port": _SERVER.port,
            "running": True,
            "already_running": True,
        }

    server = ParaViewBridgeServer(host=host, port=port)
    server.start()
    _SERVER = server
    return {
        "host": server.host,
        "port": server.port,
        "running": True,
        "already_running": False,
    }


def stop_gui_bridge() -> dict[str, Any]:
    """Stop the bridge started by :func:`start_gui_bridge`."""
    global _SERVER
    if _SERVER is None:
        return {"running": False, "stopped": False}

    host = _SERVER.host
    port = _SERVER.port
    _SERVER.stop()
    _SERVER = None
    return {"host": host, "port": port, "running": False, "stopped": True}


def gui_bridge_status() -> dict[str, Any]:
    """Return the current GUI bridge status."""
    if _SERVER is None or not _SERVER.is_running:
        return {"running": False}
    return {"host": _SERVER.host, "port": _SERVER.port, "running": True}
