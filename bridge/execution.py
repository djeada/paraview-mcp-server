"""Python script execution helper for the ParaView bridge."""

import io
import json
import sys
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

MAX_OUTPUT_SIZE = 50_000


def _cap_output(text: str) -> str:
    if len(text) <= MAX_OUTPUT_SIZE:
        return text
    return text[:MAX_OUTPUT_SIZE] + f"\n… (truncated, {len(text)} total chars)"


def execute_code(code: str, args: dict | None = None) -> dict[str, Any]:
    """Execute *code* in a namespace that includes paraview.simple and return a result dict."""
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    try:
        import paraview.simple as pvs  # noqa: PLC0415 — runtime import inside pvpython
    except ImportError:
        pvs = None  # type: ignore[assignment]

    namespace: dict[str, Any] = {
        "args": args or {},
        "pvs": pvs,
        "__result__": None,
    }

    start = time.monotonic()
    try:
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exec(compile(code, "<paraview-mcp-script>", "exec"), namespace)  # noqa: S102
    except Exception as exc:
        return {
            "result": None,
            "stdout": _cap_output(stdout_buf.getvalue()),
            "stderr": _cap_output(stderr_buf.getvalue()),
            "error": "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            ),
            "duration_seconds": round(time.monotonic() - start, 4),
        }

    result = namespace.get("__result__")
    try:
        json.dumps(result)
    except Exception:
        result = repr(result)

    return {
        "result": result,
        "stdout": _cap_output(stdout_buf.getvalue()),
        "stderr": _cap_output(stderr_buf.getvalue()),
        "error": None,
        "duration_seconds": round(time.monotonic() - start, 4),
    }
