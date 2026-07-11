# ParaView MCP Server

**Control ParaView with AI assistants through the Model Context Protocol.**

`paraview-mcp-python` provides an MCP server plus a ParaView-side bridge so
AI assistants such as Codex CLI and Claude Desktop can inspect a ParaView
session, open datasets, apply filters, color data, run ParaView Python, and
export screenshots.

The command installed for MCP clients is still:

```bash
paraview-mcp-server
```

<img width="1280" height="720" alt="maxresdefault" src="https://github.com/user-attachments/assets/6e21f408-72b6-4523-a527-55b283b9e274" />

## What Parts Are There?

There are four moving pieces in the GUI workflow:

| Part | Runs where | Purpose |
|---|---|---|
| **MCP client** | Codex CLI, Claude Desktop, or another MCP host | Starts the MCP server and calls tools. |
| **MCP server** | Normal Python environment | Speaks MCP over stdio and forwards tool calls to ParaView over TCP. |
| **ParaView bridge** | `pvpython` process | Receives TCP JSON commands and executes `paraview.simple` operations. |
| **ParaView runtime** | `pvserver` plus a ParaView GUI client | Owns the shared ParaView session that the GUI and bridge both use. |

ParaView is not Blender: Python plugins and VTK timer callbacks are pipeline
extension mechanisms, not a safe general-purpose remote-control hook for a live
GUI process. The supported GUI workflow here uses ParaView's client/server
model. `paraview-mcp-launch` starts a local `pvserver`, connects the ParaView
GUI as the first client, then connects a `pvpython` bridge client to the same
session.

```
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

Why a ParaView-side bridge? ParaView's useful automation API is
`paraview.simple`, and it must execute inside a ParaView Python runtime. The
MCP server itself is only a protocol adapter; it cannot modify a ParaView
session unless a ParaView-side bridge is running.

For live GUI modification, use:

```text
Codex/Claude -> MCP server -> pvpython bridge -> pvserver <- ParaView GUI
```

For headless automation, use:

```text
Codex/Claude -> MCP server -> bridge inside pvpython -> headless ParaView runtime
```

See [`docs/architecture.md`](docs/architecture.md) for a full diagram, protocol reference,
and tool namespace table.

---

## Install

### Option A: Install the MCP server from PyPI

Use this when you only need the MCP server executable in your normal Python
environment:

```bash
pip install paraview-mcp-python
```

This installs:

```bash
paraview-mcp-server
paraview-mcp-launch
```

### Option B: Clone this repository for the ParaView bridge

The bridge code must be available to ParaView's Python runtime. For live GUI
control and local development, clone the repository:

```bash
git clone https://github.com/djeada/paraview-mcp-server.git
cd paraview-mcp-server
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
```

This creates:

```bash
.venv/bin/paraview-mcp-server
.venv/bin/paraview-mcp-launch
```

---

## Start Everything

Start the ParaView side with one command:

```bash
cd /path/to/paraview-mcp-server
paraview-mcp-launch
```

For a local editable checkout:

```bash
.venv/bin/paraview-mcp-launch
```

Expected output:

```text
ParaView MCP bridge ready on 127.0.0.1:9876
Launching ParaView GUI connected to cs://127.0.0.1:11111
```

Keep that terminal running. Closing it stops the GUI, bridge, and local
`pvserver` session.

MCP clients can also start a clean GUI-backed session by calling
`paraview_session_start`. If it reports `existing_bridge_not_managed`, stop the
old bridge-only ParaView processes and start again with `paraview-mcp-launch` or
`paraview_session_start`; the GUI client must connect before the `pvpython`
bridge.

### Optional: Start a Headless `pvpython` Bridge

Use this only when you do not need to modify an already-open ParaView GUI:

```bash
cd /path/to/paraview-mcp-server
pvpython scripts/start_paraview_bridge.py
```

Expected output:

```text
ParaView bridge ready on 127.0.0.1:9876
```

Keep that terminal running. This controls the `pvpython` session, not a GUI
window opened separately.

### GUI/Qt Limitations

The default live bridge runs in a separate `pvpython` process connected to the
same `pvserver` session as the ParaView GUI. It is not running inside the GUI's
Qt event loop. In that mode, the bridge can safely modify the ParaView pipeline,
but it does not control render views by default.

This is intentional. Calling render-view APIs such as
`GetActiveViewOrCreate("RenderView")`, `Show()`, `Render()`, `SaveScreenshot()`,
or camera/background tools from a separate `pvpython` client can open a detached
VTK render window instead of using the visible ParaView GUI layout. The bridge
therefore blocks display, camera, screenshot, animation, and render-related
`python.execute` calls unless it is running inside the GUI bridge.

For pipeline automation from the default bridge, create or update sources and
filters first. Fixed tools return `shown: false` when display is skipped.

For GUI-window automation, start the experimental in-GUI bridge from ParaView's
Python Shell:

```bash
scripts/start_paraview_gui_bridge.py
```

To deliberately allow the old detached-window behavior for debugging, set
`PARAVIEW_MCP_ALLOW_DETACHED_RENDER_WINDOW=1` before starting the bridge.

### Verify the Bridge Directly

Before involving an MCP client, send one raw bridge command:

```bash
python scripts/paraview_bridge_request.py scene.get_info
```

Expected response shape:

```json
{
  "success": true,
  "result": {
    "source_count": 0,
    "active_view_type": "RenderView"
  }
}
```

If this fails, fix the bridge before configuring Codex or Claude.

### Register the MCP Server with Codex CLI

If you installed from PyPI:

```bash
codex mcp add paraview -- paraview-mcp-server
codex mcp list
```

If you are using the local repository:

```bash
codex mcp add paraview -- /absolute/path/to/paraview-mcp-server/.venv/bin/paraview-mcp-server
codex mcp list
```

Codex starts the MCP server automatically when needed. The ParaView bridge
must already be running separately.

### Register with Claude Desktop

**Claude Desktop** — add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "paraview": {
      "command": "/absolute/path/to/.venv/bin/paraview-mcp-server"
    }
  }
}
```

