"""ParaView MCP Server — External MCP server that bridges AI assistants to ParaView."""

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

logger = logging.getLogger(__name__)

PARAVIEW_HOST = "127.0.0.1"
PARAVIEW_PORT = 9876


class ParaViewConnection:
    """Async TCP client that communicates with the ParaView bridge server."""

    def __init__(self, host: str = PARAVIEW_HOST, port: int = PARAVIEW_PORT):
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    async def connect(self):
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        logger.info("Connected to ParaView bridge at %s:%s", self.host, self.port)

    async def disconnect(self):
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
            self._writer = None
            self._reader = None

    async def send_command(self, command: str, params: dict | None = None) -> Any:
        """Send a command to the ParaView bridge and return the result."""
        if not self._writer:
            await self.connect()

        request = {
            "id": str(uuid.uuid4()),
            "command": command,
            "params": params or {},
        }

        async with self._lock:
            try:
                self._writer.write(json.dumps(request).encode() + b"\n")
                await self._writer.drain()

                line = await self._reader.readline()
                if not line:
                    raise ConnectionError("ParaView bridge connection closed")

                response = json.loads(line)
                if not response.get("success"):
                    raise RuntimeError(
                        response.get("error", "Unknown error from ParaView bridge")
                    )
                return response.get("result")
            except (ConnectionError, OSError) as e:
                self._writer = None
                self._reader = None
                raise ConnectionError(f"Lost connection to ParaView bridge: {e}") from e


@asynccontextmanager
async def paraview_lifespan(server: FastMCP):
    """Manage the ParaView bridge connection lifecycle."""
    conn = ParaViewConnection()
    try:
        await conn.connect()
    except OSError:
        logger.warning(
            "Could not connect to ParaView bridge on startup. Will retry on first tool call."
        )
    yield conn
    await conn.disconnect()


mcp = FastMCP(
    "ParaView MCP Server",
    lifespan=paraview_lifespan,
    log_level="INFO",
)


def _get_conn(ctx: Context) -> ParaViewConnection:
    return ctx.request_context.lifespan_context


# -- Scene / session tools --


@mcp.tool(
    name="paraview_scene_get_info",
    description="Get basic information about the current ParaView session, including source count and active view type.",
)
async def scene_get_info(ctx: Context) -> str:
    result = await _get_conn(ctx).send_command("scene.get_info")
    return json.dumps(result, indent=2)


@mcp.tool(
    name="paraview_scene_list_sources",
    description="List all sources currently loaded in the ParaView pipeline browser.",
)
async def scene_list_sources(ctx: Context) -> str:
    result = await _get_conn(ctx).send_command("scene.list_sources")
    return json.dumps(result, indent=2)


@mcp.tool(
    name="paraview_scene_list_views",
    description="List all open views/render windows in the current ParaView session.",
)
async def scene_list_views(ctx: Context) -> str:
    result = await _get_conn(ctx).send_command("scene.list_views")
    return json.dumps(result, indent=2)


@mcp.tool(
    name="paraview_source_get_properties",
    description="Get the properties and metadata of a named source in the ParaView pipeline.",
)
async def source_get_properties(ctx: Context, name: str) -> str:
    result = await _get_conn(ctx).send_command(
        "source.get_properties", {"name": name}
    )
    return json.dumps(result, indent=2)


# -- Data loading tools --


@mcp.tool(
    name="paraview_source_open_file",
    description="Open a supported dataset file (VTK, VTU, VTS, ExodusII, CSV, etc.) in ParaView.",
)
async def source_open_file(ctx: Context, filepath: str) -> str:
    result = await _get_conn(ctx).send_command(
        "source.open_file", {"filepath": filepath}
    )
    return json.dumps(result, indent=2)


@mcp.tool(
    name="paraview_source_delete",
    description="Delete a named source from the ParaView pipeline.",
)
async def source_delete(ctx: Context, name: str) -> str:
    result = await _get_conn(ctx).send_command("source.delete", {"name": name})
    return json.dumps(result, indent=2)


@mcp.tool(
    name="paraview_source_rename",
    description="Rename a source in the ParaView pipeline.",
)
async def source_rename(ctx: Context, name: str, new_name: str) -> str:
    result = await _get_conn(ctx).send_command(
        "source.rename", {"name": name, "new_name": new_name}
    )
    return json.dumps(result, indent=2)


# -- Filter tools --


@mcp.tool(
    name="paraview_filter_slice",
    description=(
        "Apply a Slice filter to a named source. "
        "Specify origin as [x, y, z] and normal as [nx, ny, nz]. "
        "Defaults: origin=[0,0,0], normal=[1,0,0]."
    ),
)
async def filter_slice(
    ctx: Context,
    input: str,
    origin: list[float] | None = None,
    normal: list[float] | None = None,
) -> str:
    params: dict[str, Any] = {"input": input}
    if origin is not None:
        params["origin"] = origin
    if normal is not None:
        params["normal"] = normal
    result = await _get_conn(ctx).send_command("filter.slice", params)
    return json.dumps(result, indent=2)


