"""ParaView bridge package — runs inside pvpython to expose ParaView over TCP.

This package is deliberately free of third-party dependencies: it is imported
by ParaView's own Python runtime, which does not share the MCP server's
virtualenv and generally has neither ``mcp`` nor ``pydantic`` available.
"""

__version__ = "0.2.0"
