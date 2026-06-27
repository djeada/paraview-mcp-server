# Architecture

## Overview

```
┌────────────────────────┐
│  MCP Client            │  Claude Desktop / Codex CLI / any MCP client
│  (Claude, Codex, …)    │
└──────────┬─────────────┘
           │ stdio (MCP protocol)
┌──────────▼─────────────┐
│  paraview-mcp-server   │  External Python process
│  src/paraview_mcp_server │
│  · 31 MCP tools        │
│  · ParaViewConnection  │
│  · HeadlessPvpythonExecutor │
│  · HeadlessJobManager  │
└──────────┬─────────────┘
           │ JSON / TCP localhost:9876
           │ (newline-delimited JSON)
┌──────────▼─────────────┐
│  ParaView bridge       │  Runs in pvpython
│  bridge/               │  connected to pvserver
│  · ParaViewBridgeServer│
│  · CommandHandler      │  27 registered commands
│  · execute_code()      │
└──────────┬─────────────┘
           │ ParaView client/server
┌──────────▼─────────────┐
│  pvserver              │  Shared ParaView state
│  ParaView GUI client   │
└────────────────────────┘
```

Alternative headless bridge:

```
MCP Client → paraview-mcp-server → pvpython scripts/start_paraview_bridge.py
```

Alternative headless script transport (no long-running bridge required):

```
┌────────────────────────┐
│  MCP Client            │
└──────────┬─────────────┘
           │ stdio
┌──────────▼─────────────┐
│  paraview-mcp-server   │
│  HeadlessPvpythonExecutor │  ← spawns pvpython subprocess
└──────────┬─────────────┘
           │ subprocess (pvpython)
┌──────────▼─────────────┐
│  pvpython wrapper.py   │
│  paraview.simple       │
└────────────────────────┘
```

---

## Components

### External MCP server (`src/paraview_mcp_server/`)

| Module | Responsibility |
|---|---|
| `server.py` | FastMCP stdio server; 31 tool definitions; `ParaViewConnection` async TCP client |
| `headless.py` | `HeadlessPvpythonExecutor` — runs scripts in a separate `pvpython` process; `HeadlessJobManager` — tracks async jobs |
| `__init__.py` | Re-exports `main()`, `HeadlessPvpythonExecutor`, `HeadlessJobManager` |

### ParaView bridge (`bridge/`)

| Module | Responsibility |
|---|---|
| `server.py` | Threaded TCP socket server, newline-delimited JSON framing |
| `gui_bridge.py` | Non-blocking helpers for starting/stopping the bridge inside ParaView GUI |
| `command_handler.py` | Command registry mapping 27 command names to `paraview.simple` calls |
| `execution.py` | `execute_code()` — trusted local Python execution with timeout, output cap, and optional script path validation |
| `__init__.py` | Package marker |

---

## Communication protocol

Every message is a single JSON object terminated by a newline (`\n`).

### Request

```json
{
  "id": "uuid-string",
  "command": "scene.get_info",
  "params": {}
}
```

### Response (success)

```json
{
  "id": "uuid-string",
  "success": true,
  "result": { "source_count": 3, "active_view_type": "RenderView" }
}
```

### Response (error)

```json
{
  "id": "uuid-string",
  "success": false,
  "error": "Source 'missing' not found in the pipeline"
}
```

---

## Tool namespaces (31 tools)

### Scene / session (4)
| MCP tool | Bridge command | Description |
|---|---|---|
| `paraview_scene_get_info` | `scene.get_info` | Source count, active view |
| `paraview_scene_list_sources` | `scene.list_sources` | All pipeline sources |
| `paraview_scene_list_views` | `scene.list_views` | All render views |
| `paraview_source_get_properties` | `source.get_properties` | Properties of a source |

### Data loading (3)
| MCP tool | Bridge command | Description |
|---|---|---|
| `paraview_source_open_file` | `source.open_file` | Open dataset file |
| `paraview_source_delete` | `source.delete` | Delete source |
| `paraview_source_rename` | `source.rename` | Rename source |

### Filters — basic (4)
| MCP tool | Bridge command | Description |
|---|---|---|
| `paraview_filter_slice` | `filter.slice` | Slice with plane |
| `paraview_filter_clip` | `filter.clip` | Clip with plane |
| `paraview_filter_contour` | `filter.contour` | Isosurface extraction |
| `paraview_filter_threshold` | `filter.threshold` | Scalar range threshold |

### Filters — advanced (3)
| MCP tool | Bridge command | Description |
|---|---|---|
| `paraview_filter_calculator` | `filter.calculator` | Expression-based calculator |
| `paraview_filter_stream_tracer` | `filter.stream_tracer` | Streamline tracing |
| `paraview_filter_glyph` | `filter.glyph` | Vector glyph visualization |

