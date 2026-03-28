"""ParaView MCP Server — External MCP server that bridges AI assistants to ParaView."""

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from paraview_mcp_server.headless import HeadlessPvpythonExecutor, HeadlessJobManager

logger = logging.getLogger(__name__)

PARAVIEW_HOST = "127.0.0.1"
PARAVIEW_PORT = 9876
HEADLESS_JOB_MANAGER = HeadlessJobManager()


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


# ======================================================================
# Scene / session tools
# ======================================================================


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


# ======================================================================
# Data loading tools
# ======================================================================


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


# ======================================================================
# Filter tools — basic
# ======================================================================


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


# ======================================================================
# Filter tools — advanced
# ======================================================================


@mcp.tool(
    name="paraview_filter_calculator",
    description=(
        "Apply a Calculator filter to a named source. "
        "Provide a mathematical expression (e.g. 'Pressure * 2') and an "
        "optional result array name (default: 'Result')."
    ),
)
async def filter_calculator(
    ctx: Context,
    input: str,
    expression: str,
    result_name: str = "Result",
    attribute_type: str = "Point Data",
) -> str:
    result = await _get_conn(ctx).send_command(
        "filter.calculator",
        {
            "input": input,
            "expression": expression,
            "result_name": result_name,
            "attribute_type": attribute_type,
        },
    )
    return json.dumps(result, indent=2)


@mcp.tool(
    name="paraview_filter_stream_tracer",
    description=(
        "Apply a Stream Tracer filter to a named vector source. "
        "Generates streamlines from seed points."
    ),
)
async def filter_stream_tracer(
    ctx: Context,
    input: str,
    seed_type: str = "Point Cloud",
    num_points: int = 100,
    max_length: float = 1.0,
) -> str:
    result = await _get_conn(ctx).send_command(
        "filter.stream_tracer",
        {
            "input": input,
            "seed_type": seed_type,
            "num_points": num_points,
            "max_length": max_length,
        },
    )
    return json.dumps(result, indent=2)


@mcp.tool(
    name="paraview_filter_glyph",
    description=(
        "Apply a Glyph filter to a named source. "
        "Glyphs visualize vector data using arrows, spheres, etc."
    ),
)
async def filter_glyph(
    ctx: Context,
    input: str,
    glyph_type: str = "Arrow",
    scale_array: str | None = None,
    scale_factor: float = 1.0,
) -> str:
    params: dict[str, Any] = {
        "input": input,
        "glyph_type": glyph_type,
        "scale_factor": scale_factor,
    }
    if scale_array is not None:
        params["scale_array"] = scale_array
    result = await _get_conn(ctx).send_command("filter.glyph", params)
    return json.dumps(result, indent=2)


# ======================================================================
# Display / coloring tools
# ======================================================================


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


@mcp.tool(
    name="paraview_display_set_opacity",
    description="Set the opacity (0.0 = fully transparent, 1.0 = fully opaque) of a named source.",
)
async def display_set_opacity(ctx: Context, name: str, opacity: float) -> str:
    result = await _get_conn(ctx).send_command(
        "display.set_opacity", {"name": name, "opacity": opacity}
    )
    return json.dumps(result, indent=2)


@mcp.tool(
    name="paraview_display_rescale_transfer_function",
    description="Rescale the color transfer function of a named source to fit the current data range.",
)
async def display_rescale_transfer_function(ctx: Context, name: str) -> str:
    result = await _get_conn(ctx).send_command(
        "display.rescale_transfer_function", {"name": name}
    )
    return json.dumps(result, indent=2)


# ======================================================================
# View / camera tools
# ======================================================================


@mcp.tool(
    name="paraview_view_reset_camera",
    description="Reset the camera in the active ParaView render view to fit all visible sources.",
)
async def view_reset_camera(ctx: Context) -> str:
    result = await _get_conn(ctx).send_command("view.reset_camera")
    return json.dumps(result, indent=2)


@mcp.tool(
    name="paraview_view_set_camera",
    description=(
        "Set the camera position, focal point, and view-up vector. "
        "Each parameter is a [x, y, z] list. Optionally set parallel_scale for orthographic views."
    ),
)
async def view_set_camera(
    ctx: Context,
    position: list[float] | None = None,
    focal_point: list[float] | None = None,
    view_up: list[float] | None = None,
    parallel_scale: float | None = None,
) -> str:
    params: dict[str, Any] = {}
    if position is not None:
        params["position"] = position
    if focal_point is not None:
        params["focal_point"] = focal_point
    if view_up is not None:
        params["view_up"] = view_up
    if parallel_scale is not None:
        params["parallel_scale"] = parallel_scale
    result = await _get_conn(ctx).send_command("view.set_camera", params)
    return json.dumps(result, indent=2)


