# Python Execution Design

## Overview

The python.execute command (exposed as paraview_python_exec in MCP) provides an
escape hatch for workflows that require more than the fixed tool set.

Two transports are supported:

1. **Bridge** (default) - code runs inside the running pvpython bridge process via exec().
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

Headless transport adds:

| cancelled | bool | true if the job was cancelled |

---

## Execution namespace

| Variable | Type | Description |
|---|---|---|
| pvs | module or None | paraview.simple (None if ParaView unavailable) |
| args | dict | Arguments from the request |
| __result__ | None | Set this to return a value to the caller |

---

## Safety model

### Blocked modules

The following modules are blocked during script execution:
subprocess, shutil, socket, ctypes, multiprocessing, webbrowser,
http.server, xmlrpc.server, ftplib, smtplib, telnetlib.

### Output bounding

Both stdout and stderr are independently capped at 50 KB.

### Cooperative timeout

Default 30 seconds. Bridge transport: thread left running but response
returned with timed_out: true. Headless: subprocess killed.

### Script path validation

When script_path is used, the file is resolved to an absolute path and
checked against APPROVED_SCRIPT_ROOTS (empty = no restriction).

### Inline code toggle

Set ALLOW_INLINE_CODE = False in execution.py to disable inline code.

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

### Open file and slice
    src = pvs.OpenDataFile(args["filepath"])
    view = pvs.GetActiveViewOrCreate("RenderView")
    pvs.Show(src, view)
    filt = pvs.Slice(Input=src)
    filt.SliceType.Origin = [0, 0, 0]
    filt.SliceType.Normal = [1, 0, 0]
    pvs.Show(filt, view)
    __result__ = {"done": True}

### Color by scalar array
    src = pvs.FindSource(args["name"])
    view = pvs.GetActiveViewOrCreate("RenderView")
    display = pvs.GetDisplayProperties(src, view)
    pvs.ColorBy(display, ("POINTS", args["array"]))
    __result__ = {"colored_by": args["array"]}

### Export screenshot
    view = pvs.GetActiveViewOrCreate("RenderView")
    pvs.SaveScreenshot(args["filepath"], view, ImageResolution=[1920, 1080])
    __result__ = {"filepath": args["filepath"]}

---

## Future work

- Cancellation token (bridge transport) for cooperative cancellation
- Script library registry for referencing scripts by name
- Sandboxed execution beyond the blocked-module list
- Resource limits for memory usage per script
