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
│  · 34 MCP tools        │
│  · ParaViewConnection  │
│  · HeadlessPvpythonExecutor │
│  · HeadlessJobManager  │
└──────────┬─────────────┘
           │ JSON / TCP localhost:9876
           │ (newline-delimited JSON)
┌──────────▼─────────────┐
│  ParaView bridge       │  Runs in pvpython
│  paraview_mcp_bridge/  │  connected to pvserver
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

### GUI and Qt ownership

In the server-backed GUI launcher, the ParaView GUI and the bridge are two
different client processes connected to the same `pvserver`:

- `paraview-real` owns the visible Qt application, layouts, panels, and top-level
  windows.
- `pvpython` owns the MCP bridge process and the Python command handler.
- `pvserver` owns the shared pipeline and server-side data objects.

The default `pvpython` bridge is therefore not a GUI automation process. It may
not have Qt bindings (`PySide6`, `PyQt5`, or `qtpy`) available, and it cannot
reliably enumerate or close Qt widgets from the visible ParaView GUI. It can
create and modify pipeline proxies and server-side views.

This distinction matters for rendering commands. A script that calls
`GetActiveViewOrCreate("RenderView")`, `Show()`, or `Render()` from the
`pvpython` bridge can create a detached VTK render window if no GUI-bound render
view is active in that bridge process. If that happens, cleanup should target the
server-side `RenderView`/layout or the OS window manager; Qt widget cleanup is
only available when using the in-GUI bridge started from ParaView's Python
Shell.

---

## Components

### External MCP server (`src/paraview_mcp_server/`)

| Module | Responsibility |
|---|---|
| `server.py` | FastMCP stdio server; 34 tool definitions; `ParaViewConnection` async TCP client |
| `headless.py` | `HeadlessPvpythonExecutor` — runs scripts in a separate `pvpython` process; `HeadlessJobManager` — tracks async jobs |
| `launcher.py` | Starts `pvserver`, the GUI client and the bridge; supervises the bridge |
| `__init__.py` | Re-exports `main()`, `HeadlessPvpythonExecutor`, `HeadlessJobManager`, `__version__` |

### ParaView bridge (`src/paraview_mcp_bridge/`)

| Module | Responsibility |
|---|---|
| `server.py` | Threaded TCP socket server, newline-delimited JSON framing |
| `gui_bridge.py` | Non-blocking helpers for starting/stopping the bridge inside ParaView GUI |
| `command_handler.py` | Command registry mapping 27 command names to `paraview.simple` calls |
| `execution.py` | `execute_code()` — trusted local Python execution with timeout, bounded thread-routed output capture, and optional script path validation |
| `models.py` | Dependency-free parameter validation for every bridge command |
| `runtime.py` | Private state directory and the local auth token shared with the MCP server |
| `__init__.py` | Package marker |

The bridge package deliberately imports nothing outside the standard library:
it runs inside ParaView's own Python, which has neither `mcp` nor `pydantic`.
Its name is project-specific rather than a generic top-level `bridge`, which
would collide with any other package claiming that name in site-packages.

---

## Communication protocol

Every message is a single JSON object terminated by a newline (`\n`).

### Request

```json
{
  "id": "uuid-string",
  "command": "scene.get_info",
  "params": {},
  "token": "local-bridge-token"
}
```

`token` must match the secret the bridge wrote to its token file at startup
(see [Authentication](#authentication)). Requests are capped at 8 MB; a client
that sends more without a newline is disconnected.

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

## Tool namespaces (34 tools)

### Session lifecycle (3, MCP-only)
| MCP tool | Description |
|---|---|
| `paraview_session_status` | Report bridge reachability and managed session state |
| `paraview_session_start` | Start a clean GUI-backed ParaView MCP session |
| `paraview_session_stop` | Stop the session process started by this MCP server |

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

## Authentication

The bridge accepts newline-delimited JSON on a TCP port and can execute
arbitrary Python inside ParaView. Binding to loopback keeps it off the network,
but on a multi-user host *every local account* can reach loopback, so the
socket is not self-protecting.

At startup the bridge generates a random token and writes it to a file only the
owning user can read:

```
$XDG_RUNTIME_DIR/paraview-mcp-server/bridge.token   (mode 0600)
```

falling back to `$XDG_STATE_HOME` or `~/.local/state`. The MCP server and
`scripts/paraview_bridge_request.py` read the same file, so no configuration is
needed when both run as the same user. Requests without a matching `token` are
rejected.

Overrides:

| Variable | Effect |
|---|---|
| `PARAVIEW_MCP_TOKEN` | Use this token instead of reading the file |
| `PARAVIEW_MCP_TOKEN_FILE` | Read/write the token at this path |
| `PARAVIEW_MCP_STATE_DIR` | Base directory for the token and launcher log |
| `PARAVIEW_MCP_DISABLE_AUTH=1` | Start the bridge with no authentication |

`PARAVIEW_MCP_DISABLE_AUTH=1` returns to the previous behaviour, in which any
local process can execute Python in the ParaView session. Binding `--host` to
anything other than loopback logs a warning for the same reason.

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

1. User starts the ParaView side with `paraview-mcp-launch`, or an MCP client
   calls `paraview_session_start`.
2. The launcher starts `pvserver --multi-clients`.
3. The launcher connects the ParaView GUI as the first client.
4. The launcher starts `pvpython scripts/start_paraview_bridge.py --server-host ...`,
   which connects to the same `pvserver` and binds the MCP TCP bridge on
   `127.0.0.1:9876`.
   This separate bridge is pipeline-only for render-view operations by default:
   it refuses display, camera, screenshot, animation, and render-related
   `python.execute` calls to avoid detached VTK windows.
5. User starts an MCP client (Claude Desktop, Codex CLI, etc.)
6. MCP client spawns `paraview-mcp-server` over stdio.
7. MCP server connects to bridge on startup (or lazy-connects on first tool call).
8. User issues a natural language request → client calls an MCP tool → server
   forwards as JSON → bridge dispatches → returns result.
9. User exits ParaView, presses Ctrl+C in the launcher terminal, or calls
   `paraview_session_stop` for sessions started by the MCP server.

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

The bridge endpoint defaults to `127.0.0.1:9876` and is overridable:

```bash
export PARAVIEW_MCP_BRIDGE_HOST=127.0.0.1
export PARAVIEW_MCP_BRIDGE_PORT=9876
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
│   ├── paraview_mcp_server/
│   │   ├── __init__.py
│   │   ├── server.py            # 34 MCP tools + ParaViewConnection
│   │   ├── launcher.py          # pvserver + GUI + bridge startup
│   │   └── headless.py          # HeadlessPvpythonExecutor + HeadlessJobManager
│   └── paraview_mcp_bridge/
│       ├── __init__.py
│       ├── server.py            # TCP bridge server
│       ├── gui_bridge.py        # in-GUI bridge polled from ParaView's event loop
│       ├── command_handler.py   # 27-command registry
│       ├── models.py            # parameter validation
│       ├── runtime.py           # state dir + auth token
│       └── execution.py         # trusted local python.execute helper
├── scripts/
│   ├── start_paraview_bridge.py
│   ├── start_paraview_gui_bridge.py
│   ├── paraview_bridge_request.py
│   └── library/
├── demos/
│   ├── scenarios.py
│   └── run_scenarios.py
├── docs/
│   ├── architecture.md
│   ├── demos.md
│   └── python-execute-design.md
└── tests/
    ├── conftest.py
    ├── test_server.py
    ├── test_protocol.py
    ├── test_runtime.py
    └── test_command_handler.py
```