### Display / coloring (6)
| MCP tool | Bridge command | Description |
|---|---|---|
| `paraview_display_show` | `display.show` | Show source |
| `paraview_display_hide` | `display.hide` | Hide source |
| `paraview_display_color_by` | `display.color_by` | Color by array |
| `paraview_display_set_representation` | `display.set_representation` | Surface/Wireframe/… |
| `paraview_display_set_opacity` | `display.set_opacity` | Transparency |
| `paraview_display_rescale_transfer_function` | `display.rescale_transfer_function` | Rescale color map |

### Camera / view (3)
| MCP tool | Bridge command | Description |
|---|---|---|
| `paraview_view_reset_camera` | `view.reset_camera` | Reset camera to fit |
| `paraview_view_set_camera` | `view.set_camera` | Set camera position/orientation |
| `paraview_view_set_background` | `view.set_background` | Solid or gradient background |

### Export (3)
| MCP tool | Bridge command | Description |
|---|---|---|
| `paraview_export_screenshot` | `export.screenshot` | Save PNG/JPEG |
| `paraview_export_data` | `export.data` | Export to VTK/CSV/… |
| `paraview_export_animation` | `export.animation` | Export animation frames/video |

### Python execution (2)
| MCP tool | Bridge command | Description |
|---|---|---|
| `paraview_python_exec` | `python.execute` | Synchronous Python execution |
| `paraview_python_exec_async` | — (headless only) | Async Python job |

### Job management (3, MCP-only)
| MCP tool | Description |
|---|---|
| `paraview_job_status` | Poll async job status |
| `paraview_job_cancel` | Cancel a running job |
| `paraview_job_list` | List all known jobs |

---

## Python execution command

See [`python-execute-design.md`](python-execute-design.md) for the full design.

### Execution flow (bridge transport)

```
MCP client
  → paraview_python_exec(code="…", args={…})
    → ParaViewConnection.send_command("python.execute", {code, args, timeout_seconds})
      → bridge CommandHandler._python_execute
        → execution.execute_code(code, args, timeout_seconds=…)
          → thread: exec(code, namespace)
        ← {result, stdout, stderr, error, duration_seconds, timed_out}
```

### Execution flow (headless transport)

```
MCP client
  → paraview_python_exec(code="…", transport="headless")
    → HeadlessPvpythonExecutor.execute(code=…)
      → pvpython subprocess: wrapper.py
        → exec(code, namespace)
        → print(__PARAVIEW_MCP_RESULT__=payload)
      ← parse payload from stdout
    ← {result, stdout, stderr, error, duration_seconds, timed_out, cancelled}
```

---

## Lifecycle

1. User starts the ParaView side with `paraview-mcp-launch`.
2. The launcher starts `pvserver --multi-clients`.
3. The launcher connects the ParaView GUI as the first client.
4. The launcher starts `pvpython scripts/start_paraview_bridge.py --server-host ...`,
   which connects to the same `pvserver` and binds the MCP TCP bridge on
   `127.0.0.1:9876`.
5. User starts an MCP client (Claude Desktop, Codex CLI, etc.)
6. MCP client spawns `paraview-mcp-server` over stdio.
7. MCP server connects to bridge on startup (or lazy-connects on first tool call).
8. User issues a natural language request → client calls an MCP tool → server
   forwards as JSON → bridge dispatches → returns result.
9. User exits ParaView or presses Ctrl+C in the launcher terminal to stop the
   GUI, bridge, and local `pvserver`.

---

## Configuration

### Server-backed GUI launcher

```bash
paraview-mcp-launch
```

This starts a local `pvserver`, connects the ParaView GUI, then connects a
`pvpython` bridge client to the same server-backed ParaView session.

### Headless Bridge

```bash
pvpython scripts/start_paraview_bridge.py --host 127.0.0.1 --port 9876
```

### MCP server

The host/port are currently constants in `server.py`:

```python
PARAVIEW_HOST = "127.0.0.1"
PARAVIEW_PORT = 9876
```

### Headless pvpython executor

Set the `PVPYTHON_BIN` environment variable to specify a non-default `pvpython` binary:

```bash
export PVPYTHON_BIN=/opt/paraview/bin/pvpython
```

### Claude Desktop

```json
{
  "mcpServers": {
    "paraview": {
      "command": "/path/to/.venv/bin/paraview-mcp-server"
    }
  }
}
```

### Codex CLI

```bash
codex mcp add paraview -- /path/to/.venv/bin/paraview-mcp-server
```

---

## Repository layout

```
paraview-mcp-server/
├── pyproject.toml
├── src/
│   └── paraview_mcp_server/
│       ├── __init__.py
│       ├── server.py            # 31 MCP tools + ParaViewConnection
│       └── headless.py          # HeadlessPvpythonExecutor + HeadlessJobManager
├── bridge/
│   ├── __init__.py
│   ├── server.py                # TCP bridge server
│   ├── command_handler.py       # 27-command registry
│   └── execution.py             # trusted local python.execute helper
├── scripts/
│   ├── start_paraview_bridge.py
│   ├── paraview_bridge_request.py
│   └── library/
├── docs/
│   ├── architecture.md
│   └── python-execute-design.md
└── tests/
    ├── test_server.py
    ├── test_protocol.py
    └── test_command_handler.py
```