@mcp.tool(
    name="paraview_view_set_background",
    description=(
        "Set the background color of the active render view. "
        "Provide color as [r, g, b] with values 0-1. "
        "Optionally provide color2 for a gradient background."
    ),
)
async def view_set_background(
    ctx: Context,
    color: list[float],
    color2: list[float] | None = None,
) -> str:
    params: dict[str, Any] = {"color": color}
    if color2 is not None:
        params["color2"] = color2
    result = await _get_conn(ctx).send_command("view.set_background", params)
    return json.dumps(result, indent=2)


# ======================================================================
# Export tools
# ======================================================================


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


@mcp.tool(
    name="paraview_export_animation",
    description=(
        "Export an animation of the current ParaView scene. "
        "The output format is determined by the file extension (e.g. .avi, .ogv, .png for frame series). "
        "Default resolution is 1920×1080, frame rate 15 fps."
    ),
)
async def export_animation(
    ctx: Context,
    filepath: str,
    width: int = 1920,
    height: int = 1080,
    frame_rate: int = 15,
) -> str:
    result = await _get_conn(ctx).send_command(
        "export.animation",
        {"filepath": filepath, "width": width, "height": height, "frame_rate": frame_rate},
    )
    return json.dumps(result, indent=2)


# ======================================================================
# Python execution tools
# ======================================================================


@mcp.tool(
    name="paraview_python_exec",
    description=(
        "Execute a Python script in the ParaView bridge context synchronously. "
        "Provide either 'code' (inline Python string) or 'script_path' (path to a .py file), not both. "
        "The script has access to 'paraview.simple' as 'pvs' and an 'args' dict "
        "with any supplied arguments. Set '__result__' to return a JSON-serializable value. "
        "Returns result, stdout, stderr, error, and execution duration. "
        "Use transport='bridge' for the live bridge session, or transport='headless' "
        "to run in a separate pvpython process."
    ),
)
async def python_exec(
    ctx: Context,
    code: str | None = None,
    script_path: str | None = None,
    args: dict | None = None,
    timeout_seconds: int | None = None,
    transport: str = "bridge",
) -> str:
    if transport == "headless":
        executor = HeadlessPvpythonExecutor()
        result = await executor.execute(
            code=code,
            script_path=script_path,
            args=args,
            timeout_seconds=timeout_seconds,
        )
    else:
        params: dict[str, Any] = {}
        if code is not None:
            params["code"] = code
        if script_path is not None:
            params["script_path"] = script_path
        if args is not None:
            params["args"] = args
        if timeout_seconds is not None:
            params["timeout_seconds"] = timeout_seconds
        result = await _get_conn(ctx).send_command("python.execute", params)
    return json.dumps(result, indent=2)


@mcp.tool(
    name="paraview_python_exec_async",
    description=(
        "Start a long-running Python script in ParaView asynchronously. "
        "Same parameters as paraview_python_exec. Returns a job_id immediately. "
        "Use paraview_job_status to poll for completion, and paraview_job_cancel to abort. "
        "Uses transport='headless' to run in a separate pvpython process."
    ),
)
async def python_exec_async(
    ctx: Context,
    code: str | None = None,
    script_path: str | None = None,
    args: dict | None = None,
    timeout_seconds: int | None = None,
) -> str:
    executor = HeadlessPvpythonExecutor()
    job_id = await HEADLESS_JOB_MANAGER.create_job(
        executor,
        code=code,
        script_path=script_path,
        args=args,
        timeout_seconds=timeout_seconds,
    )
    return json.dumps({"job_id": job_id}, indent=2)


@mcp.tool(
    name="paraview_job_status",
    description=(
        "Get the status of an async ParaView job. Returns job_id, status "
        "(queued/running/succeeded/failed/cancelled), timestamps, result, stdout, stderr, and error. "
        "Poll this after starting a job with paraview_python_exec_async."
    ),
)
async def job_status(ctx: Context, job_id: str) -> str:
    result = HEADLESS_JOB_MANAGER.get_status(job_id)
    return json.dumps(result, indent=2)


@mcp.tool(
    name="paraview_job_cancel",
    description=(
        "Cancel a running or queued async ParaView job."
    ),
)
async def job_cancel(ctx: Context, job_id: str) -> str:
    result = await HEADLESS_JOB_MANAGER.cancel(job_id)
    return json.dumps(result, indent=2)


@mcp.tool(
    name="paraview_job_list",
    description="List known async ParaView jobs with their IDs, statuses, and creation timestamps.",
)
async def job_list(ctx: Context) -> str:
    result = HEADLESS_JOB_MANAGER.list_jobs()
    return json.dumps(result, indent=2)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
