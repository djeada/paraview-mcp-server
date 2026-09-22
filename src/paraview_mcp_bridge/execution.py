"""Python script execution helper for the ParaView bridge.

Execution controls
------------------
- **Output bounding** caps stdout/stderr at 50 KB.
- **Timeout** (cooperative) — the caller can supply ``timeout_seconds``.
- **Script-path execution** reads the script from disk, validating that it
  lives under an *approved root* when configured.
"""

from __future__ import annotations

import io
import json
import os
import re
import threading
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

MAX_OUTPUT_SIZE = 50_000

# Optionally set via bridge config; empty list → no restriction.
APPROVED_SCRIPT_ROOTS: list[str] = []

# Whether inline code execution is allowed (can be toggled via bridge config).
ALLOW_INLINE_CODE: bool = True

DEFAULT_TIMEOUT_SECONDS: float = 30.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cap_output(text: str, limit: int = MAX_OUTPUT_SIZE) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… (truncated, {len(text)} total chars)"


def _safe_json(value: Any) -> Any:
    """Return *value* if JSON-serialisable, otherwise ``repr(value)``."""
    if value is None:
        return None
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)


def _validate_script_path(script_path: str) -> str:
    """Resolve *script_path* and check it against approved roots."""
    resolved = str(Path(script_path).resolve())
    if not os.path.isfile(resolved):
        raise FileNotFoundError(f"Script not found: {resolved!r}")
    if APPROVED_SCRIPT_ROOTS:
        for root in APPROVED_SCRIPT_ROOTS:
            if resolved.startswith(str(Path(root).resolve())):
                return resolved
        raise PermissionError(f"Script {resolved!r} is not under any approved root: {APPROVED_SCRIPT_ROOTS!r}")
    return resolved


def _validate_registration_name(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise ValueError("registration name must be a non-empty string")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_. -]*", name):
        raise ValueError(
            "registration name may contain letters, numbers, spaces, '.', '_', and '-', "
            "and must start with a letter or '_'"
        )
    return name


def _build_polydata_programmable_script(payload: dict[str, Any]) -> str:
    payload_json = json.dumps(payload, separators=(",", ":"))
    return f"""
import json
import vtk

payload = json.loads({payload_json!r})
points_data = payload.get("points", [])
verts_data = payload.get("verts") or []
lines_data = payload.get("lines") or []
polys_data = payload.get("polys") or []
point_data = payload.get("point_data") or {{}}
cell_data = payload.get("cell_data") or {{}}

points = vtk.vtkPoints()
for point in points_data:
    if len(point) != 3:
        raise ValueError("each point must contain exactly 3 coordinates")
    points.InsertNextPoint(float(point[0]), float(point[1]), float(point[2]))

polydata = vtk.vtkPolyData()
polydata.SetPoints(points)

def _cell_array(cells):
    arr = vtk.vtkCellArray()
    for cell in cells:
        arr.InsertNextCell(len(cell))
        for point_id in cell:
            arr.InsertCellPoint(int(point_id))
    return arr

if verts_data:
    polydata.SetVerts(_cell_array(verts_data))
if lines_data:
    polydata.SetLines(_cell_array(lines_data))
if polys_data:
    polydata.SetPolys(_cell_array(polys_data))

def _add_arrays(attributes, arrays):
    for name, values in arrays.items():
        vtk_array = vtk.vtkFloatArray()
        vtk_array.SetName(str(name))
        first = values[0] if values else 0.0
        components = len(first) if isinstance(first, (list, tuple)) else 1
        vtk_array.SetNumberOfComponents(components)
        for value in values:
            if components == 1:
                vtk_array.InsertNextValue(float(value))
            else:
                if len(value) != components:
                    raise ValueError(f"array {{name!r}} has inconsistent component counts")
                vtk_array.InsertNextTuple([float(component) for component in value])
        attributes.AddArray(vtk_array)

_add_arrays(polydata.GetPointData(), point_data)
_add_arrays(polydata.GetCellData(), cell_data)

self.GetPolyDataOutput().ShallowCopy(polydata)
"""


