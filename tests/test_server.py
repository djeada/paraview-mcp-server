"""Tests for the ParaView MCP server — tool registration, connection handling, JSON schemas."""

import asyncio
import json
import signal
import sys
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from paraview_mcp_server import headless as headless_module
from paraview_mcp_server.headless import HeadlessJobManager, HeadlessPvpythonExecutor
from paraview_mcp_server.server import (
    HEADLESS_JOB_MANAGER,
    ParaViewConnection,
    export_animation,
    export_screenshot,
    filter_stream_tracer,
    job_cancel,
    job_list,
    job_status,
    main,
    mcp,
    python_exec,
    python_exec_async,
    scene_get_info,
    scene_list_sources,
    session_start,
    session_status,
    session_stop,
    source_open_file,
)


class TestToolRegistration:
    """Verify all expected tools are registered with correct metadata."""

    def _get_tool_names(self):
        return [t.name for t in mcp._tool_manager._tools.values()]

    def test_scene_tools_registered(self):
        names = self._get_tool_names()
        assert "paraview_session_status" in names
        assert "paraview_session_start" in names
        assert "paraview_session_stop" in names
        assert "paraview_scene_get_info" in names
        assert "paraview_scene_list_sources" in names
        assert "paraview_scene_list_views" in names
        assert "paraview_source_get_properties" in names

    def test_source_tools_registered(self):
        names = self._get_tool_names()
        assert "paraview_source_open_file" in names
        assert "paraview_source_delete" in names
        assert "paraview_source_rename" in names

    def test_basic_filter_tools_registered(self):
        names = self._get_tool_names()
        for tool in [
            "paraview_filter_slice",
            "paraview_filter_clip",
            "paraview_filter_contour",
            "paraview_filter_threshold",
        ]:
            assert tool in names

    def test_advanced_filter_tools_registered(self):
        names = self._get_tool_names()
        for tool in [
            "paraview_filter_calculator",
            "paraview_filter_stream_tracer",
            "paraview_filter_glyph",
        ]:
            assert tool in names

    def test_display_tools_registered(self):
        names = self._get_tool_names()
        for tool in [
            "paraview_display_show",
            "paraview_display_hide",
            "paraview_display_color_by",
            "paraview_display_set_representation",
            "paraview_display_set_opacity",
            "paraview_display_rescale_transfer_function",
        ]:
            assert tool in names

    def test_view_tools_registered(self):
        names = self._get_tool_names()
        assert "paraview_view_reset_camera" in names
        assert "paraview_view_set_camera" in names
        assert "paraview_view_set_background" in names

    def test_export_tools_registered(self):
        names = self._get_tool_names()
        assert "paraview_export_screenshot" in names
        assert "paraview_export_data" in names
        assert "paraview_export_animation" in names

    def test_python_exec_tools_registered(self):
        names = self._get_tool_names()
        assert "paraview_python_exec" in names
        assert "paraview_python_exec_async" in names

    def test_job_tools_registered(self):
        names = self._get_tool_names()
        assert "paraview_job_status" in names
        assert "paraview_job_cancel" in names
        assert "paraview_job_list" in names

    def test_total_tool_count(self):
        names = self._get_tool_names()
        assert len(names) == 34

    def test_all_tools_have_descriptions(self):
        for tool in mcp._tool_manager._tools.values():
            assert tool.description, f"Tool {tool.name} has no description"

    def test_context_parameter_not_exposed_in_tool_schema(self):
        for tool in mcp._tool_manager._tools.values():
            schema = getattr(tool, "inputSchema", None) or getattr(tool, "parameters", {})
            properties = schema.get("properties", {})
            assert "ctx" not in properties, f"Tool {tool.name} exposes ctx in schema"

    def test_selected_tool_schemas_match_supported_parameters(self):
        expected_properties = {
            "paraview_display_color_by": {"name", "array", "component", "association"},
            "paraview_filter_stream_tracer": {
                "input",
                "seed_type",
                "integration_direction",
                "num_points",
                "max_length",
            },
            "paraview_export_screenshot": {"filepath", "width", "height", "transparent"},
            "paraview_export_animation": {
                "filepath",
                "width",
                "height",
                "frame_rate",
                "frame_start",
                "frame_end",
            },
        }

        for tool in mcp._tool_manager._tools.values():
            if tool.name not in expected_properties:
                continue
            schema = getattr(tool, "inputSchema", None) or getattr(tool, "parameters", {})
            properties = set(schema.get("properties", {}))
            assert properties == expected_properties[tool.name]


