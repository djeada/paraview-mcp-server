# paraview-mcp-server

**Control ParaView with AI assistants through the Model Context Protocol.**

`paraview-mcp-server` is a two-process bridge that lets AI assistants such as Claude Desktop
and Codex CLI open datasets, apply filters, color data, and export screenshots in ParaView
using natural language.

---

## How it works

```
MCP Client (Claude Desktop, Codex CLI, …)
      ⇅  stdio
paraview-mcp-server            ← thin MCP server, defines 31 tools
      ⇅  JSON / TCP localhost:9876
ParaView bridge (pvpython)     ← dispatches commands with paraview.simple
      ⇅
paraview.simple / servermanager
```

- The **MCP server** is a normal Python package. It speaks MCP over stdio and forwards
  every tool call as a JSON request to the bridge over a local TCP socket.
- The **bridge** runs inside `pvpython`. It receives JSON commands, dispatches them through
  a command registry, calls `paraview.simple`, and returns JSON results.
- Neither process depends on the other's code at import time.
- A **headless pvpython executor** lets the MCP server run scripts in a separate
  `pvpython` process for long-running or async workflows (no bridge needed).

See [`docs/architecture.md`](docs/architecture.md) for a full diagram, protocol reference,
and tool namespace table.

---

## Quick start

### 1. Install the MCP server

```bash
git clone https://github.com/djeada/paraview-mcp-server.git
cd paraview-mcp-server
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
```

### 2. Start the ParaView bridge

In a terminal that has `pvpython` on `PATH`:

```bash
pvpython scripts/start_paraview_bridge.py
# → ParaView bridge ready on 127.0.0.1:9876
```

The bridge listens for JSON commands from the MCP server.

### 3. Register the MCP server with your AI client

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

**Codex CLI:**

```bash
codex mcp add paraview -- /absolute/path/to/.venv/bin/paraview-mcp-server
```

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

## Tool reference (31 tools)

### Scene / session
| Tool | Description |
|---|---|
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

## Safety model

- **Blocked modules** — scripts cannot import `subprocess`, `shutil`, `socket`, `ctypes`,
  `multiprocessing`, `webbrowser`, or several network-facing stdlib modules.
- **Output bounding** — stdout/stderr capped at **50 KB**.
- **Cooperative timeout** — default 30 seconds per script execution.
- **Script path validation** — optionally restrict execution to approved root directories.
- The bridge runs inside `pvpython` with the same trust level as a local ParaView session.
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
│       ├── server.py            # FastMCP stdio server (31 tools)
│       └── headless.py          # Headless pvpython executor + job manager
├── bridge/
│   ├── __init__.py
│   ├── server.py                # TCP socket bridge server
│   ├── command_handler.py       # Command registry + paraview.simple handlers (27 commands)
│   └── execution.py             # python.execute helper with safety controls
├── scripts/
│   ├── start_paraview_bridge.py
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
    ├── test_server.py           # 31 tools, connection, headless, async jobs
    ├── test_protocol.py         # Wire encoding, fake bridge integration
    └── test_command_handler.py  # All 27 handlers + safety controls
```

---

## License

MIT — see [LICENSE](LICENSE).