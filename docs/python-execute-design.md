# Python Execution Design

## Overview

The python.execute command (exposed as paraview_python_exec in MCP) provides an
escape hatch for workflows that require more than the fixed tool set.

Two transports are supported:

1. **Bridge** (default) - code runs inside the active bridge process via exec().
   For GUI control started by `paraview-mcp-launch`, that process is a
   `pvpython` client connected to the same `pvserver` as the ParaView GUI. For
   headless control, it is the standalone `pvpython scripts/start_paraview_bridge.py`
   process.
2. **Headless** - code runs in a separate pvpython subprocess via HeadlessPvpythonExecutor.

---

## Request schema

### Bridge transport

    {
      "id": "uuid-string",
      "command": "python.execute",
      "params": {
        "code": "src = pvs.OpenDataFile(args['filepath'])",
        "args": { "filepath": "/data/disk.vtu" },
        "timeout_seconds": 30,
        "script_path": null
      }
    }

| Field | Type | Required | Description |
|---|---|---|---|
| code | str | One of code/script_path | Inline Python source |
| script_path | str | One of code/script_path | Path to a .py file |
| args | dict | No | Arguments exposed as args in the script |
| timeout_seconds | float | No | Cooperative timeout (default: 30s) |

---

## Response schema

| Field | Type | Description |
|---|---|---|
| result | Any | Value of __result__ (JSON-serialisable, or repr() fallback) |
| stdout | str | Captured stdout (capped at 50 KB) |
| stderr | str | Captured stderr (capped at 50 KB) |
| error | str or null | Traceback string on failure, null on success |
| duration_seconds | float | Wall-clock execution time |
| timed_out | bool | true if the script exceeded the timeout |
| abandoned_threads | int | Timed-out scripts still running in the bridge |

Headless transport adds:

| cancelled | bool | true if the job was cancelled |

---

## Execution namespace

| Variable | Type | Description |
|---|---|---|
| pvs | module or None | paraview.simple (None if ParaView unavailable) |
| args | dict | Arguments from the request |
| mcp | helper | Mode-aware helpers, see below |
| __result__ | None | Set this to return a value to the caller |

### The `mcp` helpers

| Call | Purpose |
|---|---|
| `mcp.find_render_view()` | Existing render view or `None` — never creates one |
| `mcp.show(proxy)` | Display *proxy* if a view exists; returns whether it did |
| `mcp.reset_camera()` | Reset the camera if a view exists; returns whether it did |
| `mcp.create_polydata_source(name, points=..., ...)` | Publish a `vtkPolyData` source into the pipeline |

Prefer these over `GetActiveViewOrCreate("RenderView")` + `Show()`. They are
no-ops rather than errors when no render view exists, so the same script runs
under both the default pvpython bridge and the in-GUI bridge.

---

## Python Execution Trust Model

### Trusted local execution

Bridge scripts run inside the local ParaView Python process and may import
normal Python modules. In GUI mode, that is a `pvpython` bridge client attached
to the same `pvserver` as the ParaView GUI.
This is intentional: `paraview_python_exec` is the escape hatch for full
ParaView automation when the fixed MCP tool set is too small.

### Output bounding

Both stdout and stderr are independently capped at 50 KB.

### Cooperative timeout

Default 30 seconds.

- **Headless transport**: the subprocess is killed. Output written before the
  kill is still returned.
- **Bridge transport**: Python cannot kill a thread, so the script keeps
  running after the timeout response is sent. It may still modify the ParaView
  session, and it is no longer serialised against later commands. The response
  says so, and `abandoned_threads` reports how many such scripts are still
  alive. Restart the bridge if that matters.

Captured stdout/stderr are routed per *thread*, not by swapping the process's
`sys.stdout`. An abandoned thread therefore keeps writing into its own bounded
buffer instead of silencing the bridge's own logging.

### Render-view guard

From the default standalone pvpython bridge, `python.execute` rejects scripts
that reference render/view/display APIs, because creating a view from a client
that is not the GUI can open a detached VTK window. Detection is done on the
parsed syntax tree, so a comment or an unrelated identifier such as
`Rendering` is not a false positive, while `pvs.Show(...)`, a bare `Show(...)`
and `getattr(pvs, "Show")` are all caught.

This is a guardrail against an *accident*, not a sandbox: a script that builds
a name at runtime still gets through, and `python.execute` remains fully
trusted. To run render code deliberately, start the in-GUI bridge or set
`PARAVIEW_MCP_ALLOW_DETACHED_RENDER_WINDOW=1`.

### Script path validation

When script_path is used, the file is resolved to an absolute path and checked
against the approved roots (empty = no restriction). The check compares path
components, so an approved root of `/srv/safe` does not also admit
`/srv/safe-evil/script.py`.

Configure with `PARAVIEW_MCP_APPROVED_SCRIPT_ROOTS` (os.pathsep-separated) or
by assigning `execution.APPROVED_SCRIPT_ROOTS`; the assignment wins.

### Inline code toggle

Set `PARAVIEW_MCP_ALLOW_INLINE_CODE=0`, or assign
`execution.ALLOW_INLINE_CODE = False`, to require `script_path`.

---

## Async execution

Use paraview_python_exec_async for long-running scripts:
1. Start job -> returns job_id
2. Poll with paraview_job_status
3. Cancel with paraview_job_cancel

---

## Examples

### List pipeline sources
    sources = pvs.GetSources()
    __result__ = [{"name": n, "id": str(i)} for (n, i), p in sources.items()]

### Open file and slice (works in both bridge modes)
    src = pvs.OpenDataFile(args["filepath"])
    filt = pvs.Slice(Input=src)
    filt.SliceType.Origin = [0, 0, 0]
    filt.SliceType.Normal = [1, 0, 0]
    __result__ = {"done": True, "shown": mcp.show(filt)}

The examples below call render APIs directly, so they need the in-GUI bridge or
`PARAVIEW_MCP_ALLOW_DETACHED_RENDER_WINDOW=1`. From the default bridge, use the
`paraview_display_color_by` and `paraview_export_screenshot` tools instead.

### Color by scalar array (render-view mode only)
    src = pvs.FindSource(args["name"])
    view = pvs.GetActiveViewOrCreate("RenderView")
    display = pvs.GetDisplayProperties(src, view)
    pvs.ColorBy(display, ("POINTS", args["array"]))
    __result__ = {"colored_by": args["array"]}

### Export screenshot (render-view mode only)
    view = pvs.GetActiveViewOrCreate("RenderView")
    pvs.SaveScreenshot(args["filepath"], view, ImageResolution=[1920, 1080])
    __result__ = {"filepath": args["filepath"]}

---

## Future work

- Cancellation token (bridge transport) for cooperative cancellation
- Script library registry for referencing scripts by name
- Optional sandboxed execution mode for deployments that need stricter isolation
- Resource limits for memory usage per script