class TestParaViewConnection:
    """Test the async TCP client that communicates with the ParaView bridge."""

    @pytest.mark.asyncio
    async def test_send_command_success(self):
        conn = ParaViewConnection()
        response = {"id": "test-id", "success": True, "result": {"source_count": 3}}

        mock_reader = AsyncMock()
        mock_reader.readline = AsyncMock(return_value=json.dumps(response).encode() + b"\n")
        mock_writer = AsyncMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        conn._reader = mock_reader
        conn._writer = mock_writer

        with patch("paraview_mcp_server.server.uuid.uuid4", return_value="test-id"):
            result = await conn.send_command("scene.get_info")
            assert result == {"source_count": 3}

    @pytest.mark.asyncio
    async def test_send_command_error_response(self):
        conn = ParaViewConnection()
        response = {"id": "test-id", "success": False, "error": "Source not found"}

        mock_reader = AsyncMock()
        mock_reader.readline = AsyncMock(return_value=json.dumps(response).encode() + b"\n")
        mock_writer = AsyncMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        conn._reader = mock_reader
        conn._writer = mock_writer

        with (
            patch("paraview_mcp_server.server.uuid.uuid4", return_value="test-id"),
            pytest.raises(RuntimeError, match="Source not found"),
        ):
            await conn.send_command("source.open_file", {"filepath": "/bad/path.vtu"})

    @pytest.mark.asyncio
    async def test_send_command_connection_closed(self):
        conn = ParaViewConnection()
        response = {"id": "retry-id", "success": True, "result": {"source_count": 3}}

        mock_reader = AsyncMock()
        mock_reader.readline = AsyncMock(return_value=b"")
        mock_writer = AsyncMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        conn._reader = mock_reader
        conn._writer = mock_writer

        retry_reader = AsyncMock()
        retry_reader.readline = AsyncMock(return_value=json.dumps(response).encode() + b"\n")
        retry_writer = AsyncMock()
        retry_writer.write = MagicMock()
        retry_writer.drain = AsyncMock()
        retry_writer.close = MagicMock()
        retry_writer.wait_closed = AsyncMock()

        with (
            patch("asyncio.open_connection", return_value=(retry_reader, retry_writer)),
            patch("paraview_mcp_server.server.uuid.uuid4", side_effect=["closed-id", "retry-id"]),
        ):
            result = await conn.send_command("scene.get_info")

        assert result == {"source_count": 3}
        mock_writer.close.assert_called_once()
        mock_writer.wait_closed.assert_awaited_once()
        retry_writer.write.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_command_response_id_mismatch_resets_connection(self):
        conn = ParaViewConnection()
        response = {"id": "retry-id", "success": True, "result": {"ok": True}}

        mock_reader = AsyncMock()
        mock_reader.readline = AsyncMock(
            return_value=json.dumps({"id": "wrong-id", "success": True, "result": {}}).encode() + b"\n"
        )
        mock_writer = AsyncMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        conn._reader = mock_reader
        conn._writer = mock_writer

        retry_reader = AsyncMock()
        retry_reader.readline = AsyncMock(return_value=json.dumps(response).encode() + b"\n")
        retry_writer = AsyncMock()
        retry_writer.write = MagicMock()
        retry_writer.drain = AsyncMock()
        retry_writer.close = MagicMock()
        retry_writer.wait_closed = AsyncMock()

        with (
            patch("asyncio.open_connection", return_value=(retry_reader, retry_writer)),
            patch("paraview_mcp_server.server.uuid.uuid4", side_effect=["test-id", "retry-id"]),
        ):
            result = await conn.send_command("scene.get_info")

        assert result == {"ok": True}
        mock_writer.close.assert_called_once()
        mock_writer.wait_closed.assert_awaited_once()
        retry_writer.write.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        conn = ParaViewConnection(host="127.0.0.1", port=19998)
        with pytest.raises(OSError):
            await conn.connect()

    @pytest.mark.asyncio
    async def test_auto_reconnect_on_first_call(self):
        conn = ParaViewConnection()
        response = {"id": "test-id", "success": True, "result": {}}

        mock_reader = AsyncMock()
        mock_reader.readline = AsyncMock(return_value=json.dumps(response).encode() + b"\n")
        mock_writer = AsyncMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        with (
            patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)),
            patch("paraview_mcp_server.server.uuid.uuid4", return_value="test-id"),
        ):
            result = await conn.send_command("scene.get_info")
            assert result == {}

    @pytest.mark.asyncio
    async def test_disconnect_clears_state(self):
        conn = ParaViewConnection()
        mock_writer = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()
        conn._reader = AsyncMock()
        conn._writer = mock_writer

        await conn.disconnect()
        assert conn._writer is None
        assert conn._reader is None


