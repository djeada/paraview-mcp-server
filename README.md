# ParaView MCP Server

Control ParaView with AI assistants through the Model Context Protocol (MCP).

`paraview-mcp-python` provides an MCP server and a ParaView-side bridge. MCP clients such as Codex CLI and Claude Desktop can use it to inspect a ParaView session, open datasets, apply filters, color data, run ParaView Python, and export screenshots.

The MCP server command is:

```bash
paraview-mcp-server
```

<img width="1280" height="720" alt="ParaView MCP Server demonstration" src="https://github.com/user-attachments/assets/6e21f408-72b6-4523-a527-55b283b9e274" />

## Architecture

The GUI workflow has four components:

| Component | Runs in | Purpose |
|---|---|---|
| MCP client | Codex CLI, Claude Desktop, or another MCP host | Starts the MCP server and calls its tools. |
| MCP server | Standard Python environment | Communicates over MCP stdio and forwards calls to ParaView over TCP. |
| ParaView bridge | `pvpython` process | Receives JSON commands over TCP and executes `paraview.simple` operations. |
| ParaView runtime | `pvserver` and a ParaView GUI client | Owns the shared session used by the GUI and bridge. |

ParaView Python plugins and VTK timer callbacks are pipeline-extension mechanisms, not a general-purpose remote-control interface for a live GUI process. This project therefore uses ParaView's client/server model.

`paraview-mcp-launch` starts a local `pvserver`, connects the ParaView GUI as the first client, and then connects a `pvpython` bridge to the same session.

```text
┌──────────────────────────────┐      stdio      ┌────────────────────────┐
│ MCP Client                   │ ◄──────────────► │ MCP Server             │
│ Codex / Claude / other host  │                  │ paraview-mcp-server    │
└──────────────────────────────┘                  └──────────┬─────────────┘
                                                              │ JSON/TCP
                                                              │ 127.0.0.1:9876
                                                   ┌──────────▼─────────────┐
                                                   │ ParaView Bridge        │
                                                   │ pvpython client        │
                                                   └──────────┬─────────────┘
                                                              │ ParaView client/server
                                                   ┌──────────▼─────────────┐
                                                   │ pvserver + GUI client  │
                                                   │ shared ParaView state  │
                                                   └────────────────────────┘
```

The bridge is required because `paraview.simple` must run inside a ParaView Python runtime. The MCP server is only a protocol adapter and cannot modify a ParaView session by itself.

Live GUI workflow:

```text
Codex/Claude -> MCP server -> pvpython bridge -> pvserver <- ParaView GUI
```

Headless workflow:

```text
Codex/Claude -> MCP server -> bridge inside pvpython -> headless ParaView runtime
```

See [`docs/architecture.md`](docs/architecture.md) for the complete diagram, protocol reference, and tool namespace table.

## Installation

### Install from PyPI

Use this option when you only need the MCP server executables in your standard Python environment:

```bash
pip install paraview-mcp-python
```

This installs:

```text
paraview-mcp-server
paraview-mcp-launch
```

### Clone the repository

The bridge code must be available to ParaView's Python runtime. Clone the repository for live GUI control or local development:

```bash
git clone https://github.com/djeada/paraview-mcp-server.git
cd paraview-mcp-server
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
```

The executables are then available at:

```text
.venv/bin/paraview-mcp-server
.venv/bin/paraview-mcp-launch
```

## Start a GUI-backed session

From the repository directory, run:

```bash
paraview-mcp-launch
```

For a local editable checkout, you can call the executable directly:

```bash
.venv/bin/paraview-mcp-launch
```

Expected output:

```text
ParaView MCP bridge ready on 127.0.0.1:9876
Launching ParaView GUI connected to cs://127.0.0.1:11111
```

Keep the terminal open. Closing it stops the GUI, bridge, and local `pvserver` session.