For a PyPI install, use the absolute path returned by:

```bash
which paraview-mcp-server
```

Restart Claude Desktop after editing the config.

### Verify Through Your MCP Client

With the bridge still running, ask your MCP client:

```text
List all sources in the current ParaView session.
```

The client should call `paraview_scene_list_sources` and return the current
ParaView pipeline sources from the server-backed GUI session started by
`paraview-mcp-launch`.

---

## What Can It Control?

There are two levels of control:

1. **Fixed MCP tools** for common workflows: scene inspection, loading data,
   filters, display/coloring, camera, screenshots, data export, and animation
   export.
2. **Python execution** through `paraview_python_exec`, which can run trusted
   local Python inside the ParaView bridge session. Use this for anything not
   covered by a fixed tool, including arbitrary `paraview.simple` scripts.

So the fixed tool list is intentionally finite, but the Python execution tool
is the general escape hatch for the broader ParaView API.

---

## Example prompts

Once both processes are running and your MCP client is configured:

- *"List all sources in the current ParaView session."*
- *"Open `/data/disk_out_ref.ex2`."*
- *"Create a slice through X = 0 of the disk dataset."*
- *"Color the dataset by Pressure."*
- *"Save a screenshot to `/tmp/view.png`."*
- *"Apply a contour filter on Pressure with isovalues 0.5 and 1.0."*
- *"Set the camera to position [10, 5, 5] looking at the origin."*
- *"Set the background to a gradient from white to dark blue."*
- *"Export an animation to `/tmp/anim.avi`."*

---

## Tool reference (34 tools)

### Scene / session
| Tool | Description |
|---|---|
| `paraview_session_status` | Report bridge reachability and managed GUI session state |
| `paraview_session_start` | Start a clean GUI-backed ParaView MCP session |
| `paraview_session_stop` | Stop the session process started by this MCP server |
| `paraview_scene_get_info` | Session info: source count, active view type |
| `paraview_scene_list_sources` | List all pipeline sources |
| `paraview_scene_list_views` | List open render views |
| `paraview_source_get_properties` | Properties of a named source |

### Data loading
| Tool | Description |
|---|---|
| `paraview_source_open_file` | Open a dataset (VTK, VTU, ExodusII, CSV, …) |
| `paraview_source_delete` | Remove a source from the pipeline |
| `paraview_source_rename` | Rename a source |

### Filters — basic
| Tool | Description |
|---|---|
| `paraview_filter_slice` | Slice filter with origin + normal |
| `paraview_filter_clip` | Clip filter with origin + normal |
| `paraview_filter_contour` | Contour / isosurface by scalar array and values |
| `paraview_filter_threshold` | Threshold filter by scalar range |

### Filters — advanced
| Tool | Description |
|---|---|
| `paraview_filter_calculator` | Calculator filter with expression |
| `paraview_filter_stream_tracer` | Stream Tracer for vector field streamlines |
| `paraview_filter_glyph` | Glyph filter for vector visualization |

### Display / coloring
| Tool | Description |
|---|---|
| `paraview_display_show` | Make a source visible |
| `paraview_display_hide` | Hide a source |
| `paraview_display_color_by` | Color by a data array |
| `paraview_display_set_representation` | Surface / Wireframe / Points / Volume |
| `paraview_display_set_opacity` | Set opacity (0.0 – 1.0) |
| `paraview_display_rescale_transfer_function` | Rescale color map to data range |

### Camera / view
| Tool | Description |
|---|---|
| `paraview_view_reset_camera` | Fit all visible sources in the view |
| `paraview_view_set_camera` | Set camera position, focal point, view-up |
| `paraview_view_set_background` | Set solid or gradient background color |

### Export
| Tool | Description |
|---|---|
| `paraview_export_screenshot` | Save a PNG or JPEG screenshot |
| `paraview_export_data` | Export source data to VTK/CSV/… |
| `paraview_export_animation` | Export animation to video/frames |