class TestMCPToolFunctions:
    """Test individual tool functions with mocked connections."""

    def _make_ctx(self, return_value):
        ctx = MagicMock()
        conn = MagicMock()
        conn.send_command = AsyncMock(return_value=return_value)
        ctx.request_context.lifespan_context = conn
        return ctx, conn

    @pytest.mark.asyncio
    async def test_scene_get_info(self):
        ctx, conn = self._make_ctx({"source_count": 2, "active_view_type": "RenderView"})
        result = json.loads(await scene_get_info(ctx))
        assert result["source_count"] == 2
        conn.send_command.assert_awaited_once_with("scene.get_info")

    @pytest.mark.asyncio
    async def test_session_status_reports_bridge_and_process_state(self):
        ctx = MagicMock()
        with patch("paraview_mcp_server.server._port_is_open", return_value=True):
            result = json.loads(await session_status(ctx))

        assert result["bridge"]["reachable"] is True
        assert result["session_process"]["managed"] is False

    @pytest.mark.asyncio
    async def test_session_start_launches_managed_session_when_bridge_is_not_running(self):
        ctx = MagicMock()
        proc = MagicMock()
        proc.pid = 123
        proc.poll.return_value = None

        with (
            patch("paraview_mcp_server.server.SESSION_PROCESS", None),
            patch("paraview_mcp_server.server._port_is_open", return_value=False),
            patch("paraview_mcp_server.server._wait_for_open_port", return_value=True),
            patch("paraview_mcp_server.server._start_process", return_value=proc) as start_process,
        ):
            result = json.loads(await session_start(ctx, wait_seconds=0.1))

        assert result["started"] is True
        assert result["mode"] == "managed_session"
        assert result["bridge_reachable"] is True
        assert result["command"][:3] == [sys.executable, "-m", "paraview_mcp_server.launcher"]
        start_process.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_start_refuses_unmanaged_existing_bridge(self):
        ctx = MagicMock()

        with (
            patch("paraview_mcp_server.server.SESSION_PROCESS", None),
            patch("paraview_mcp_server.server._port_is_open", return_value=True),
            patch("paraview_mcp_server.server._start_process") as start_process,
        ):
            result = json.loads(await session_start(ctx, wait_seconds=0.1))

        assert result["started"] is False
        assert result["mode"] == "existing_bridge_not_managed"
        assert result["bridge_reachable"] is True
        start_process.assert_not_called()

    @pytest.mark.asyncio
    async def test_session_stop_terminates_managed_process(self):
        ctx = MagicMock()
        proc = MagicMock()
        proc.pid = 789
        proc.poll.return_value = None
        proc.returncode = 0

        with patch("paraview_mcp_server.server.SESSION_PROCESS", proc):
            result = json.loads(await session_stop(ctx))

        assert result == {"stopped": True, "returncode": 0, "pid": 789}
        proc.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_scene_list_sources(self):
        ctx, conn = self._make_ctx({"sources": [{"name": "disk.vtu", "id": "1"}]})
        result = json.loads(await scene_list_sources(ctx))
        assert len(result["sources"]) == 1
        conn.send_command.assert_awaited_once_with("scene.list_sources")

    @pytest.mark.asyncio
    async def test_source_open_file(self):
        ctx, conn = self._make_ctx({"name": "disk_out_ref.ex2", "filepath": "/data/disk.ex2"})
        result = json.loads(await source_open_file(ctx, filepath="/data/disk.ex2"))
        assert result["filepath"] == "/data/disk.ex2"
        conn.send_command.assert_awaited_once_with("source.open_file", {"filepath": "/data/disk.ex2"})

    @pytest.mark.asyncio
    async def test_export_screenshot(self):
        ctx, conn = self._make_ctx({"filepath": "/tmp/shot.png", "resolution": [1920, 1080]})
        result = json.loads(
            await export_screenshot(ctx, filepath="/tmp/shot.png", width=1920, height=1080, transparent=True)
        )
        assert result["resolution"] == [1920, 1080]
        conn.send_command.assert_awaited_once_with(
            "export.screenshot",
            {"filepath": "/tmp/shot.png", "width": 1920, "height": 1080, "transparent": True},
        )

    @pytest.mark.asyncio
    async def test_export_animation_forwards_frame_window(self):
        ctx, conn = self._make_ctx({"filepath": "/tmp/anim.avi", "frame_start": 1, "frame_end": 5})
        result = json.loads(await export_animation(ctx, filepath="/tmp/anim.avi", frame_start=1, frame_end=5))
        assert result["frame_start"] == 1
        assert result["frame_end"] == 5
        conn.send_command.assert_awaited_once_with(
            "export.animation",
            {
                "filepath": "/tmp/anim.avi",
                "width": 1920,
                "height": 1080,
                "frame_rate": 15,
                "frame_start": 1,
                "frame_end": 5,
            },
        )

    @pytest.mark.asyncio
    async def test_filter_stream_tracer_forwards_integration_direction(self):
        ctx, conn = self._make_ctx({"filter": "StreamTracer", "integration_direction": "BACKWARD"})
        result = json.loads(
            await filter_stream_tracer(
                ctx,
                input="disk.ex2",
                integration_direction="BACKWARD",
            )
        )
        assert result["integration_direction"] == "BACKWARD"
        conn.send_command.assert_awaited_once_with(
            "filter.stream_tracer",
            {
                "input": "disk.ex2",
                "seed_type": "Point Cloud",
                "integration_direction": "BACKWARD",
                "num_points": 100,
                "max_length": 1.0,
            },
        )

    @pytest.mark.asyncio
    async def test_python_exec_bridge(self):
        ctx, conn = self._make_ctx(
            {"result": {"ok": True}, "stdout": "", "stderr": "", "error": None, "duration_seconds": 0.01}
        )
        result = json.loads(await python_exec(ctx, code="__result__ = {'ok': True}"))
        assert result["result"] == {"ok": True}
        conn.send_command.assert_awaited_once_with("python.execute", {"code": "__result__ = {'ok': True}"})


