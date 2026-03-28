# ParaView MCP Server — Architecture

## Overview

The ParaView MCP Server enables AI assistants (Claude Desktop, Codex CLI, etc.) to control
ParaView through the **Model Context Protocol (MCP)**. It uses a two-process bridge architecture
that keeps the MCP server thin and generic while the ParaView-native logic lives in a dedicated
bridge process.

## Components

```
┌─────────────────┐      stdio       ┌──────────────────────────┐    JSON/TCP     ┌──────────────────────┐
│  Claude Desktop  │ ◄──────────────► │  MCP Server              │ ◄────────────► │  ParaView Bridge     │
│  (MCP Client)    │                  │  src/paraview_mcp_server  │  localhost:9876 │  (pvpython context)  │
└─────────────────┘                  └──────────────────────────┘                 └──────────────────────┘
```

### 1. External MCP Server (`src/paraview_mcp_server/server.py`)

- Built with the official **MCP Python SDK** (`mcp`)
- Uses **stdio** transport — standard for MCP clients such as Claude Desktop
- Registers tools with proper names, descriptions, and JSON schemas
- On tool invocation: serialises the request as JSON, sends it to the bridge via TCP, waits for a JSON response
- Handles errors and connection failures gracefully
- Does **not** import ParaView — it only needs `mcp`

### 2. ParaView Bridge (`bridge/`)

- A standard Python package launched by `pvpython scripts/start_paraview_bridge.py`
- On startup: opens a **TCP socket** on `localhost:9876`
- Listens for newline-delimited JSON command messages from the MCP server
- Dispatches commands through the `CommandHandler` registry
- Executes commands using `paraview.simple` / `servermanager`
- Returns structured JSON results

## Communication Protocol

All messages are **newline-delimited JSON** (one JSON object per line).

### Request (MCP Server → Bridge)
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "command": "scene.list_sources",
  "params": {}
}
```

### Success Response (Bridge → MCP Server)
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "success": true,
  "result": { "sources": [...] }
}
```

### Error Response
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "success": false,
  "error": "Source 'disk.vtu' not found in the pipeline"
}
```

## Tool Namespaces

| Namespace | MCP tool prefix | Bridge command prefix |
|---|---|---|
| Scene / session | `paraview_scene_*` | `scene.*` |
| Data loading | `paraview_source_*` | `source.*` |
| Filters | `paraview_filter_*` | `filter.*` |
| Display / coloring | `paraview_display_*` | `display.*` |
| Camera / view | `paraview_view_*` | `view.*` |
| Export | `paraview_export_*` | `export.*` |
| Python execution | `paraview_python_exec` | `python.execute` |

## Full Tool Reference

### Scene tools
| MCP name | Bridge command | Description |
|---|---|---|
| `paraview_scene_get_info` | `scene.get_info` | Session info (source count, view type) |
| `paraview_scene_list_sources` | `scene.list_sources` | List all pipeline sources |
| `paraview_scene_list_views` | `scene.list_views` | List open render views |
| `paraview_source_get_properties` | `source.get_properties` | Get source properties |

### Data loading
| MCP name | Bridge command | Description |
|---|---|---|
| `paraview_source_open_file` | `source.open_file` | Open a dataset file |
| `paraview_source_delete` | `source.delete` | Remove a source from the pipeline |
| `paraview_source_rename` | `source.rename` | Rename a source |

### Filters
| MCP name | Bridge command | Description |
|---|---|---|
| `paraview_filter_slice` | `filter.slice` | Apply a Slice filter |
| `paraview_filter_clip` | `filter.clip` | Apply a Clip filter |
| `paraview_filter_contour` | `filter.contour` | Apply a Contour (isosurface) filter |
| `paraview_filter_threshold` | `filter.threshold` | Apply a Threshold filter |

### Display / coloring
| MCP name | Bridge command | Description |
|---|---|---|
| `paraview_display_show` | `display.show` | Make a source visible |
| `paraview_display_hide` | `display.hide` | Hide a source |
| `paraview_display_color_by` | `display.color_by` | Color by a data array |
| `paraview_display_set_representation` | `display.set_representation` | Set representation type |

### View / camera
| MCP name | Bridge command | Description |
|---|---|---|
| `paraview_view_reset_camera` | `view.reset_camera` | Fit all visible sources in view |

### Export
| MCP name | Bridge command | Description |
|---|---|---|
| `paraview_export_screenshot` | `export.screenshot` | Save a PNG/JPEG screenshot |
| `paraview_export_data` | `export.data` | Export source data to file |

### Python
| MCP name | Bridge command | Description |
|---|---|---|
| `paraview_python_exec` | `python.execute` | Execute inline Python in pvpython context |

## Python Script Execution

The `python.execute` command lets MCP clients execute arbitrary ParaView Python code
through the bridge. This is the primary extension point for advanced workflows that go
beyond the predefined tool set.

### Command Flow

```
MCP Client                MCP Server                ParaView Bridge
    │                         │                            │
    │  paraview_python_exec   │                            │
    │  {code, args}           │                            │
    │────────────────────────►│                            │
    │                         │  python.execute            │
    │                         │  {code, args}              │
    │                         │───────────────────────────►│
    │                         │                            │ exec(code, namespace)
    │                         │                            │ capture stdout/stderr
    │                         │                            │◄─── __result__
    │                         │  {success, result,         │
    │                         │   stdout, stderr,          │
    │                         │   duration_seconds}        │
    │                         │◄───────────────────────────│
    │  tool response          │                            │
    │◄────────────────────────│                            │
```

See `docs/python-execute-design.md` for the full design.

## Lifecycle

1. User starts the ParaView bridge: `pvpython scripts/start_paraview_bridge.py`
   - Bridge binds to `127.0.0.1:9876`
2. User registers the MCP server in their client config
3. MCP client starts the MCP server process via stdio
4. MCP client sends tool calls → MCP server forwards to bridge → bridge executes with `paraview.simple` → result flows back
5. On shutdown: MCP server closes TCP connection; bridge can be stopped with Ctrl+C

## Configuration

### Claude Desktop (`claude_desktop_config.json`)
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

## Repository Layout

```
paraview-mcp-server/
├── pyproject.toml                   # Package metadata, dependencies, entrypoint
├── src/
│   └── paraview_mcp_server/
│       ├── __init__.py              # Re-exports main()
│       └── server.py                # FastMCP stdio server with all tools
├── bridge/
│   ├── __init__.py
│   ├── server.py                    # TCP socket server
│   ├── command_handler.py           # Command registry + paraview.simple handlers
│   └── execution.py                 # python.execute helper
├── scripts/
│   ├── start_paraview_bridge.py     # Entry point: pvpython scripts/start_paraview_bridge.py
│   ├── paraview_bridge_request.py   # CLI tool to send raw JSON commands
│   └── library/                     # Reusable pvpython script snippets
│       ├── open_dataset.py
│       ├── create_slice.py
│       ├── create_contour.py
│       ├── color_by.py
│       ├── reset_camera.py
│       └── save_screenshot.py
├── docs/
│   ├── architecture.md              # This document
│   └── python-execute-design.md     # Python execution design
└── tests/
    ├── __init__.py
    ├── test_server.py               # MCP server tool registration + connection tests
    ├── test_protocol.py             # Bridge protocol (request/response format)
    └── test_command_handler.py      # Command handler unit tests
```
