"""ParaView MCP server package."""

__version__ = "0.2.0"

from paraview_mcp_server.headless import HeadlessJobManager, HeadlessPvpythonExecutor
from paraview_mcp_server.server import main

__all__ = ["main", "HeadlessPvpythonExecutor", "HeadlessJobManager", "__version__"]
