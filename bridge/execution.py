"""Python script execution helper for the ParaView bridge.

Safety controls
---------------
- **Blocked-module import hook** prevents scripts from importing dangerous
  standard-library modules (``subprocess``, ``shutil``, ``socket``, …).
- **Output bounding** caps stdout/stderr at 50 KB.
- **Timeout** (cooperative) — the caller can supply ``timeout_seconds``.
- **Script-path execution** reads the script from disk, validating that it
  lives under an *approved root* when configured.
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import io
import json
import os
import sys
import threading
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

MAX_OUTPUT_SIZE = 50_000

BLOCKED_MODULES: set[str] = {
    "subprocess",
    "shutil",
    "socket",
    "ctypes",
    "multiprocessing",
    "webbrowser",
    "http.server",
    "xmlrpc.server",
    "ftplib",
    "smtplib",
    "telnetlib",
}

# Optionally set via bridge config; empty list → no restriction.
APPROVED_SCRIPT_ROOTS: list[str] = []

# Whether inline code execution is allowed (can be toggled via bridge config).
ALLOW_INLINE_CODE: bool = True

DEFAULT_TIMEOUT_SECONDS: float = 30.0


# ---------------------------------------------------------------------------
# Import hook that blocks dangerous modules during script execution
# ---------------------------------------------------------------------------


class _BlockedImportFinder(importlib.abc.MetaPathFinder):
    """Raises ``ImportError`` for modules in the *blocked* set."""

    _active = False
    _blocked: set[str] = set()

    def find_module(self, fullname: str, path=None):
        """Return *self* if the module should be blocked, ``None`` otherwise (legacy hook)."""
        if self._active and fullname in self._blocked:
            return self
        return None

    def find_spec(self, fullname: str, path=None, target=None):
        """Raise ``ImportError`` for blocked modules (modern import hook)."""
        if self._active and fullname in self._blocked:
            raise ImportError(f"Module {fullname!r} is blocked during ParaView MCP script execution")
        return None

    def load_module(self, fullname: str):
        raise ImportError(f"Module {fullname!r} is blocked during ParaView MCP script execution")


_BLOCKER = _BlockedImportFinder()


def _install_import_blocker() -> dict[str, Any]:
    """Activate the blocker and hide already-imported blocked modules.

    Returns a dict of hidden modules that must be restored later.
    """
    _BLOCKER._blocked = BLOCKED_MODULES
    _BLOCKER._active = True
    if _BLOCKER not in sys.meta_path:
        sys.meta_path.insert(0, _BLOCKER)
    # Temporarily remove blocked modules from sys.modules so `import X`
    # falls through to the meta-path hooks instead of hitting the cache.
    hidden: dict[str, Any] = {}
    for mod_name in BLOCKED_MODULES:
        if mod_name in sys.modules:
            hidden[mod_name] = sys.modules.pop(mod_name)
    return hidden


def _remove_import_blocker(hidden: dict[str, Any]) -> None:
    _BLOCKER._active = False
    # Restore previously-imported modules.
    sys.modules.update(hidden)


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
        "__result__": None,
    }

    result_holder: dict[str, Any] = {}
    start = time.monotonic()

    # At this point code is guaranteed to be a non-None str
    assert isinstance(code, str)

    def _run() -> None:
        hidden = _install_import_blocker()
        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(compile(code, "<paraview-mcp-script>", "exec"), namespace)  # noqa: S102
        except Exception as exc:
            result_holder["error"] = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        finally:
            _remove_import_blocker(hidden)

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