An MCP client can also start a clean GUI-backed session with `paraview_session_start`. If it reports `existing_bridge_not_managed`, stop any old bridge-only ParaView processes and restart with `paraview-mcp-launch` or `paraview_session_start`. The GUI client must connect before the `pvpython` bridge.

### Start a headless bridge

Use a headless bridge only when you do not need to modify an already-open ParaView GUI:

```bash
cd /path/to/paraview-mcp-server
pvpython scripts/start_paraview_bridge.py
```

Expected output:

```text
ParaView bridge ready on 127.0.0.1:9876
```

Keep the terminal open. This command controls the `pvpython` session, not a separately opened GUI window.

### GUI and Qt limitations

The default live bridge runs in a separate `pvpython` process connected to the same `pvserver` session as the ParaView GUI. Because it does not run inside the GUI's Qt event loop, it can safely modify the pipeline but does not control render views by default.

Calling APIs such as `GetActiveViewOrCreate("RenderView")`, `Show()`, `Render()`, `SaveScreenshot()`, or camera and background tools from a separate `pvpython` client can create a detached VTK render window instead of modifying the visible GUI layout. To avoid that behavior, the bridge blocks display, camera, screenshot, animation, and render-related `python.execute` calls unless it is running inside the GUI bridge.

For pipeline automation, create or update sources and filters first. Fixed tools return `shown: false` when display is skipped.

For GUI-window automation, start the experimental in-GUI bridge from ParaView's Python Shell:

```bash
scripts/start_paraview_gui_bridge.py
```

To allow detached render windows for debugging, set the following environment variable before starting the bridge:

```bash
PARAVIEW_MCP_ALLOW_DETACHED_RENDER_WINDOW=1
```

## Verify the connection

### Test the bridge directly

Before configuring an MCP client, send a raw bridge command:

```bash
python scripts/paraview_bridge_request.py scene.get_info
```

Expected response:

```json
{
  "success": true,
  "result": {
    "source_count": 0,
    "active_view_type": "RenderView"
  }
}
```

Resolve any bridge errors before configuring Codex or Claude.

### Register with Codex CLI

For a PyPI installation:

```bash
codex mcp add paraview -- paraview-mcp-server
codex mcp list
```

For a local repository:

```bash
codex mcp add paraview -- /absolute/path/to/paraview-mcp-server/.venv/bin/paraview-mcp-server
codex mcp list
```

Codex starts the MCP server when needed. The ParaView bridge must already be running.

### Register with Claude Desktop

