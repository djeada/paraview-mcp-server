"""Tests for the ParaView MCP server — tool registration, connection handling, JSON schemas."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from paraview_mcp_server.headless import HeadlessPvpythonExecutor
from paraview_mcp_server.server import (
    HEADLESS_JOB_MANAGER,
    ParaViewConnection,
    export_screenshot,
    job_cancel,
    job_list,
    job_status,
    main,
    mcp,
    python_exec,
    python_exec_async,
    scene_get_info,
    scene_list_sources,
    source_open_file,
)


class TestToolRegistration:
    """Verify all expected tools are registered with correct metadata."""

    def _get_tool_names(self):
        return [t.name for t in mcp._tool_manager._tools.values()]

    def test_scene_tools_registered(self):
        names = self._get_tool_names()
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
        assert len(names) == 31

    def test_all_tools_have_descriptions(self):
        for tool in mcp._tool_manager._tools.values():
            assert tool.description, f"Tool {tool.name} has no description"

    def test_context_parameter_not_exposed_in_tool_schema(self):
        for tool in mcp._tool_manager._tools.values():
            schema = getattr(tool, "inputSchema", None) or getattr(tool, "parameters", {})
            properties = schema.get("properties", {})
            assert "ctx" not in properties, f"Tool {tool.name} exposes ctx in schema"


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

        conn._reader = mock_reader
        conn._writer = mock_writer

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

        conn._reader = mock_reader
        conn._writer = mock_writer

        with pytest.raises(RuntimeError, match="Source not found"):
            await conn.send_command("source.open_file", {"filepath": "/bad/path.vtu"})

    @pytest.mark.asyncio
    async def test_send_command_connection_closed(self):
        conn = ParaViewConnection()

        mock_reader = AsyncMock()
        mock_reader.readline = AsyncMock(return_value=b"")
        mock_writer = AsyncMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()

        conn._reader = mock_reader
        conn._writer = mock_writer

        with pytest.raises(ConnectionError):
            await conn.send_command("scene.get_info")

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

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
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
        result = json.loads(await export_screenshot(ctx, filepath="/tmp/shot.png", width=1920, height=1080))
        assert result["resolution"] == [1920, 1080]
        conn.send_command.assert_awaited_once_with(
            "export.screenshot",
            {"filepath": "/tmp/shot.png", "width": 1920, "height": 1080},
        )

    @pytest.mark.asyncio
    async def test_python_exec_bridge(self):
        ctx, conn = self._make_ctx(
            {"result": {"ok": True}, "stdout": "", "stderr": "", "error": None, "duration_seconds": 0.01}
        )
        result = json.loads(await python_exec(ctx, code="__result__ = {'ok': True}"))
        assert result["result"] == {"ok": True}
        conn.send_command.assert_awaited_once_with("python.execute", {"code": "__result__ = {'ok': True}"})


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

        proc = AsyncMock()
        proc.communicate = AsyncMock(
            return_value=(
                ("noise before\n__PARAVIEW_MCP_RESULT__=" + json.dumps(payload) + "\n").encode(),
                b"",
            )
        )
        proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await executor.execute(code="__result__ = {'ok': True}")

        assert result["result"] == {"ok": True}
        assert "noise before" in result["stdout"]
        assert "inner stdout" in result["stdout"]
        assert result["error"] is None


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


class TestMCPEntrypoint:
    """Test the MCP server entrypoint configuration."""

    def test_main_runs_stdio_transport(self):
        with patch.object(mcp, "run") as run:
            main()
        run.assert_called_once_with(transport="stdio")