class _FakeStream:
    """Minimal asyncio.StreamReader stand-in that yields bytes then EOF."""

    def __init__(self, data: bytes, chunk_size: int = 4096):
        self._data = data
        self._chunk_size = chunk_size

    async def read(self, size: int = -1) -> bytes:
        if not self._data:
            return b""
        take = self._chunk_size if size is None or size < 0 else min(size, self._chunk_size)
        chunk, self._data = self._data[:take], self._data[take:]
        return chunk


def _fake_proc(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0, wait_forever: bool = False):
    proc = MagicMock()
    proc.stdout = _FakeStream(stdout)
    proc.stderr = _FakeStream(stderr)
    # A process that never exits has no returncode yet; _signal_tree relies on
    # that to know whether there is still anything to signal.
    proc.returncode = None if wait_forever else returncode
    proc.pid = 424242

    async def _wait():
        if wait_forever:
            await asyncio.Event().wait()
        return returncode

    proc.wait = _wait
    proc.kill = MagicMock()
    proc.terminate = MagicMock()
    return proc


class TestHeadlessExecutor:
    """Test the headless pvpython executor."""

    @pytest.mark.asyncio
    async def test_execute_parses_structured_payload(self):
        executor = HeadlessPvpythonExecutor(pvpython_binary="pvpython")
        payload = {
            "result": {"ok": True},
            "stdout": "inner stdout\n",
            "stderr": "",
            "error": None,
            "timed_out": False,
            "cancelled": False,
        }

        proc = _fake_proc(stdout=("noise before\n__PARAVIEW_MCP_RESULT__=" + json.dumps(payload) + "\n").encode())

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await executor.execute(code="__result__ = {'ok': True}")

        assert result["result"] == {"ok": True}
        assert "noise before" in result["stdout"]
        assert "inner stdout" in result["stdout"]
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_execute_invalid_payload_returns_error(self):
        executor = HeadlessPvpythonExecutor(pvpython_binary="pvpython")

        proc = _fake_proc(stdout=b"__PARAVIEW_MCP_RESULT__={not-json}\n")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await executor.execute(code="__result__ = {'ok': True}")

        assert result["result"] is None
        assert "invalid result payload" in result["error"]