class ParaViewMCPHelpers:
    """Small helpers exposed to ``python.execute`` scripts as ``mcp``."""

    def __init__(self, pvs: Any):
        self._pvs = pvs

    def create_polydata_source(
        self,
        name: str,
        *,
        points: list,
        verts: list | None = None,
        lines: list | None = None,
        polys: list | None = None,
        point_data: dict[str, list] | None = None,
        cell_data: dict[str, list] | None = None,
    ) -> Any:
        """Create a pipeline-visible ``vtkPolyData`` source.

        This avoids ``GetClientSideObject()``, which is often ``None`` when the
        bridge is a separate pvpython client connected to a pvserver session.
        """
        if self._pvs is None:
            raise RuntimeError("paraview.simple is not available")
        source_name = _validate_registration_name(name)
        payload = {
            "points": points,
            "verts": verts or [],
            "lines": lines or [],
            "polys": polys or [],
            "point_data": point_data or {},
            "cell_data": cell_data or {},
        }
        source = self._pvs.ProgrammableSource(registrationName=source_name)
        source.OutputDataSetType = "vtkPolyData"
        source.Script = _build_polydata_programmable_script(payload)
        source.UpdatePipeline()
        return source


# ---------------------------------------------------------------------------
# Core execution
# ---------------------------------------------------------------------------


def execute_code(
    code: str | None = None,
    args: dict | None = None,
    *,
    script_path: str | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Execute *code* (or *script_path*) in a pvpython-friendly namespace.

    Parameters
    ----------
    code:
        Inline Python source string.  Mutually exclusive with *script_path*.
    args:
        Dict exposed as ``args`` inside the script.
    script_path:
        Path to a ``.py`` file.  Mutually exclusive with *code*.
    timeout_seconds:
        Cooperative timeout (default ``DEFAULT_TIMEOUT_SECONDS``).
    """
    if code and script_path:
        raise ValueError("Provide either 'code' or 'script_path', not both")
    if not code and not script_path:
        raise ValueError("Either 'code' or 'script_path' must be provided")
    if code and not ALLOW_INLINE_CODE:
        raise PermissionError("Inline code execution is disabled; use script_path instead")

    if script_path:
        resolved = _validate_script_path(script_path)
        code = Path(resolved).read_text(encoding="utf-8")

    if timeout_seconds is None:
        timeout_seconds = DEFAULT_TIMEOUT_SECONDS

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    try:
        import paraview.simple as pvs  # noqa: PLC0415
    except ImportError:
        pvs = None  # type: ignore[assignment]

    namespace: dict[str, Any] = {
        "args": args or {},
        "pvs": pvs,
        "mcp": ParaViewMCPHelpers(pvs),
        "__result__": None,
    }

    result_holder: dict[str, Any] = {}
    start = time.monotonic()

    # At this point code is guaranteed to be a non-None str
    assert isinstance(code, str)

    def _run() -> None:
        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(compile(code, "<paraview-mcp-script>", "exec"), namespace)  # noqa: S102
        except Exception as exc:
            result_holder["error"] = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)

    elapsed = round(time.monotonic() - start, 4)

    if thread.is_alive():
        return {
            "result": None,
            "stdout": _cap_output(stdout_buf.getvalue()),
            "stderr": _cap_output(stderr_buf.getvalue()),
            "error": f"Execution exceeded timeout of {timeout_seconds}s",
            "duration_seconds": elapsed,
            "timed_out": True,
        }

    if "error" in result_holder:
        return {
            "result": None,
            "stdout": _cap_output(stdout_buf.getvalue()),
            "stderr": _cap_output(stderr_buf.getvalue()),
            "error": result_holder["error"],
            "duration_seconds": elapsed,
            "timed_out": False,
        }

    return {
        "result": _safe_json(namespace.get("__result__")),
        "stdout": _cap_output(stdout_buf.getvalue()),
        "stderr": _cap_output(stderr_buf.getvalue()),
        "error": None,
        "duration_seconds": elapsed,
        "timed_out": False,
    }
