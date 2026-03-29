FROM python:3.12-slim AS base

LABEL maintainer="Adam Djellouli <adam@djellouli.com>"
LABEL description="ParaView MCP Server — headless mode (no bridge)"

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src/ src/
COPY bridge/ bridge/

RUN pip install --no-cache-dir .

# pvpython is NOT bundled — mount or install ParaView separately.
# The MCP server itself runs without ParaView; headless transport
# needs PVPYTHON_BIN pointing to a pvpython binary.
ENV PVPYTHON_BIN=pvpython

ENTRYPOINT ["paraview-mcp-server"]