class TestHeadlessExecutorRobustness:
    """Regressions for the stream-draining rewrite."""

    @pytest.mark.asyncio
    async def test_timeout_preserves_output_written_before_the_kill(self):
        """A hung script's earlier output is exactly what is needed to debug it.

        communicate() discards everything it read when cancelled, so the old
        implementation reported an empty stdout for every timeout.
        """
        executor = HeadlessPvpythonExecutor(pvpython_binary="pvpython")
        proc = _fake_proc(stdout=b"progress: step 1\n", wait_forever=True)

        killed: list[tuple[int, int]] = []
        with (
            patch("asyncio.create_subprocess_exec", return_value=proc),
            patch("os.getpgid", return_value=proc.pid),
            patch("os.killpg", side_effect=lambda pgid, sig: killed.append((pgid, sig))),
        ):
            result = await executor.execute(code="hang()", timeout_seconds=1)

        assert result["timed_out"] is True
        assert "progress: step 1" in result["stdout"]
        assert killed, "the timed-out process tree must be signalled"

    @pytest.mark.asyncio
    async def test_non_bytes_stream_does_not_spin(self):
        """A pipe that never yields bytes must end the drain, not loop forever.

        A bare AsyncMock returns a truthy MagicMock from read(), which an
        unguarded `if not chunk: break` never terminates on — it allocates
        until the machine dies.
        """
        executor = HeadlessPvpythonExecutor(pvpython_binary="pvpython")
        proc = AsyncMock()
        proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await asyncio.wait_for(executor.execute(code="x = 1"), timeout=10)

        assert result["result"] is None
        assert "without a result payload" in result["error"]

    def test_stream_capture_is_bounded_and_keeps_head_and_tail(self):
        capture = headless_module._StreamCapture(limit=1000)
        capture.feed(b"HEAD" + b"." * 500)
        capture.feed(b"M" * 100_000)
        capture.feed(b"__PARAVIEW_MCP_RESULT__=TAIL\n")

        value = capture.value()
        assert capture.total == 504 + 100_000 + 29
        assert len(value) < 2000, "capture must stay bounded regardless of volume"
        assert value.startswith(b"HEAD")
        assert value.endswith(b"__PARAVIEW_MCP_RESULT__=TAIL\n")
        assert b"dropped" in value