@mcp.tool(
    name="paraview_filter_clip",
    description=(
        "Apply a Clip filter to a named source. "
        "Specify origin as [x, y, z] and normal as [nx, ny, nz]. "
        "Defaults: origin=[0,0,0], normal=[1,0,0]."
    ),
)
async def filter_clip(
    ctx: Context,
    input: str,
    origin: list[float] | None = None,
    normal: list[float] | None = None,
) -> str:
    params: dict[str, Any] = {"input": input}
    if origin is not None:
        params["origin"] = origin
    if normal is not None:
        params["normal"] = normal
    result = await _get_conn(ctx).send_command("filter.clip", params)
    return json.dumps(result, indent=2)


@mcp.tool(
    name="paraview_filter_contour",
    description=(
        "Apply a Contour (isosurface) filter to a named source. "
        "Specify the scalar array name and one or more isovalues."
    ),
)
async def filter_contour(
    ctx: Context,
    input: str,
    array: str,
    values: list[float],
) -> str:
    result = await _get_conn(ctx).send_command(
        "filter.contour", {"input": input, "array": array, "values": values}
    )
    return json.dumps(result, indent=2)


@mcp.tool(
    name="paraview_filter_threshold",
    description=(
        "Apply a Threshold filter to a named source. "
        "Keep cells where the scalar array falls within [lower, upper]."
    ),
)
async def filter_threshold(
    ctx: Context,
    input: str,
    array: str,
    lower: float,
    upper: float,
) -> str:
    result = await _get_conn(ctx).send_command(
        "filter.threshold",
        {"input": input, "array": array, "lower": lower, "upper": upper},
    )
    return json.dumps(result, indent=2)


# -- Display / coloring tools --


@mcp.tool(
    name="paraview_display_show",
    description="Make a named source visible in the active ParaView render view.",
)
async def display_show(ctx: Context, name: str) -> str:
    result = await _get_conn(ctx).send_command("display.show", {"name": name})
    return json.dumps(result, indent=2)


@mcp.tool(
    name="paraview_display_hide",
    description="Hide a named source in the active ParaView render view.",
)
async def display_hide(ctx: Context, name: str) -> str:
    result = await _get_conn(ctx).send_command("display.hide", {"name": name})
    return json.dumps(result, indent=2)


@mcp.tool(
    name="paraview_display_color_by",
    description=(
        "Color a named source by a data array. "
        "Specify the array name and optionally the component index "
        "(-1 = magnitude, 0/1/2 = X/Y/Z). "
        "association can be 'POINTS' (default) or 'CELLS'."
    ),
)
async def display_color_by(
    ctx: Context,
    name: str,
    array: str,
    component: int = -1,
    association: str = "POINTS",
) -> str:
    result = await _get_conn(ctx).send_command(
        "display.color_by",
        {"name": name, "array": array, "component": component, "association": association},
    )
    return json.dumps(result, indent=2)


@mcp.tool(
    name="paraview_display_set_representation",
    description=(
        "Set the display representation for a named source. "
        "Supported types: Surface, Wireframe, Points, Surface With Edges, Volume."
    ),
)
async def display_set_representation(
    ctx: Context, name: str, representation: str
) -> str:
    result = await _get_conn(ctx).send_command(
        "display.set_representation",
        {"name": name, "representation": representation},
    )
    return json.dumps(result, indent=2)


# -- View / camera tools --


@mcp.tool(
    name="paraview_view_reset_camera",
    description="Reset the camera in the active ParaView render view to fit all visible sources.",
)
async def view_reset_camera(ctx: Context) -> str:
    result = await _get_conn(ctx).send_command("view.reset_camera")
    return json.dumps(result, indent=2)


# -- Export tools --


@mcp.tool(
    name="paraview_export_screenshot",
    description=(
        "Save a screenshot of the active ParaView render view to a file. "
        "Supports PNG and JPEG. Default resolution is 1920×1080."
    ),
)
async def export_screenshot(
    ctx: Context,
    filepath: str,
    width: int = 1920,
    height: int = 1080,
) -> str:
    result = await _get_conn(ctx).send_command(
        "export.screenshot",
        {"filepath": filepath, "width": width, "height": height},
    )
    return json.dumps(result, indent=2)


@mcp.tool(
    name="paraview_export_data",
    description=(
        "Export a named source's data to a file. "
        "The output format is determined by the file extension (e.g. .vtu, .csv, .vtk)."
    ),
)
async def export_data(ctx: Context, name: str, filepath: str) -> str:
    result = await _get_conn(ctx).send_command(
        "export.data", {"name": name, "filepath": filepath}
    )
    return json.dumps(result, indent=2)


# -- Python execution tool --


@mcp.tool(
    name="paraview_python_exec",
    description=(
        "Execute a Python script in the ParaView bridge context. "
        "The script has access to 'paraview.simple' as 'pvs' and an 'args' dict "
        "with any supplied arguments. Set '__result__' to return a JSON-serializable value. "
        "Returns result, stdout, stderr, error, and execution duration."
    ),
)
async def python_exec(
    ctx: Context,
    code: str,
    args: dict | None = None,
) -> str:
    params: dict[str, Any] = {"code": code}
    if args is not None:
        params["args"] = args
    result = await _get_conn(ctx).send_command("python.execute", params)
    return json.dumps(result, indent=2)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
