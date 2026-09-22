FROM python:3.12-slim AS base

LABEL maintainer="Adam Djellouli <adam@djellouli.com>"
LABEL description="ParaView MCP Server — headless transport only (no ParaView bundled)"

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src/ src/
COPY scripts/ scripts/

RUN pip install --no-cache-dir .

# ParaView is NOT bundled: the image ships only the MCP protocol adapter.
# Every transport needs a ParaView runtime, so mount or install one and point
# PVPYTHON_BIN at its pvpython. Without that, the server starts and answers
# tool listings but every ParaView operation fails.
ENV PVPYTHON_BIN=pvpython

# The server executes Python supplied by its MCP client; do not hand that root.
RUN useradd --create-home --uid 10001 paraview
USER paraview

ENTRYPOINT ["paraview-mcp-server"]