class TestHeadlessJobRetention:
    """The job table must not grow without bound in a long-lived server."""

    def test_finished_jobs_are_evicted_past_the_cap(self):
        manager = HeadlessJobManager(max_jobs=3)
        now = time.time()
        for index in range(10):
            manager._jobs[f"job-{index}"] = {
                "job_id": f"job-{index}",
                "status": "succeeded",
                "created_at": now + index,
                "completed_at": now + index,
            }
        manager._evict()

        assert len(manager._jobs) == 3
        # Oldest first: the survivors are the most recent three.
        assert set(manager._jobs) == {"job-7", "job-8", "job-9"}

    def test_running_jobs_are_never_evicted(self):
        manager = HeadlessJobManager(max_jobs=1)
        now = time.time()
        manager._jobs["running"] = {
            "job_id": "running",
            "status": "running",
            "created_at": now,
            "completed_at": None,
        }
        for index in range(5):
            manager._jobs[f"done-{index}"] = {
                "job_id": f"done-{index}",
                "status": "succeeded",
                "created_at": now + index + 1,
                "completed_at": now + index + 1,
            }
        manager._evict()

        assert "running" in manager._jobs

    def test_finished_jobs_expire_after_their_ttl(self):
        manager = HeadlessJobManager(max_jobs=100, job_ttl_seconds=60)
        manager._jobs["stale"] = {
            "job_id": "stale",
            "status": "succeeded",
            "created_at": time.time() - 10_000,
            "completed_at": time.time() - 10_000,
        }
        manager._jobs["fresh"] = {
            "job_id": "fresh",
            "status": "succeeded",
            "created_at": time.time(),
            "completed_at": time.time(),
        }
        manager._evict()

        assert set(manager._jobs) == {"fresh"}