Add the server to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "paraview": {
      "command": "/absolute/path/to/.venv/bin/paraview-mcp-server"
    }
  }
}
```

For a PyPI installation, find the absolute command path with:

```bash
which paraview-mcp-server
```

Restart Claude Desktop after editing the configuration.

### Test through the MCP client

With the bridge running, ask the client:

```text
List all sources in the current ParaView session.
```

The client should call `paraview_scene_list_sources` and return the pipeline sources from the server-backed GUI session started by `paraview-mcp-launch`.

## Capabilities

The server provides two levels of control:

1. Fixed MCP tools for scene inspection, data loading, filters, display and coloring, camera control, screenshots, data export, and animation export.
2. Python execution through `paraview_python_exec` for trusted local scripts and workflows not covered by the fixed tools.

The fixed tool set covers common operations. Python execution provides access to the broader `paraview.simple` API.

### Example prompts

- "List all sources in the current ParaView session."
- "Open `/data/disk_out_ref.ex2`."
- "Create a slice through X = 0 of the disk dataset."
- "Color the dataset by Pressure."
- "Save a screenshot to `/tmp/view.png`."
- "Apply a contour filter on Pressure with isovalues 0.5 and 1.0."
- "Set the camera to position [10, 5, 5] looking at the origin."
- "Set the background to a gradient from white to dark blue."
- "Export an animation to `/tmp/anim.avi`."

## Tool reference

The server exposes 34 MCP tools.

### Scene and session

| Tool | Description |
|---|---|
| `paraview_session_status` | Report bridge reachability and managed GUI session state. |
| `paraview_session_start` | Start a clean GUI-backed ParaView MCP session. |
| `paraview_session_stop` | Stop the session process started by this MCP server. |
| `paraview_scene_get_info` | Return session information, including source count and active view type. |
| `paraview_scene_list_sources` | List all pipeline sources. |
| `paraview_scene_list_views` | List open render views. |
| `paraview_source_get_properties` | Return the properties of a named source. |

### Data loading

| Tool | Description |
|---|---|
| `paraview_source_open_file` | Open a dataset such as VTK, VTU, ExodusII, or CSV. |
| `paraview_source_delete` | Remove a source from the pipeline. |
| `paraview_source_rename` | Rename a source. |

### Basic filters

| Tool | Description |
|---|---|
| `paraview_filter_slice` | Create a slice using an origin and normal. |
| `paraview_filter_clip` | Create a clip using an origin and normal. |
| `paraview_filter_contour` | Create contours or isosurfaces from a scalar array and values. |
| `paraview_filter_threshold` | Apply a scalar-range threshold. |

### Advanced filters

| Tool | Description |
|---|---|
| `paraview_filter_calculator` | Apply a Calculator filter with an expression. |
| `paraview_filter_stream_tracer` | Create streamlines for a vector field. |
| `paraview_filter_glyph` | Create glyphs for vector visualization. |

### Display and coloring

| Tool | Description |
|---|---|
| `paraview_display_show` | Make a source visible. |
| `paraview_display_hide` | Hide a source. |
| `paraview_display_color_by` | Color a source by a data array. |
| `paraview_display_set_representation` | Set the representation to Surface, Wireframe, Points, or Volume. |
| `paraview_display_set_opacity` | Set opacity from `0.0` to `1.0`. |
| `paraview_display_rescale_transfer_function` | Rescale the color map to the data range. |

### Camera and view

| Tool | Description |
|---|---|
| `paraview_view_reset_camera` | Fit all visible sources in the view. |
| `paraview_view_set_camera` | Set the camera position, focal point, and view-up vector. |
| `paraview_view_set_background` | Set a solid or gradient background. |

### Export

| Tool | Description |
|---|---|
| `paraview_export_screenshot` | Save a PNG or JPEG screenshot. |
| `paraview_export_data` | Export source data to VTK, CSV, or another supported format. |
| `paraview_export_animation` | Export an animation as video or image frames. |

### Python execution

| Tool | Description |
|---|---|
| `paraview_python_exec` | Run Python in the bridge or a headless `pvpython` process. |
| `paraview_python_exec_async` | Start a long-running Python job in headless mode. |

### Job management

| Tool | Description |
|---|---|
| `paraview_job_status` | Return the status of an asynchronous job. |
| `paraview_job_cancel` | Cancel a running job. |
| `paraview_job_list` | List known asynchronous jobs. |

## Python execution

`paraview_python_exec` handles workflows that need more than the fixed tool set. Scripts run in the bridge process, where `paraview.simple` is already imported.

### Parameters

| Parameter | Type | Description |
|---|---|---|
| `code` | `str` | Inline Python source; mutually exclusive with `script_path`. |
| `script_path` | `str` | Path to a `.py` file; mutually exclusive with `code`. |
| `args` | `dict` | Arguments exposed as `args` inside the script. |
| `timeout_seconds` | `int` | Cooperative timeout in seconds; defaults to `30`. |
| `transport` | `str` | `"bridge"` by default, or `"headless"` for a separate `pvpython` process. |

### Execution namespace

| Variable | Type | Description |
|---|---|---|
| `pvs` | module | The imported `paraview.simple` module. |
| `args` | dict | Arguments supplied through the `args` parameter. |
| `__result__` | Any | Assign a JSON-serializable value to return it to the caller. |

### Example

```python
src = pvs.OpenDataFile(args["filepath"])
view = pvs.GetActiveViewOrCreate("RenderView")
pvs.Show(src, view)

