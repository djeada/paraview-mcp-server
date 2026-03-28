# ParaView MCP Server — Python Execution Design

## Overview

The `paraview_python_exec` tool (bridge command: `python.execute`) lets an AI assistant
send arbitrary Python code to the ParaView bridge for execution in the `pvpython` context.
This is the **escape hatch** for advanced workflows that go beyond the fixed tool set.

## Why it Matters

ParaView visualization pipelines are highly varied:

- Unusual file readers with custom options
- Multi-step filter pipelines
- Custom coloring logic and LUT manipulation
- `servermanager` property tuning
- Animation frame export loops
- Batch processing of multiple datasets

A fixed set of high-level tools cannot cover all of these. `paraview_python_exec` provides
full flexibility while keeping the structured tools for common, well-defined operations.

## Request Schema

**MCP tool call:**
```json
{
  "name": "paraview_python_exec",
  "arguments": {
    "code": "import paraview.simple as pvs\n__result__ = {'sources': list(pvs.GetSources().keys())}",
    "args": {}
  }
}
```

**Bridge protocol request:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "command": "python.execute",
  "params": {
    "code": "...",
    "args": {}
  }
}
```

## Response Schema

**Bridge protocol response (success):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "success": true,
  "result": {
    "result": {"sources": [...]},
    "stdout": "any printed output\n",
    "stderr": "",
    "error": null,
    "duration_seconds": 0.012
  }
}
```

**Bridge protocol response (script error):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "success": true,
  "result": {
    "result": null,
    "stdout": "",
    "stderr": "",
    "error": "Traceback (most recent call last):\n  ...\nValueError: ...",
    "duration_seconds": 0.003
  }
}
```

Note: A script-level exception returns `success: true` at the bridge protocol level
(the command was dispatched successfully) but sets `error` in the inner result dict.
The MCP tool returns this inner result to the AI assistant as a JSON string.

## Execution Namespace

The script executes with the following variables pre-populated:

| Variable | Type | Description |
|---|---|---|
| `pvs` | `module` | `paraview.simple` — the main ParaView Python API |
| `args` | `dict` | Arguments passed by the caller via the `args` parameter |
| `__result__` | `Any` | Set this to return a value. Must be JSON-serialisable. |

Example:
```python
# Accessible in script:
pvs.GetActiveViewOrCreate("RenderView")
src = pvs.OpenDataFile(args["filepath"])
__result__ = {"name": src.GetXMLLabel()}
```

## Output Capture

- Both `sys.stdout` and `sys.stderr` are redirected for the duration of the script
- Output from `print()` calls is captured and returned in `stdout`
- Stack traces from exceptions are captured in `error`
- All output is capped at **50 000 characters** to prevent memory exhaustion

## Return Value Handling

- The script sets `__result__` to any JSON-serialisable value
- If `__result__` is not JSON-serialisable, it is converted to `repr()`
- If the script does not set `__result__`, it defaults to `None`

## Safety Model

The bridge operates in a local desktop trust model. The following controls are in place:

1. **Output bounding** — stdout/stderr are capped at 50 KB
2. **No module blocklist by default** — the bridge runs in the same Python process as
   ParaView and trusts the user; blocking is configurable by modifying `bridge/execution.py`
3. **Execution timeout** — not enforced by default; can be added by wrapping `execute_code`
   in a thread with a join timeout

This is **not a sandbox**. It provides the same level of isolation as running arbitrary
Python in a `pvpython` session. Only use it in trusted, local desktop automation workflows.

## Examples

### List all pipeline sources
```python
__result__ = {
    "sources": [
        {"name": name, "id": str(_id)}
        for (name, _id) in pvs.GetSources().keys()
    ]
}
```

### Open a file and apply a slice
```python
src = pvs.OpenDataFile(args["filepath"])
view = pvs.GetActiveViewOrCreate("RenderView")
pvs.Show(src, view)
filt = pvs.Slice(Input=src)
filt.SliceType.Origin = args.get("origin", [0, 0, 0])
filt.SliceType.Normal = args.get("normal", [1, 0, 0])
pvs.Show(filt, view)
pvs.ResetCamera(view)
__result__ = {"slice": "created", "origin": filt.SliceType.Origin[:]}
```

### Color by a scalar array
```python
name = args["name"]
array = args["array"]
src = next(
    proxy for (src_name, _id), proxy in pvs.GetSources().items()
    if src_name == name
)
view = pvs.GetActiveViewOrCreate("RenderView")
display = pvs.GetDisplayProperties(src, view)
pvs.ColorBy(display, ("POINTS", array))
pvs.UpdateScalarBars(view)
__result__ = {"colored_by": array}
```

### Export a screenshot
```python
view = pvs.GetActiveViewOrCreate("RenderView")
pvs.SaveScreenshot(args["filepath"], view, ImageResolution=[1920, 1080])
__result__ = {"filepath": args["filepath"]}
```

### Batch process multiple datasets
```python
import os
results = []
for f in args["files"]:
    src = pvs.OpenDataFile(f)
    if src is None:
        results.append({"file": f, "error": "could not open"})
        continue
    out = f.replace(".vtu", "_screenshot.png")
    view = pvs.GetActiveViewOrCreate("RenderView")
    pvs.Show(src, view)
    pvs.ResetCamera(view)
    pvs.SaveScreenshot(out, view, ImageResolution=[800, 600])
    pvs.Delete(src)
    results.append({"file": f, "screenshot": out})
__result__ = {"processed": results}
```

## Future Work

- **Timeout enforcement** via a thread watchdog
- **Script-path execution** (`script_path` parameter) with path validation
- **Async execution** for long-running pipelines
- **Module blocklist** configurable via bridge settings