### Python execution
| Tool | Description |
|---|---|
| `paraview_python_exec` | Run Python in bridge or headless pvpython |
| `paraview_python_exec_async` | Start a long-running Python job (headless) |

### Job management
| Tool | Description |
|---|---|
| `paraview_job_status` | Get status of an async job |
| `paraview_job_cancel` | Cancel a running async job |
| `paraview_job_list` | List all known async jobs |

---

## Python execution

`paraview_python_exec` is the escape hatch for workflows that need more than the fixed
tool set. The script runs in the bridge process where `paraview.simple` is already imported.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `code` | `str` | Inline Python source (mutually exclusive with `script_path`) |
| `script_path` | `str` | Path to a `.py` file (mutually exclusive with `code`) |
| `args` | `dict` | Arguments exposed as `args` inside the script |
| `timeout_seconds` | `int` | Cooperative timeout (default: 30s) |
| `transport` | `str` | `"bridge"` (default) or `"headless"` (separate pvpython process) |

**Execution namespace:**

| Variable | Type | Description |
|---|---|---|
| `pvs` | module | `paraview.simple` |
| `args` | dict | Arguments from the `args` parameter |
| `__result__` | Any | Set this to return a JSON-serialisable value |

**Example:**

```python
# Open a file and create a slice
src = pvs.OpenDataFile(args["filepath"])
view = pvs.GetActiveViewOrCreate("RenderView")
pvs.Show(src, view)
filt = pvs.Slice(Input=src)
filt.SliceType.Origin = [0, 0, 0]
filt.SliceType.Normal = [1, 0, 0]
pvs.Show(filt, view)
pvs.ResetCamera(view)
__result__ = {"done": True}
```

See [`docs/python-execute-design.md`](docs/python-execute-design.md) for the full design,
schema reference, and more examples.

---

## Async job execution

For long-running pipelines, use `paraview_python_exec_async`:

1. Start a job → returns `job_id` immediately
2. Poll with `paraview_job_status` → check `status` field
3. Cancel with `paraview_job_cancel` if needed

Async jobs run in a separate headless `pvpython` process via `HeadlessPvpythonExecutor`.

---

## Troubleshooting

### ParaView is connected, but MCP cannot close or inspect a window

If the Pipeline Browser shows `cs://127.0.0.1:11111`, the ParaView GUI is
connected to `pvserver`. That does not mean the MCP TCP bridge is running or
that MCP has access to GUI Qt widgets. Verify the bridge separately:

```bash
python scripts/paraview_bridge_request.py scene.get_info
```

If a second VTK render window appears and refuses to close, it was likely
created by the `pvpython` bridge through `GetActiveViewOrCreate("RenderView")`
or a display/render command. The bridge normally cannot close this via Qt
because the default runtime is not the GUI process and often has no Qt Python
bindings. Delete the server-side view/layout, use the window manager, or restart
the ParaView-side bridge. For workflows that must control GUI windows directly,
use the in-GUI bridge from ParaView's Python Shell.

---

## Python execution trust model

- **Trusted local execution** — `paraview_python_exec` can run arbitrary Python available to the active
  ParaView Python process, including imports and full `paraview.simple` workflows.
- **Output bounding** — stdout/stderr capped at **50 KB**.
- **Cooperative timeout** — default 30 seconds per script execution.
- **Script path validation** — optionally restrict execution to approved root directories.
- The bridge runs inside ParaView's Python runtime with the same trust level as that local session.
- This is a local desktop automation tool — not a public API sandbox.

---

## Development

### Install dev dependencies

```bash
pip install -e ".[dev]"
```

### Run tests

```bash
pytest tests/
```

Tests do **not** require ParaView to be installed. The command handler tests patch
`_import_pv` with a `MagicMock` that mimics the `paraview.simple` API.

### Send a raw bridge command (for debugging)

```bash
python scripts/paraview_bridge_request.py scene.get_info
python scripts/paraview_bridge_request.py source.open_file --params '{"filepath":"/data/disk.vtu"}'
python scripts/paraview_bridge_request.py export.screenshot --params '{"filepath":"/tmp/shot.png"}'
```

---

## Project structure

```
paraview-mcp-server/
├── pyproject.toml
├── src/
│   └── paraview_mcp_server/
│       ├── __init__.py          # Re-exports main()
│       ├── server.py            # FastMCP stdio server (34 tools)
│       ├── launcher.py          # Starts pvserver, GUI, and bridge together
│       └── headless.py          # Headless pvpython executor + job manager
├── bridge/
│   ├── __init__.py
│   ├── server.py                # TCP socket bridge server
│   ├── gui_bridge.py            # Experimental in-GUI bridge helpers
│   ├── command_handler.py       # Command registry + paraview.simple handlers (27 commands)
│   └── execution.py             # trusted local python.execute helper
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
    ├── test_protocol.py         # Wire encoding, fake bridge integration
    └── test_command_handler.py  # All 27 handlers + execution controls
```

---

## License

MIT — see [LICENSE](LICENSE).
