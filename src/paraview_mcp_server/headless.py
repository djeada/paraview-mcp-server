"""Headless pvpython execution helpers used as a fallback transport.

This module lets the MCP server launch a separate ``pvpython`` / ``pvbatch``
process to execute scripts without requiring a running bridge.  It mirrors
the ``HeadlessBlenderExecutor`` from the Blender MCP server.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import tempfile
import textwrap
import time
import traceback
import uuid
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

RESULT_PREFIX = "__PARAVIEW_MCP_RESULT__="

# Async jobs are retained so their results can be polled, but a long-lived MCP
# server would otherwise accumulate every job it ever ran, each holding up to
# 100 KB of captured output.
DEFAULT_MAX_JOBS = 100
DEFAULT_JOB_TTL_SECONDS = 24 * 60 * 60

# Hard ceiling on bytes buffered per subprocess pipe, independent of the much
# smaller 50 KB cap applied to what is reported back.
MAX_CAPTURE_BYTES = 8 * 1024 * 1024


class _StreamCapture:
    """Bounded capture of a subprocess pipe.

    Keeps the head and the tail and drops the middle when a script produces
    more than ``limit`` bytes. The head keeps the early output that usually
    explains a failure; the tail matters because the structured result payload
    is the *last* line pvpython prints. Without a bound, a script that writes
    without stopping would grow this process until it is killed.
    """

    def __init__(self, limit: int = MAX_CAPTURE_BYTES):
        self._half = max(limit // 2, 1)
        self._head: list[bytes] = []
        self._head_size = 0
        self._tail: deque[bytes] = deque()
        self._tail_size = 0
        self.total = 0

    def feed(self, chunk: bytes) -> None:
        self.total += len(chunk)
        if self._head_size < self._half:
            room = self._half - self._head_size
            self._head.append(chunk[:room])
            self._head_size += min(room, len(chunk))
            chunk = chunk[room:]
            if not chunk:
                return
        if len(chunk) > self._half:
            # A single read larger than the budget: only its tail can be kept,
            # otherwise the "bound" would be one chunk wider than advertised.
            chunk = chunk[-self._half :]
        self._tail.append(chunk)
        self._tail_size += len(chunk)
        while self._tail and self._tail_size - len(self._tail[0]) >= self._half:
            self._tail_size -= len(self._tail.popleft())

    def value(self) -> bytes:
        head = b"".join(self._head)
        tail = b"".join(self._tail)
        dropped = self.total - len(head) - len(tail)
        if dropped > 0:
            return head + f"\n… ({dropped} bytes dropped) …\n".encode() + tail
        return head + tail

    def text(self) -> str:
        return self.value().decode("utf-8", errors="replace")


def _signal_tree(proc: Any, sig: int) -> None:
    """Signal a subprocess *and everything it spawned*.

    ``pvpython`` is a launcher that forks ``pvpython-real`` and waits for it,
    rather than exec'ing it. Signalling only the direct child therefore leaves
    the process actually running the script alive indefinitely, burning CPU and
    holding the pipes open. Children are started in their own session, so the
    whole group can be signalled at once.
    """
    if proc is None or proc.returncode is not None:
        return
    killpg = getattr(os, "killpg", None)
    getpgid = getattr(os, "getpgid", None)
    if killpg is not None and getpgid is not None:
        try:
            killpg(getpgid(proc.pid), sig)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    # Windows, or the group is already gone: fall back to the direct child.
    with contextlib.suppress(ProcessLookupError, OSError):
        if sig == signal.SIGKILL:
            proc.kill()
        else:
            proc.terminate()


async def _drain(stream: asyncio.StreamReader | None, capture: _StreamCapture) -> None:
    """Accumulate everything *stream* produces until it closes."""
    if stream is None:
        return
    while True:
        chunk = await stream.read(65536)
        # A non-bytes read means the stream is not a real pipe (a test double,
        # say). Stop rather than spin: an endless loop here would consume the
        # machine's memory.
        if not isinstance(chunk, bytes) or not chunk:
            return
        capture.feed(chunk)


async def _settle(tasks: Iterable[asyncio.Future[Any]], timeout: float = 5.0, proc: Any = None) -> None:
    """Let drain/wait tasks finish after the process has been signalled.

    If they are still pending once *timeout* elapses, the process ignored the
    signal (or a grandchild is holding the pipes), so escalate to SIGKILL on
    the whole group rather than leaving it running.
    """
    tasks = list(tasks)
    pending = {task for task in tasks if not task.done()}
    if not pending:
        return
    _, still_pending = await asyncio.wait(pending, timeout=timeout)
    if still_pending and proc is not None:
        _signal_tree(proc, signal.SIGKILL)
        _, still_pending = await asyncio.wait(still_pending, timeout=timeout)
    for task in still_pending:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


def _cap_output(text: str, limit: int = 50_000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… (truncated, {len(text)} total chars)"


def _safe_json(value: Any) -> Any:
    if value is None:
        return None
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)


def _extract_payload(stdout: str) -> tuple[dict[str, Any] | None, str]:
    """Split out the structured result payload from raw pvpython stdout."""
    payload = None
    clean_lines: list[str] = []
    for line in stdout.splitlines():
        if line.startswith(RESULT_PREFIX):
            payload = json.loads(line[len(RESULT_PREFIX) :])
        else:
            clean_lines.append(line)
    cleaned = "\n".join(clean_lines)
    if stdout.endswith("\n"):
        cleaned += "\n"
    return payload, cleaned


def _build_wrapper_script(code_path: Path, args_path: Path) -> str:
    return textwrap.dedent(
        f"""
        import io
        import json
        import pathlib
        import traceback
        from contextlib import redirect_stdout, redirect_stderr

        try:
            import paraview.simple as pvs
        except ImportError:
            pvs = None

        code = pathlib.Path({code_path.as_posix()!r}).read_text(encoding="utf-8")
        args = json.loads(pathlib.Path({args_path.as_posix()!r}).read_text(encoding="utf-8"))
        namespace = {{
            "pvs": pvs,
            "args": args,
            "__result__": None,
        }}
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(compile(code, "<mcp-headless-script>", "exec"), namespace)
            payload = {{
                "result": namespace.get("__result__"),
                "stdout": stdout_buf.getvalue(),
                "stderr": stderr_buf.getvalue(),
                "error": None,
                "timed_out": False,
                "cancelled": False,
            }}
        except Exception as exc:
            tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
            payload = {{
                "result": None,
                "stdout": stdout_buf.getvalue(),
                "stderr": stderr_buf.getvalue(),
                "error": "".join(tb).strip(),
                "timed_out": False,
                "cancelled": False,
            }}

        print({RESULT_PREFIX!r} + json.dumps(payload, ensure_ascii=True, default=repr))
        """
    )


class HeadlessPvpythonExecutor:
    """Run ParaView scripts in a separate headless ``pvpython`` process."""

    def __init__(self, pvpython_binary: str | None = None):
        self.pvpython_binary = pvpython_binary or os.environ.get("PVPYTHON_BIN", "pvpython")

    async def execute(
        self,
        *,
        code: str | None = None,
        script_path: str | None = None,
        args: dict[str, Any] | None = None,
        timeout_seconds: int | None = None,
        process_holder: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if code and script_path:
            raise ValueError("Provide either 'code' or 'script_path', not both")
        if not code and not script_path:
            raise ValueError("Either 'code' or 'script_path' must be provided")

        if script_path is not None:
            code = Path(script_path).read_text(encoding="utf-8")

        args = args or {}
        start = time.monotonic()

        with tempfile.TemporaryDirectory(prefix="paraview-mcp-headless-") as tmpdir:
            tmp = Path(tmpdir)
            code_path = tmp / "script.py"
            args_path = tmp / "args.json"
            wrapper_path = tmp / "wrapper.py"

            code_path.write_text(code or "", encoding="utf-8")
            args_path.write_text(json.dumps(args), encoding="utf-8")
            wrapper_path.write_text(_build_wrapper_script(code_path, args_path), encoding="utf-8")

            cmd = [self.pvpython_binary, str(wrapper_path)]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # Own process group, so the whole pvpython tree can be signalled.
                start_new_session=True,
            )
            if process_holder is not None:
                process_holder["process"] = proc

            # Drain both pipes into buffers we own, rather than communicate().
            # communicate() discards everything it has read when it is
            # cancelled, which loses exactly the output needed to debug the
            # script that hung.
            out_capture = _StreamCapture()
            err_capture = _StreamCapture()
            tasks = {
                asyncio.ensure_future(_drain(proc.stdout, out_capture)),
                asyncio.ensure_future(_drain(proc.stderr, err_capture)),
                asyncio.ensure_future(proc.wait()),
            }
            timeout = timeout_seconds if timeout_seconds and timeout_seconds > 0 else None

            try:
                _, pending = await asyncio.wait(tasks, timeout=timeout)
            except asyncio.CancelledError:
                _signal_tree(proc, signal.SIGTERM)
                await _settle(tasks, proc=proc)
                elapsed = time.monotonic() - start
                return {
                    "result": None,
                    "stdout": _cap_output(out_capture.text()),
                    "stderr": _cap_output(err_capture.text()),
                    "error": "Execution cancelled",
                    "duration_seconds": round(elapsed, 4),
                    "timed_out": False,
                    "cancelled": True,
                }

            if pending:
                _signal_tree(proc, signal.SIGKILL)
                await _settle(tasks, proc=proc)
                elapsed = time.monotonic() - start
                return {
                    "result": None,
                    "stdout": _cap_output(out_capture.text()),
                    "stderr": _cap_output(err_capture.text()),
                    "error": f"Execution exceeded timeout of {timeout_seconds}s",
                    "duration_seconds": round(elapsed, 4),
                    "timed_out": True,
                    "cancelled": False,
                }

            stdout_b = out_capture.value()
            stderr_b = err_capture.value()

        elapsed = time.monotonic() - start
        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        try:
            payload, clean_stdout = _extract_payload(stdout)
        except json.JSONDecodeError as exc:
            error = f"Headless pvpython returned an invalid result payload: {exc}"
            if stderr.strip():
                error = f"{error}\n{stderr.strip()}"
            return {
                "result": None,
                "stdout": _cap_output(stdout),
                "stderr": _cap_output(stderr),
                "error": error,
                "duration_seconds": round(elapsed, 4),
                "timed_out": False,
                "cancelled": False,
            }

        if payload is None:
            error = f"Headless pvpython exited with code {proc.returncode} without a result payload"
            if stderr.strip():
                error = f"{error}\n{stderr.strip()}"
            return {
                "result": None,
                "stdout": _cap_output(stdout),
                "stderr": _cap_output(stderr),
                "error": error,
                "duration_seconds": round(elapsed, 4),
                "timed_out": False,
                "cancelled": False,
            }

        return {
            "result": _safe_json(payload.get("result")),
            "stdout": _cap_output(clean_stdout + payload.get("stdout", "")),
            "stderr": _cap_output(stderr + payload.get("stderr", "")),
            "error": payload.get("error"),
            "duration_seconds": round(elapsed, 4),
            "timed_out": bool(payload.get("timed_out")),
            "cancelled": bool(payload.get("cancelled")),
        }


class HeadlessJobManager:
    """Track async headless pvpython executions inside the MCP server process."""

    def __init__(self, *, max_jobs: int = DEFAULT_MAX_JOBS, job_ttl_seconds: float = DEFAULT_JOB_TTL_SECONDS):
        self._jobs: dict[str, dict[str, Any]] = {}
        self._max_jobs = max_jobs
        self._job_ttl_seconds = job_ttl_seconds

    def _is_finished(self, job: dict[str, Any]) -> bool:
        return job["status"] in {"succeeded", "failed", "cancelled"}

    def _evict(self) -> None:
        """Drop finished jobs past their TTL, then past the retention cap.

        Each job holds up to 100 KB of captured output, so an MCP server that
        stays up for days would otherwise grow without bound.
        """
        now = time.time()
        for job_id, job in list(self._jobs.items()):
            if not self._is_finished(job):
                continue
            completed_at = job.get("completed_at") or job["created_at"]
            if now - completed_at > self._job_ttl_seconds:
                del self._jobs[job_id]

        finished = [(job["created_at"], job_id) for job_id, job in self._jobs.items() if self._is_finished(job)]
        overflow = len(self._jobs) - self._max_jobs
        if overflow <= 0:
            return
        # Running jobs are never evicted; only completed ones, oldest first.
        for _, job_id in sorted(finished)[:overflow]:
            del self._jobs[job_id]

    async def create_job(
        self,
        executor: HeadlessPvpythonExecutor,
        *,
        code: str | None = None,
        script_path: str | None = None,
        args: dict[str, Any] | None = None,
        timeout_seconds: int | None = None,
    ) -> str:
        job_id = f"headless-job-{uuid.uuid4().hex[:8]}"
        process_holder: dict[str, Any] = {}
        job: dict[str, Any] = {
            "job_id": job_id,
            "status": "queued",
            "created_at": time.time(),
            "started_at": None,
            "completed_at": None,
            "result": None,
            "stdout": "",
            "stderr": "",
            "error": None,
            "cancelled": False,
            "timed_out": False,
            "process_holder": process_holder,
            "task": None,
        }
        self._jobs[job_id] = job
        self._evict()

        async def runner():
            job["status"] = "running"
            job["started_at"] = time.time()
            try:
                result = await executor.execute(
                    code=code,
                    script_path=script_path,
                    args=args,
                    timeout_seconds=timeout_seconds,
                    process_holder=process_holder,
                )
            except asyncio.CancelledError:
                job["error"] = "Execution cancelled"
                job["cancelled"] = True
                job["status"] = "cancelled"
                job["completed_at"] = time.time()
                raise
            except Exception as exc:
                job["error"] = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
                job["status"] = "failed"
                job["completed_at"] = time.time()
            else:
                job["result"] = result.get("result")
                job["stdout"] = result.get("stdout", "")
                job["stderr"] = result.get("stderr", "")
                job["error"] = result.get("error")
                job["cancelled"] = bool(result.get("cancelled"))
                job["timed_out"] = bool(result.get("timed_out"))
                job["completed_at"] = time.time()
                if job["cancelled"]:
                    job["status"] = "cancelled"
                elif job["error"]:
                    job["status"] = "failed"
                else:
                    job["status"] = "succeeded"
            finally:
                process_holder.pop("process", None)

        job["task"] = asyncio.create_task(runner())
        return job_id

    def get_status(self, job_id: str) -> dict[str, Any]:
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError(f"Unknown job: {job_id}")
        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "created_at": job["created_at"],
            "started_at": job["started_at"],
            "completed_at": job["completed_at"],
            "result": job["result"],
            "stdout": job["stdout"],
            "stderr": job["stderr"],
            "error": job["error"],
            "cancelled": job["cancelled"],
            "timed_out": job["timed_out"],
        }

    def list_jobs(self) -> dict[str, Any]:
        jobs = [
            {
                "job_id": job["job_id"],
                "status": job["status"],
                "created_at": job["created_at"],
            }
            for job in self._jobs.values()
        ]
        return {"jobs": jobs}

    async def cancel(self, job_id: str) -> dict[str, Any]:
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError(f"Unknown job: {job_id}")

        proc = job["process_holder"].get("process")
        if proc is not None and proc.returncode is None:
            _signal_tree(proc, signal.SIGTERM)
        task = job.get("task")
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if job["status"] in {"queued", "running"}:
            job["status"] = "cancelled"
            job["completed_at"] = time.time()
            job["cancelled"] = True
        return {"job_id": job_id, "status": job["status"]}
