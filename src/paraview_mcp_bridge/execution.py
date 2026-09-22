"""Python script execution helper for the ParaView bridge.

Execution controls
------------------
- **Output bounding** — stdout/stderr are captured into buffers that stop
  accumulating at 50 KB, so a runaway script cannot exhaust memory.
- **Timeout** (cooperative) — the caller can supply ``timeout_seconds``.
- **Script-path execution** reads the script from disk, validating that it
  lives under an *approved root* when one is configured.

Why output capture is thread-routed
-----------------------------------
Scripts run on a worker thread so the bridge can return a response when one
overruns its timeout. Python cannot kill a thread, so an overrunning script
keeps running after that response is sent. ``contextlib.redirect_stdout``
would be catastrophic here: it swaps the *process-global* ``sys.stdout``, and
the abandoned thread never unwinds it, permanently silencing the bridge's own
logging. Instead ``sys.stdout``/``sys.stderr`` are replaced once by a proxy
that routes each write according to the *writing thread*. Abandoned threads
keep writing into their own bounded, abandoned buffers and the real streams
stay intact.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

MAX_OUTPUT_SIZE = 50_000

DEFAULT_TIMEOUT_SECONDS: float = 30.0

APPROVED_SCRIPT_ROOTS_ENV = "PARAVIEW_MCP_APPROVED_SCRIPT_ROOTS"
ALLOW_INLINE_CODE_ENV = "PARAVIEW_MCP_ALLOW_INLINE_CODE"

# Module-level overrides. Both are also configurable through the environment
# variables above; an explicit assignment here takes precedence.
APPROVED_SCRIPT_ROOTS: list[str] | None = None
ALLOW_INLINE_CODE: bool | None = None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def approved_script_roots() -> list[str]:
    """Roots that ``script_path`` execution is confined to (empty = no limit)."""
    if APPROVED_SCRIPT_ROOTS is not None:
        return list(APPROVED_SCRIPT_ROOTS)
    raw = os.environ.get(APPROVED_SCRIPT_ROOTS_ENV, "")
    return [part for part in raw.split(os.pathsep) if part]


def inline_code_allowed() -> bool:
    """Whether inline ``code`` execution is permitted."""
    if ALLOW_INLINE_CODE is not None:
        return bool(ALLOW_INLINE_CODE)
    return os.environ.get(ALLOW_INLINE_CODE_ENV, "1") != "0"


# ---------------------------------------------------------------------------
# Bounded, thread-routed output capture
# ---------------------------------------------------------------------------


class _BoundedBuffer:
    """Collects text up to a byte budget while counting everything written."""

    def __init__(self, limit: int = MAX_OUTPUT_SIZE):
        self._limit = limit
        self._chunks: list[str] = []
        self._kept = 0
        self._total = 0
        self._lock = threading.Lock()

    def write(self, text: Any) -> int:
        if not isinstance(text, str):
            text = str(text)
        with self._lock:
            self._total += len(text)
            room = self._limit - self._kept
            if room > 0:
                kept = text[:room]
                self._chunks.append(kept)
                self._kept += len(kept)
        return len(text)

    def writelines(self, lines: Any) -> None:
        for line in lines:
            self.write(line)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False

    def getvalue(self) -> str:
        with self._lock:
            text = "".join(self._chunks)
            truncated = self._total > self._kept
            total = self._total
        if truncated:
            text += f"\n… (truncated, {total} total chars)"
        return text


# Per-thread capture targets, consulted by every proxy stream. Keeping this at
# module scope (rather than on the proxy) means a thread stays bound to its own
# buffer even if sys.stdout is swapped again by something else, e.g. pytest.
_capture = threading.local()

_install_lock = threading.Lock()


class _ThreadRoutedStream:
    """``sys.stdout``/``sys.stderr`` proxy that honours per-thread capture."""

    def __init__(self, original: Any, kind: str):
        self._original = original
        self._kind = kind

    @property
    def original(self) -> Any:
        return self._original

    def _target(self) -> Any:
        buffer = getattr(_capture, self._kind, None)
        return self._original if buffer is None else buffer

    def write(self, text: Any) -> int:
        written = self._target().write(text)
        # Some file-likes return None from write(); report the length instead.
        return written if isinstance(written, int) else len(text)

    def writelines(self, lines: Any) -> None:
        target = self._target()
        writelines = getattr(target, "writelines", None)
        if callable(writelines):
            writelines(lines)
            return
        for line in lines:
            target.write(line)

    def flush(self) -> None:
        flush = getattr(self._target(), "flush", None)
        if callable(flush):
            flush()

    def isatty(self) -> bool:
        # Only the real stream can be a terminal; while captured it is not.
        if getattr(_capture, self._kind, None) is not None:
            return False
        isatty = getattr(self._original, "isatty", None)
        return bool(isatty()) if callable(isatty) else False

    def close(self) -> None:
        # Never let a script close the bridge's real stdout.
        return None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)


def _install_stream_proxies() -> None:
    """Replace ``sys.stdout``/``sys.stderr`` with routing proxies, once."""
    with _install_lock:
        if not isinstance(sys.stdout, _ThreadRoutedStream):
            sys.stdout = _ThreadRoutedStream(sys.stdout, "stdout")  # type: ignore[assignment]
        if not isinstance(sys.stderr, _ThreadRoutedStream):
            sys.stderr = _ThreadRoutedStream(sys.stderr, "stderr")  # type: ignore[assignment]


def _bind_capture(stdout_buf: _BoundedBuffer, stderr_buf: _BoundedBuffer) -> None:
    _capture.stdout = stdout_buf
    _capture.stderr = stderr_buf


# Threads whose script overran its timeout and is still running.
_abandoned_threads: list[threading.Thread] = []
_abandoned_lock = threading.Lock()


def _record_abandoned(thread: threading.Thread) -> int:
    with _abandoned_lock:
        _abandoned_threads[:] = [t for t in _abandoned_threads if t.is_alive()]
        _abandoned_threads.append(thread)
        return len(_abandoned_threads)


def abandoned_thread_count() -> int:
    """How many timed-out scripts are still running in this process."""
    with _abandoned_lock:
        _abandoned_threads[:] = [t for t in _abandoned_threads if t.is_alive()]
        return len(_abandoned_threads)


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
    resolved = Path(script_path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Script not found: {str(resolved)!r}")
    roots = approved_script_roots()
    if not roots:
        return str(resolved)
    for root in roots:
        root_resolved = Path(root).resolve()
        # is_relative_to compares path components, so an approved root of
        # '/srv/safe' does not also admit '/srv/safe-evil/script.py'.
        if resolved == root_resolved or resolved.is_relative_to(root_resolved):
            return str(resolved)
    raise PermissionError(f"Script {str(resolved)!r} is not under any approved root: {roots!r}")


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

    def _require_pvs(self) -> Any:
        if self._pvs is None:
            raise RuntimeError("paraview.simple is not available")
        return self._pvs

    def find_render_view(self) -> Any | None:
        """Return an existing render view, or ``None``.

        Unlike ``GetActiveViewOrCreate('RenderView')`` this never *creates* a
        view, so it cannot pop a detached VTK window when the bridge is a
        standalone pvpython client. Scripts that use it work in both the
        in-GUI bridge and the default pipeline-only bridge.
        """
        from paraview_mcp_bridge.command_handler import CommandHandler  # noqa: PLC0415

        return CommandHandler().find_existing_render_view(self._require_pvs())

    def show(self, proxy: Any) -> bool:
        """Display *proxy* if a render view already exists. Returns whether it did."""
        pvs = self._require_pvs()
        view = self.find_render_view()
        if view is None:
            return False
        pvs.Show(proxy, view)
        return True

    def reset_camera(self) -> bool:
        """Reset the camera if a render view already exists."""
        pvs = self._require_pvs()
        view = self.find_render_view()
        if view is None:
            return False
        pvs.ResetCamera(view)
        return True

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
        pvs = self._require_pvs()
        source_name = _validate_registration_name(name)
        payload = {
            "points": points,
            "verts": verts or [],
            "lines": lines or [],
            "polys": polys or [],
            "point_data": point_data or {},
            "cell_data": cell_data or {},
        }
        source = pvs.ProgrammableSource(registrationName=source_name)
        source.OutputDataSetType = "vtkPolyData"
        source.Script = _build_polydata_programmable_script(payload)
        source.UpdatePipeline()
        return source


# ---------------------------------------------------------------------------
# Render-API guard
# ---------------------------------------------------------------------------


def find_render_api_calls(source: str, blocked_names: tuple[str, ...]) -> list[str]:
    """Return the blocked render/view APIs *source* references.

    Matching is done on the parsed syntax tree, not on raw text, so a comment
    or an unrelated identifier such as ``Rendering`` is not a hit, while
    ``pvs.Show(...)``, a bare ``Show(...)`` and ``getattr(pvs, "Show")`` all
    are. This is a guardrail against *accidentally* opening a detached render
    window, not a sandbox: code that builds a name at runtime still gets
    through, and callers should treat ``python.execute`` as trusted.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # Let exec() raise the syntax error with a proper traceback.
        return []

    blocked = set(blocked_names)
    found: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in blocked:
            found.add(node.attr)
        elif isinstance(node, ast.Name) and node.id in blocked:
            found.add(node.id)
        elif isinstance(node, ast.alias):
            imported = node.name.rsplit(".", 1)[-1]
            if imported in blocked:
                found.add(imported)
        elif isinstance(node, ast.Call):
            func = node.func
            is_getattr = (isinstance(func, ast.Name) and func.id == "getattr") or (
                isinstance(func, ast.Attribute) and func.attr == "getattr"
            )
            if is_getattr and len(node.args) >= 2:
                target = node.args[1]
                if isinstance(target, ast.Constant) and target.value in blocked:
                    found.add(str(target.value))

    return sorted(found)


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
    if code and not inline_code_allowed():
        raise PermissionError("Inline code execution is disabled; use script_path instead")

    if script_path:
        resolved = _validate_script_path(script_path)
        code = Path(resolved).read_text(encoding="utf-8")

    if timeout_seconds is None:
        timeout_seconds = DEFAULT_TIMEOUT_SECONDS

    stdout_buf = _BoundedBuffer()
    stderr_buf = _BoundedBuffer()
    _install_stream_proxies()

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
        _bind_capture(stdout_buf, stderr_buf)
        try:
            exec(compile(code, "<paraview-mcp-script>", "exec"), namespace)  # noqa: S102
        except Exception as exc:
            result_holder["error"] = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    thread = threading.Thread(target=_run, name="paraview-mcp-script", daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)

    elapsed = round(time.monotonic() - start, 4)

    if thread.is_alive():
        # Python cannot kill a thread. Say so plainly: the script keeps running
        # and keeps touching ParaView, so it is no longer serialised against
        # later commands.
        abandoned = _record_abandoned(thread)
        return {
            "result": None,
            "stdout": stdout_buf.getvalue(),
            "stderr": stderr_buf.getvalue(),
            "error": (
                f"Execution exceeded timeout of {timeout_seconds}s. The script is still running "
                "in the background and may continue to modify the ParaView session; restart the "
                "bridge if that is a problem."
            ),
            "duration_seconds": elapsed,
            "timed_out": True,
            "abandoned_threads": abandoned,
        }

    if "error" in result_holder:
        return {
            "result": None,
            "stdout": stdout_buf.getvalue(),
            "stderr": stderr_buf.getvalue(),
            "error": result_holder["error"],
            "duration_seconds": elapsed,
            "timed_out": False,
            "abandoned_threads": abandoned_thread_count(),
        }

    return {
        "result": _safe_json(namespace.get("__result__")),
        "stdout": stdout_buf.getvalue(),
        "stderr": stderr_buf.getvalue(),
        "error": None,
        "duration_seconds": elapsed,
        "timed_out": False,
        "abandoned_threads": abandoned_thread_count(),
    }