slice_filter = pvs.Slice(Input=src)
slice_filter.SliceType.Origin = [0, 0, 0]
slice_filter.SliceType.Normal = [1, 0, 0]
pvs.Show(slice_filter, view)

pvs.ResetCamera(view)
__result__ = {"done": True}
```

See [`docs/python-execute-design.md`](docs/python-execute-design.md) for the full design, schema reference, and additional examples.

## Asynchronous jobs

Use `paraview_python_exec_async` for long-running pipelines:

1. Start a job and store the returned `job_id`.
2. Check its `status` with `paraview_job_status`.
3. Cancel it with `paraview_job_cancel` when necessary.

Asynchronous jobs run in a separate headless `pvpython` process through `HeadlessPvpythonExecutor`.

## Troubleshooting

### ParaView is connected, but MCP cannot inspect or close a window

A Pipeline Browser connection to `cs://127.0.0.1:11111` confirms that the GUI is connected to `pvserver`. It does not confirm that the MCP TCP bridge is running or that MCP can access GUI Qt widgets.

Verify the bridge separately:

```bash
python scripts/paraview_bridge_request.py scene.get_info
```

A second VTK render window may appear if the `pvpython` bridge calls `GetActiveViewOrCreate("RenderView")` or another display or render command. The default bridge often cannot close that window through Qt because it is not the GUI process and may not include Qt Python bindings.

Delete the server-side view or layout, close the window through the window manager, or restart the ParaView-side bridge. Use the in-GUI bridge for workflows that require direct GUI-window control.

## Python execution trust model

`paraview_python_exec` runs trusted local Python with the permissions of the active ParaView process. This includes imports and unrestricted `paraview.simple` workflows.

Safeguards include:

- stdout and stderr are limited to 50 KB.
- The default cooperative timeout is 30 seconds.
- Script paths can be restricted to approved root directories.

This project is a local desktop automation tool, not a public API sandbox.

## Development

Install development dependencies:

```bash
pip install -e ".[dev]"
```

Run the test suite:

```bash
pytest tests/
```

The tests do not require ParaView. Command-handler tests patch `_import_pv` with a `MagicMock` that mimics the `paraview.simple` API.

Send raw bridge commands for debugging:

```bash
python scripts/paraview_bridge_request.py scene.get_info
python scripts/paraview_bridge_request.py source.open_file --params '{"filepath":"/data/disk.vtu"}'
python scripts/paraview_bridge_request.py export.screenshot --params '{"filepath":"/tmp/shot.png"}'
```

## Project structure

```text
paraview-mcp-server/
├── pyproject.toml
├── src/
│   └── paraview_mcp_server/
│       ├── __init__.py          # Re-exports main()
│       ├── server.py            # FastMCP stdio server (34 tools)
│       ├── launcher.py          # Starts pvserver, GUI, and bridge together
│       └── headless.py          # Headless pvpython executor and job manager
├── bridge/
│   ├── __init__.py
│   ├── server.py                # TCP socket bridge server
│   ├── gui_bridge.py            # Experimental in-GUI bridge helpers
│   ├── command_handler.py       # Command registry and paraview.simple handlers (27 commands)
│   └── execution.py             # Trusted local python.execute helper
├── scripts/
│   ├── start_paraview_bridge.py
│   ├── start_paraview_gui_bridge.py
│   ├── paraview_bridge_request.py
│   └── library/                 # Reusable pvpython snippets
│       ├── open_dataset.py
│       ├── create_slice.py
│       ├── create_contour.py
│       ├── color_by.py
│       ├── reset_camera.py
│       └── save_screenshot.py
├── docs/
│   ├── architecture.md
│   └── python-execute-design.md
└── tests/
    ├── test_server.py           # 34 tools, connection, headless, async jobs
    ├── test_protocol.py         # Wire encoding and fake-bridge integration
    └── test_command_handler.py  # All 27 handlers and execution controls
```

## License

MIT. See [LICENSE](LICENSE).