class TestHeadlessTransportTools:
    """Test tools that support headless transport."""

    @pytest.mark.asyncio
    async def test_python_exec_uses_headless_transport(self):
        ctx = MagicMock()
        ctx.request_context.lifespan_context = MagicMock()

        with patch(
            "paraview_mcp_server.server.HeadlessPvpythonExecutor.execute",
            new=AsyncMock(return_value={"result": {"mode": "headless"}}),
        ) as execute:
            result = await python_exec(
                ctx,
                code="__result__ = {'mode': 'headless'}",
                transport="headless",
            )

        assert json.loads(result) == {"result": {"mode": "headless"}}
        execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_headless_async_job_lifecycle(self):
        HEADLESS_JOB_MANAGER._jobs.clear()
        ctx = MagicMock()
        ctx.request_context.lifespan_context = MagicMock()

        with patch(
            "paraview_mcp_server.server.HeadlessPvpythonExecutor.execute",
            new=AsyncMock(
                return_value={
                    "result": {"ok": True},
                    "stdout": "",
                    "stderr": "",
                    "error": None,
                    "cancelled": False,
                    "timed_out": False,
                }
            ),
        ):
            created = json.loads(await python_exec_async(ctx, code="__result__ = {'ok': True}"))
            job_id = created["job_id"]
            await asyncio.sleep(0)
            status = json.loads(await job_status(ctx, job_id))

        assert job_id.startswith("headless-job-")
        assert status["status"] == "succeeded"
        assert status["result"] == {"ok": True}

    @pytest.mark.asyncio
    async def test_job_list_returns_headless_jobs(self):
        HEADLESS_JOB_MANAGER._jobs.clear()
        HEADLESS_JOB_MANAGER._jobs["headless-job-1"] = {
            "job_id": "headless-job-1",
            "status": "queued",
            "created_at": 1.0,
        }
        ctx = MagicMock()
        result = json.loads(await job_list(ctx))

        ids = {job["job_id"] for job in result["jobs"]}
        assert ids == {"headless-job-1"}

    @pytest.mark.asyncio
    async def test_headless_job_cancel(self):
        HEADLESS_JOB_MANAGER._jobs.clear()
        ctx = MagicMock()
        ctx.request_context.lifespan_context = MagicMock()

        async def slow_execute(**_kwargs):
            await asyncio.sleep(10)
            return {
                "result": None,
                "stdout": "",
                "stderr": "",
                "error": None,
                "cancelled": False,
                "timed_out": False,
            }

        with patch(
            "paraview_mcp_server.server.HeadlessPvpythonExecutor.execute",
            new=slow_execute,
        ):
            created = json.loads(await python_exec_async(ctx, code="pass"))
            job_id = created["job_id"]
            cancelled = json.loads(await job_cancel(ctx, job_id))

        assert cancelled["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_headless_async_job_records_executor_exception(self):
        HEADLESS_JOB_MANAGER._jobs.clear()
        ctx = MagicMock()
        ctx.request_context.lifespan_context = MagicMock()

        async def broken_execute(self, **_kwargs):
            raise RuntimeError("executor exploded")

        with patch(
            "paraview_mcp_server.server.HeadlessPvpythonExecutor.execute",
            new=broken_execute,
        ):
            created = json.loads(await python_exec_async(ctx, code="pass"))
            job_id = created["job_id"]
            await asyncio.sleep(0)
            status = json.loads(await job_status(ctx, job_id))

        assert status["status"] == "failed"
        assert "executor exploded" in status["error"]


class TestMCPEntrypoint:
    """Test the MCP server entrypoint configuration."""

    def test_main_runs_stdio_transport(self):
        with patch.object(mcp, "run") as run:
            main()
        run.assert_called_once_with(transport="stdio")


class TestTransportValidation:
    @pytest.mark.asyncio
    async def test_unknown_transport_is_rejected(self):
        """'Headless' used to fall through silently to the bridge transport."""
        ctx = MagicMock()
        conn = AsyncMock()
        ctx.request_context.lifespan_context = conn

        with pytest.raises(ValueError, match="transport must be one of"):
            await python_exec(ctx, code="x = 1", transport="Headless")

        conn.send_command.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_bridge_transport_is_the_default(self):
        ctx = MagicMock()
        conn = AsyncMock()
        conn.send_command = AsyncMock(return_value={"result": 1})
        ctx.request_context.lifespan_context = conn

        await python_exec(ctx, code="x = 1")

        conn.send_command.assert_awaited_once()


class TestConnectionAuth:
    @pytest.mark.asyncio
    async def test_requests_carry_the_bridge_token(self, isolated_state_dir):
        from paraview_mcp_bridge import runtime

        token = runtime.create_token()

        sent: list[bytes] = []
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        mock_writer.write = MagicMock(side_effect=sent.append)
        mock_writer.drain = AsyncMock()

        conn = ParaViewConnection()

        async def fake_connect():
            conn._reader, conn._writer = mock_reader, mock_writer

        request_ids = []

        async def fake_readline():
            payload = json.loads(sent[-1])
            request_ids.append(payload["id"])
            return json.dumps({"id": payload["id"], "success": True, "result": {}}).encode() + b"\n"

        mock_reader.readline = AsyncMock(side_effect=fake_readline)
        conn.connect = fake_connect

        await conn.send_command("scene.get_info")

        assert json.loads(sent[-1])["token"] == token

    @pytest.mark.asyncio
    async def test_concurrent_calls_share_one_connection(self):
        """connect() outside the lock let racing calls each open a socket."""
        conn = ParaViewConnection()
        connects = 0

        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()

        async def fake_connect():
            nonlocal connects
            connects += 1
            await asyncio.sleep(0.01)  # widen the race window
            conn._reader, conn._writer = mock_reader, mock_writer

        sent_ids: list[str] = []

        def record(data: bytes):
            sent_ids.append(json.loads(data)["id"])

        mock_writer.write = MagicMock(side_effect=record)

        async def fake_readline():
            return json.dumps({"id": sent_ids[-1], "success": True, "result": {}}).encode() + b"\n"

        mock_reader.readline = AsyncMock(side_effect=fake_readline)
        conn.connect = fake_connect

        await asyncio.gather(*(conn.send_command("scene.get_info") for _ in range(5)))

        assert connects == 1


class TestSessionStartReporting:
    @pytest.mark.asyncio
    async def test_failed_start_includes_the_log_tail(self, isolated_state_dir):
        """Otherwise the caller sees 'started: false' with no reason at all."""
        import paraview_mcp_server.server as server_module

        log_path = isolated_state_dir / "launch.log"
        log_path.write_text("Could not find start_paraview_bridge.py\n", encoding="utf-8")

        dead = MagicMock()
        dead.poll.return_value = 2
        dead.pid = 4321

        ctx = MagicMock()
        with (
            patch.object(server_module, "SESSION_LOG_PATH", log_path),
            patch.object(server_module, "SESSION_PROCESS", None),
            patch("paraview_mcp_server.server._port_is_open", return_value=False),
            patch("paraview_mcp_server.server._wait_for_open_port", return_value=False),
            patch("paraview_mcp_server.server._start_process", return_value=dead),
        ):
            result = json.loads(await session_start(ctx, wait_seconds=0.01))

        assert result["started"] is False
        assert "start_paraview_bridge.py" in result["log_tail"]


class TestCancellationKillsTheProcessTree:
    """Regression: cancelling a job left the real ParaView process running.

    `pvpython` is a launcher that forks `pvpython-real` and waits for it.
    Signalling only the direct child left the script running forever, holding
    CPU and pipes. Children now get their own process group.
    """

    @pytest.mark.asyncio
    async def test_subprocess_is_started_in_its_own_session(self):
        executor = HeadlessPvpythonExecutor(pvpython_binary="pvpython")
        captured: dict[str, Any] = {}

        async def fake_exec(*args, **kwargs):
            captured.update(kwargs)
            proc = MagicMock()
            proc.stdout = _FakeStream(b"__PARAVIEW_MCP_RESULT__=" + json.dumps({"result": 1}).encode() + b"\n")
            proc.stderr = _FakeStream(b"")
            proc.returncode = 0

            async def _wait():
                return 0

            proc.wait = _wait
            return proc

        with patch("asyncio.create_subprocess_exec", new=fake_exec):
            await executor.execute(code="x = 1")

        assert captured.get("start_new_session") is True, (
            "without its own process group, only the pvpython launcher gets signalled"
        )

    @pytest.mark.asyncio
    async def test_timeout_signals_the_whole_group(self):
        executor = HeadlessPvpythonExecutor(pvpython_binary="pvpython")
        proc = _fake_proc(stdout=b"", wait_forever=True)
        proc.pid = 4242

        killed: list[tuple[int, int]] = []

        with (
            patch("asyncio.create_subprocess_exec", return_value=proc),
            patch("os.getpgid", return_value=4242),
            patch("os.killpg", side_effect=lambda pgid, sig: killed.append((pgid, sig))),
        ):
            result = await executor.execute(code="hang()", timeout_seconds=1)

        assert result["timed_out"] is True
        assert (4242, signal.SIGKILL) in killed, "the process group must be killed, not just the child"

    @pytest.mark.asyncio
    async def test_job_cancel_signals_the_whole_group(self):
        manager = HeadlessJobManager()
        executor = HeadlessPvpythonExecutor(pvpython_binary="pvpython")

        proc = MagicMock()
        proc.pid = 5150
        proc.returncode = None

        started = asyncio.Event()

        async def never_finishes(**kwargs):
            holder = kwargs.get("process_holder")
            if holder is not None:
                holder["process"] = proc
            started.set()
            await asyncio.Event().wait()

        killed: list[tuple[int, int]] = []
        with patch.object(executor, "execute", new=never_finishes):
            job_id = await manager.create_job(executor, code="import time; time.sleep(600)")
            await asyncio.wait_for(started.wait(), timeout=5)
            with (
                patch("os.getpgid", return_value=5150),
                patch("os.killpg", side_effect=lambda pgid, sig: killed.append((pgid, sig))),
            ):
                result = await manager.cancel(job_id)

        assert result["status"] == "cancelled"
        assert (5150, signal.SIGTERM) in killed, "cancel must reach pvpython-real, not just the launcher"
