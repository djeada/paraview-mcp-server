"""Tests for the bridge CommandHandler — routing and dispatch logic.

The CommandHandler imports ``paraview.simple`` lazily (inside _import_pv).
These tests patch _import_pv so ParaView does not need to be installed.
"""

from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _make_pv_mock():
    """Return a MagicMock that mimics the paraview.simple API surface."""
    pvs = MagicMock()

    # Provide a fake sources dict
    fake_proxy = MagicMock()
    fake_proxy.GetXMLLabel.return_value = "DiskOut"
    fake_proxy.__class__.__name__ = "ExodusIIReader"
    fake_proxy.ListProperties.return_value = ["FileName", "TimestepValues"]
    fake_proxy.FileName = "/data/disk.ex2"
    fake_proxy.TimestepValues = [0.0, 1.0]

    pvs.GetSources.return_value = {("disk.ex2", 1): fake_proxy}
    fake_view = MagicMock()
    fake_view.GetXMLName.return_value = "RenderView"
    fake_view.__class__.__name__ = "RenderView"
    pvs.GetActiveView.return_value = fake_view
    pvs.GetActiveViewOrCreate.return_value = fake_view
    pvs.GetRenderViews.return_value = [fake_view]
    pvs.GetViews.return_value = [fake_view]
    pvs.OpenDataFile.return_value = fake_proxy
    pvs.Show.return_value = None
    pvs.Hide.return_value = None
    pvs.Delete.return_value = None
    pvs.ResetCamera.return_value = None
    pvs.RenameSource.return_value = None
    pvs.SaveScreenshot.return_value = None
    pvs.SaveData.return_value = None
    pvs.SaveAnimation.return_value = None
    pvs.ColorBy.return_value = None
    pvs.UpdateScalarBars.return_value = None
    pvs.GetDisplayProperties.return_value = MagicMock()
    pvs.GetColorTransferFunction.return_value = MagicMock()

    # Slice filter mock
    slice_mock = MagicMock()
    slice_mock.SliceType = MagicMock()
    slice_mock.SliceType.Origin = [0, 0, 0]
    slice_mock.SliceType.Normal = [1, 0, 0]
    pvs.Slice.return_value = slice_mock

    # Clip filter mock
    clip_mock = MagicMock()
    clip_mock.ClipType = MagicMock()
    clip_mock.ClipType.Origin = [0, 0, 0]
    clip_mock.ClipType.Normal = [1, 0, 0]
    pvs.Clip.return_value = clip_mock

    # Contour filter mock
    contour_mock = MagicMock()
    contour_mock.ContourBy = None
    contour_mock.Isosurfaces = []
    pvs.Contour.return_value = contour_mock

    # Threshold filter mock
    threshold_mock = MagicMock()
    threshold_mock.Scalars = None
    threshold_mock.ThresholdRange = []
    pvs.Threshold.return_value = threshold_mock

    # Calculator filter mock
    calc_mock = MagicMock()
    calc_mock.Function = ""
    calc_mock.ResultArrayName = "Result"
    calc_mock.AttributeType = "Point Data"
    pvs.Calculator.return_value = calc_mock

    # StreamTracer mock
    stream_mock = MagicMock()
    stream_mock.IntegrationDirection = "BOTH"
    stream_mock.MaximumStreamlineLength = 1.0
    pvs.StreamTracer.return_value = stream_mock

    # Glyph mock
    glyph_mock = MagicMock()
    glyph_mock.ScaleFactor = 1.0
    pvs.Glyph.return_value = glyph_mock

    # Camera mock for view.set_camera
    camera_mock = MagicMock()
    camera_mock.GetPosition.return_value = (1, 2, 3)
    camera_mock.GetFocalPoint.return_value = (0, 0, 0)
    camera_mock.GetViewUp.return_value = (0, 1, 0)
    camera_state = {"parallel_scale": 1.0}
    camera_mock.GetParallelScale.side_effect = lambda: camera_state["parallel_scale"]
    camera_mock.SetParallelScale.side_effect = lambda value: camera_state.__setitem__("parallel_scale", value)
    fake_view.GetActiveCamera.return_value = camera_mock

    return pvs


@pytest.fixture()
def handler(monkeypatch):
    """Provide a CommandHandler with _import_pv patched to return a mock pvs."""
    from paraview_mcp_bridge.command_handler import CommandHandler

    monkeypatch.setenv("PARAVIEW_MCP_GUI_BRIDGE", "1")
    h = CommandHandler()
    pvs = _make_pv_mock()
    h._import_pv = lambda: pvs  # type: ignore[method-assign]
    return h, pvs


@pytest.fixture()
def safe_handler(monkeypatch):
    """Provide a separate pvpython bridge handler with render control disabled."""
    from paraview_mcp_bridge.command_handler import CommandHandler

    monkeypatch.delenv("PARAVIEW_MCP_GUI_BRIDGE", raising=False)
    monkeypatch.delenv("PARAVIEW_MCP_ALLOW_DETACHED_RENDER_WINDOW", raising=False)
    monkeypatch.delenv("PARAVIEW_MCP_ALLOW_VIEW_CREATE", raising=False)
    h = CommandHandler()
    pvs = _make_pv_mock()
    h._import_pv = lambda: pvs  # type: ignore[method-assign]
    return h, pvs


class TestCommandRouting:
    def test_unknown_command_raises(self, handler):
        h, _ = handler
        with pytest.raises(ValueError, match="Unknown command"):
            h.handle("does.not_exist", {})

    def test_known_commands_are_callable(self, handler):
        h, _ = handler
        expected = {
            "scene.get_info",
            "scene.list_sources",
            "scene.list_views",
            "source.get_properties",
            "source.open_file",
            "source.delete",
            "source.rename",
            "display.show",
            "display.hide",
            "display.color_by",
            "display.set_representation",
            "display.set_opacity",
            "display.rescale_transfer_function",
            "view.reset_camera",
            "view.set_camera",
            "view.set_background",
            "export.screenshot",
            "export.data",
            "export.animation",
            "filter.slice",
            "filter.clip",
            "filter.contour",
            "filter.threshold",
            "filter.calculator",
            "filter.stream_tracer",
            "filter.glyph",
            "python.execute",
        }
        assert set(h._handlers.keys()) == expected


class TestSceneHandlers:
    def test_scene_get_info(self, handler):
        h, pvs = handler
        result = h.handle("scene.get_info", {})
        assert "source_count" in result
        assert "active_view_type" in result
        assert result["render_view_available"] is True

    def test_scene_list_sources(self, handler):
        h, pvs = handler
        result = h.handle("scene.list_sources", {})
        assert "sources" in result
        sources = result["sources"]
        assert len(sources) == 1
        assert sources[0]["name"] == "disk.ex2"

    def test_scene_list_views(self, handler):
        h, pvs = handler
        result = h.handle("scene.list_views", {})
        assert "views" in result
        assert len(result["views"]) == 1

    def test_source_get_properties(self, handler):
        h, pvs = handler
        result = h.handle("source.get_properties", {"name": "disk.ex2"})
        assert result["name"] == "disk.ex2"
        assert "properties" in result

    def test_source_get_properties_not_found(self, handler):
        h, pvs = handler
        pvs.GetSources.return_value = {}
        with pytest.raises(ValueError, match="not found"):
            h.handle("source.get_properties", {"name": "missing.vtu"})

    def test_scene_get_info_does_not_create_view_when_none_exists(self, safe_handler):
        h, pvs = safe_handler
        pvs.GetActiveView.return_value = None
        pvs.GetRenderViews.return_value = []
        pvs.GetViews.return_value = []
        result = h.handle("scene.get_info", {})
        assert result["active_view_type"] is None
        assert result["render_view_available"] is False
        pvs.GetActiveViewOrCreate.assert_not_called()


class TestDataLoadingHandlers:
    def test_source_open_file(self, handler):
        h, pvs = handler
        result = h.handle("source.open_file", {"filepath": "/data/disk.ex2"})
        assert result["name"] == "disk.ex2"
        assert result["label"] == "DiskOut"
        assert result["filepath"] == "/data/disk.ex2"
        assert result["shown"] is True
        pvs.OpenDataFile.assert_called_once_with("/data/disk.ex2")
        pvs.Show.assert_called()

    def test_source_open_file_does_not_create_view_when_none_exists(self, safe_handler):
        h, pvs = safe_handler
        pvs.GetActiveView.return_value = None
        pvs.GetRenderViews.return_value = []
        pvs.GetViews.return_value = []
        result = h.handle("source.open_file", {"filepath": "/data/disk.ex2"})
        assert result["shown"] is False
        pvs.OpenDataFile.assert_called_once_with("/data/disk.ex2")
        pvs.Show.assert_not_called()
        pvs.GetActiveViewOrCreate.assert_not_called()

    def test_source_open_file_does_not_show_from_separate_bridge(self, safe_handler):
        h, pvs = safe_handler
        result = h.handle("source.open_file", {"filepath": "/data/disk.ex2"})
        assert result["shown"] is False
        pvs.Show.assert_not_called()
        pvs.ResetCamera.assert_not_called()

    def test_source_open_file_returns_none_raises(self, handler):
        h, pvs = handler
        pvs.OpenDataFile.return_value = None
        with pytest.raises(RuntimeError, match="could not open"):
            h.handle("source.open_file", {"filepath": "/bad/path.vtu"})

    def test_source_delete(self, handler):
        h, pvs = handler
        result = h.handle("source.delete", {"name": "disk.ex2"})
        assert result["deleted"] == "disk.ex2"
        pvs.Delete.assert_called_once()

    def test_source_rename(self, handler):
        h, pvs = handler
        result = h.handle("source.rename", {"name": "disk.ex2", "new_name": "renamed"})
        assert result["new_name"] == "renamed"
        pvs.RenameSource.assert_called_once_with("renamed", pvs.GetSources.return_value[("disk.ex2", 1)])


class TestDisplayHandlers:
    def test_display_show(self, handler):
        h, pvs = handler
        result = h.handle("display.show", {"name": "disk.ex2"})
        assert result["shown"] == "disk.ex2"
        pvs.Show.assert_called()

    def test_display_show_refuses_render_control_from_separate_bridge(self, safe_handler):
        h, pvs = safe_handler
        with pytest.raises(RuntimeError, match="Render-view control is disabled"):
            h.handle("display.show", {"name": "disk.ex2"})
        pvs.GetActiveViewOrCreate.assert_not_called()

    def test_display_show_can_create_view_when_explicitly_allowed(self, handler, monkeypatch):
        h, pvs = handler
        pvs.GetActiveView.return_value = None
        pvs.GetRenderViews.return_value = []
        pvs.GetViews.return_value = []
        monkeypatch.setenv("PARAVIEW_MCP_ALLOW_DETACHED_RENDER_WINDOW", "1")
        monkeypatch.delenv("PARAVIEW_MCP_GUI_BRIDGE", raising=False)
        result = h.handle("display.show", {"name": "disk.ex2"})
        assert result["shown"] == "disk.ex2"
        pvs.GetActiveViewOrCreate.assert_called_once_with("RenderView")
        pvs.Show.assert_called()

    def test_display_hide(self, handler):
        h, pvs = handler
        result = h.handle("display.hide", {"name": "disk.ex2"})
        assert result["hidden"] == "disk.ex2"
        pvs.Hide.assert_called()

    def test_display_color_by(self, handler):
        h, pvs = handler
        result = h.handle("display.color_by", {"name": "disk.ex2", "array": "Pressure"})
        assert result["array"] == "Pressure"
        assert result["component"] == -1
        pvs.ColorBy.assert_called_once()
        lut = pvs.GetColorTransferFunction.return_value
        assert lut.VectorMode == "Magnitude"

    def test_display_color_by_component(self, handler):
        h, pvs = handler
        result = h.handle(
            "display.color_by",
            {"name": "disk.ex2", "array": "Pressure", "component": 2, "association": "CELLS"},
        )
        assert result["association"] == "CELLS"
        assert result["component"] == 2
        lut = pvs.GetColorTransferFunction.return_value
        assert lut.VectorMode == "Component"
        assert lut.VectorComponent == 2

    def test_display_set_representation(self, handler):
        h, pvs = handler
        display_mock = pvs.GetDisplayProperties.return_value
        result = h.handle(
            "display.set_representation",
            {"name": "disk.ex2", "representation": "Wireframe"},
        )
        assert result["representation"] == "Wireframe"
        assert display_mock.Representation == "Wireframe"

    def test_display_set_opacity(self, handler):
        h, pvs = handler
        display_mock = pvs.GetDisplayProperties.return_value
        result = h.handle("display.set_opacity", {"name": "disk.ex2", "opacity": 0.5})
        assert result["opacity"] == 0.5
        assert display_mock.Opacity == 0.5

    def test_display_rescale_transfer_function(self, handler):
        h, pvs = handler
        result = h.handle("display.rescale_transfer_function", {"name": "disk.ex2"})
        assert result["rescaled"] is True


class TestViewHandlers:
    def test_view_reset_camera(self, handler):
        h, pvs = handler
        result = h.handle("view.reset_camera", {})
        assert result["reset"] is True
        pvs.ResetCamera.assert_called_once()

    def test_view_set_camera(self, handler):
        h, pvs = handler
        result = h.handle(
            "view.set_camera",
            {"position": [1, 2, 3], "focal_point": [0, 0, 0], "view_up": [0, 1, 0], "parallel_scale": 3.5},
        )
        assert result["position"] == [1, 2, 3]
        assert result["focal_point"] == [0, 0, 0]
        assert result["view_up"] == [0, 1, 0]
        assert result["parallel_scale"] == 3.5

    def test_view_set_background(self, handler):
        h, pvs = handler
        _ = pvs.GetActiveViewOrCreate.return_value
        result = h.handle("view.set_background", {"color": [0.1, 0.2, 0.3]})
        assert result["color"] == [0.1, 0.2, 0.3]
        assert result["gradient"] is False

    def test_view_set_background_gradient(self, handler):
        h, pvs = handler
        result = h.handle(
            "view.set_background",
            {"color": [0.1, 0.2, 0.3], "color2": [0.9, 0.8, 0.7]},
        )
        assert result["gradient"] is True
        assert result["color2"] == [0.9, 0.8, 0.7]


class TestExportHandlers:
    def test_export_screenshot(self, handler):
        h, pvs = handler
        result = h.handle(
            "export.screenshot",
            {"filepath": "/tmp/shot.png", "width": 800, "height": 600},
        )
        assert result["filepath"] == "/tmp/shot.png"
        assert result["resolution"] == [800, 600]
        pvs.SaveScreenshot.assert_called_once()

    def test_export_screenshot_transparent(self, handler):
        h, pvs = handler
        result = h.handle(
            "export.screenshot",
            {"filepath": "/tmp/shot.png", "width": 800, "height": 600, "transparent": True},
        )
        assert result["transparent"] is True
        pvs.SaveScreenshot.assert_called_once_with(
            "/tmp/shot.png",
            pvs.GetActiveViewOrCreate.return_value,
            ImageResolution=[800, 600],
            TransparentBackground=1,
        )

    def test_export_screenshot_defaults(self, handler):
        h, pvs = handler
        result = h.handle("export.screenshot", {"filepath": "/tmp/shot.png"})
        assert result["resolution"] == [1920, 1080]

    def test_export_data(self, handler):
        h, pvs = handler
        result = h.handle("export.data", {"name": "disk.ex2", "filepath": "/tmp/out.vtu"})
        assert result["filepath"] == "/tmp/out.vtu"
        pvs.SaveData.assert_called_once()

    def test_export_animation(self, handler):
        h, pvs = handler
        result = h.handle(
            "export.animation",
            {"filepath": "/tmp/anim.avi", "width": 800, "height": 600, "frame_rate": 30},
        )
        assert result["filepath"] == "/tmp/anim.avi"
        assert result["frame_rate"] == 30
        pvs.SaveAnimation.assert_called_once()

    def test_export_animation_frame_window(self, handler):
        h, pvs = handler
        result = h.handle(
            "export.animation",
            {"filepath": "/tmp/anim.avi", "frame_start": 2, "frame_end": 5},
        )
        assert result["frame_start"] == 2
        assert result["frame_end"] == 5
        pvs.SaveAnimation.assert_called_once_with(
            "/tmp/anim.avi",
            pvs.GetActiveViewOrCreate.return_value,
            ImageResolution=[1920, 1080],
            FrameRate=15,
            FrameWindow=[2, 5],
        )


class TestBasicFilterHandlers:
    def test_filter_slice(self, handler):
        h, pvs = handler
        result = h.handle(
            "filter.slice",
            {"input": "disk.ex2", "origin": [1, 2, 3], "normal": [0, 1, 0]},
        )
        assert result["filter"] == "Slice"
        assert result["origin"] == [1, 2, 3]
        pvs.Slice.assert_called_once()

    def test_filter_slice_does_not_show_from_separate_bridge(self, safe_handler):
        h, pvs = safe_handler
        result = h.handle(
            "filter.slice",
            {"input": "disk.ex2", "origin": [1, 2, 3], "normal": [0, 1, 0]},
        )
        assert result["filter"] == "Slice"
        assert result["shown"] is False
        pvs.Show.assert_not_called()

    def test_filter_slice_defaults(self, handler):
        h, pvs = handler
        result = h.handle("filter.slice", {"input": "disk.ex2"})
        assert result["origin"] == [0.0, 0.0, 0.0]
        assert result["normal"] == [1.0, 0.0, 0.0]

    def test_filter_clip(self, handler):
        h, pvs = handler
        result = h.handle("filter.clip", {"input": "disk.ex2"})
        assert result["filter"] == "Clip"
        pvs.Clip.assert_called_once()

    def test_filter_contour(self, handler):
        h, pvs = handler
        result = h.handle(
            "filter.contour",
            {"input": "disk.ex2", "array": "Pressure", "values": [0.5, 1.0]},
        )
        assert result["filter"] == "Contour"
        assert result["values"] == [0.5, 1.0]
        pvs.Contour.assert_called_once()

    def test_filter_threshold(self, handler):
        h, pvs = handler
        result = h.handle(
            "filter.threshold",
            {"input": "disk.ex2", "array": "Pressure", "lower": 0.1, "upper": 0.9},
        )
        assert result["filter"] == "Threshold"
        assert result["lower"] == 0.1
        assert result["upper"] == 0.9
        pvs.Threshold.assert_called_once()

    def test_filter_source_not_found(self, handler):
        h, pvs = handler
        pvs.GetSources.return_value = {}
        with pytest.raises(ValueError, match="not found"):
            h.handle("filter.slice", {"input": "missing"})


class TestAdvancedFilterHandlers:
    def test_filter_calculator(self, handler):
        h, pvs = handler
        result = h.handle(
            "filter.calculator",
            {"input": "disk.ex2", "expression": "Pressure * 2", "result_name": "Doubled"},
        )
        assert result["filter"] == "Calculator"
        assert result["expression"] == "Pressure * 2"
        assert result["result_name"] == "Doubled"
        pvs.Calculator.assert_called_once()

    def test_filter_calculator_defaults(self, handler):
        h, pvs = handler
        result = h.handle(
            "filter.calculator",
            {"input": "disk.ex2", "expression": "X"},
        )
        assert result["result_name"] == "Result"

    def test_filter_stream_tracer(self, handler):
        h, pvs = handler
        result = h.handle(
            "filter.stream_tracer",
            {"input": "disk.ex2", "num_points": 200, "max_length": 2.0},
        )
        assert result["filter"] == "StreamTracer"
        assert result["num_points"] == 200
        assert result["max_length"] == 2.0
        pvs.StreamTracer.assert_called_once()

    def test_filter_stream_tracer_integration_direction(self, handler):
        h, pvs = handler
        result = h.handle(
            "filter.stream_tracer",
            {"input": "disk.ex2", "integration_direction": "FORWARD"},
        )
        assert result["integration_direction"] == "FORWARD"
        assert pvs.StreamTracer.return_value.IntegrationDirection == "FORWARD"

    def test_filter_glyph(self, handler):
        h, pvs = handler
        result = h.handle(
            "filter.glyph",
            {"input": "disk.ex2", "glyph_type": "Arrow", "scale_factor": 0.5},
        )
        assert result["filter"] == "Glyph"
        assert result["glyph_type"] == "Arrow"
        assert result["scale_factor"] == 0.5
        pvs.Glyph.assert_called_once()

    def test_filter_glyph_with_scale_array(self, handler):
        h, pvs = handler
        result = h.handle(
            "filter.glyph",
            {"input": "disk.ex2", "scale_array": "Velocity"},
        )
        assert result["filter"] == "Glyph"


class TestPythonExecuteHandler:
    def test_python_execute_success(self, handler):
        h, _ = handler
        result = h.handle("python.execute", {"code": "__result__ = 42"})
        assert result["result"] == 42
        assert result["error"] is None

    def test_python_execute_missing_code_raises(self, handler):
        h, _ = handler
        with pytest.raises(ValueError, match="Missing required parameter"):
            h.handle("python.execute", {})

    def test_python_execute_captures_stdout(self, handler):
        h, _ = handler
        result = h.handle("python.execute", {"code": "print('hello from pvpython')"})
        assert "hello from pvpython" in result["stdout"]

    def test_python_execute_captures_error(self, handler):
        h, _ = handler
        result = h.handle("python.execute", {"code": "raise ValueError('oops')"})
        assert result["error"] is not None
        assert "oops" in result["error"]
        assert result["result"] is None

    def test_python_execute_passes_args(self, handler):
        h, _ = handler
        result = h.handle(
            "python.execute",
            {"code": "__result__ = args['x'] + 1", "args": {"x": 41}},
        )
        assert result["result"] == 42

    def test_python_execute_script_path(self, handler):
        h, _ = handler
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("__result__ = 'from file'")
            f.flush()
            try:
                result = h.handle("python.execute", {"script_path": f.name})
                assert result["result"] == "from file"
            finally:
                os.unlink(f.name)

    def test_python_execute_blocks_render_api_from_separate_bridge(self, safe_handler):
        h, _ = safe_handler
        with pytest.raises(RuntimeError, match="detached windows"):
            h.handle("python.execute", {"code": "from paraview.simple import *\nRender()"})

    def test_python_execute_timeout(self, handler):
        h, _ = handler
        result = h.handle(
            "python.execute",
            {"code": "import time; time.sleep(10)", "timeout_seconds": 0.2},
        )
        assert result["timed_out"] is True
        assert "timeout" in result["error"].lower()


class TestExecutionControls:
    """Test the execution controls in bridge/execution.py."""

    def test_standard_library_imports_are_allowed(self):
        from paraview_mcp_bridge.execution import execute_code

        result = execute_code(code="import subprocess\n__result__ = subprocess.__name__")

        assert result["error"] is None
        assert result["result"] == "subprocess"

    def test_output_capping(self):
        from paraview_mcp_bridge.execution import _cap_output

        short = "hello"
        assert _cap_output(short) == "hello"
        long_text = "x" * 60_000
        capped = _cap_output(long_text)
        assert len(capped) < 60_000
        assert "truncated" in capped

    def test_script_path_validation_missing_file(self):
        from paraview_mcp_bridge.execution import _validate_script_path

        with pytest.raises(FileNotFoundError):
            _validate_script_path("/nonexistent/path/script.py")

    def test_code_and_script_path_mutual_exclusion(self):
        from paraview_mcp_bridge.execution import execute_code

        with pytest.raises(ValueError, match="not both"):
            execute_code(code="pass", script_path="/tmp/x.py")

    def test_neither_code_nor_script_path_raises(self):
        from paraview_mcp_bridge.execution import execute_code

        with pytest.raises(ValueError, match="must be provided"):
            execute_code()

    def test_polydata_helper_validates_registration_name(self):
        from paraview_mcp_bridge.execution import _validate_registration_name

        assert _validate_registration_name("Seed Points_1") == "Seed Points_1"
        with pytest.raises(ValueError, match="registration name"):
            _validate_registration_name("../bad")

    def test_polydata_helper_generates_programmable_source_script(self):
        from paraview_mcp_bridge.execution import _build_polydata_programmable_script

        script = _build_polydata_programmable_script(
            {
                "points": [[0, 0, 0], [1, 0, 0]],
                "verts": [[0], [1]],
                "lines": [[0, 1]],
                "polys": [],
                "point_data": {"U_mag": [40.0, 41.0]},
                "cell_data": {},
            }
        )

        assert "self.GetPolyDataOutput().ShallowCopy(polydata)" in script
        assert "GetClientSideObject" not in script
        assert '"U_mag":[40.0,41.0]' in script

    def test_export_animation_requires_complete_frame_window(self, handler):
        h, _ = handler
        with pytest.raises(ValueError, match="provided together"):
            h.handle("export.animation", {"filepath": "/tmp/anim.avi", "frame_start": 1})


class TestExecutionOutputIsolation:
    """Regressions for the process-wide stdout hijack on timeout."""

    def test_timeout_does_not_hijack_process_streams(self):
        """A timed-out script must not leave sys.stdout replaced.

        The worker thread cannot be killed, so a redirect_stdout context it
        never unwinds would leave the bridge's real stdout swallowed for the
        lifetime of the process, silencing its own logging.
        """
        import sys

        from paraview_mcp_bridge.execution import execute_code

        result = execute_code(code="import threading\nthreading.Event().wait()", timeout_seconds=0.3)
        assert result["timed_out"] is True

        captured = io.StringIO()
        real_stdout, real_stderr = sys.stdout, sys.stderr
        try:
            sys.stdout = captured
            print("visible")
        finally:
            sys.stdout = real_stdout
        assert captured.getvalue() == "visible\n"
        assert sys.stderr is real_stderr

    def test_timeout_reports_the_abandoned_thread(self):
        from paraview_mcp_bridge.execution import execute_code

        result = execute_code(code="import threading\nthreading.Event().wait()", timeout_seconds=0.3)
        assert result["abandoned_threads"] >= 1
        assert "still running in the background" in result["error"]

    def test_captured_output_is_bounded(self):
        """A chatty script must not grow the capture buffer without limit."""
        from paraview_mcp_bridge.execution import MAX_OUTPUT_SIZE, execute_code

        result = execute_code(
            code="for _ in range(500):\n    print('x' * 1000)",
            timeout_seconds=30,
        )
        assert result["error"] is None
        assert len(result["stdout"]) <= MAX_OUTPUT_SIZE + 200
        assert "truncated" in result["stdout"]

    def test_bounded_buffer_counts_everything_it_drops(self):
        from paraview_mcp_bridge.execution import _BoundedBuffer

        buffer = _BoundedBuffer(limit=100)
        for _ in range(50):
            buffer.write("y" * 100)

        value = buffer.getvalue()
        assert value.startswith("y" * 100)
        assert "truncated, 5000 total chars" in value
        assert len(value) < 200

    def test_concurrent_scripts_capture_their_own_output(self):
        import threading

        from paraview_mcp_bridge.execution import execute_code

        results: dict[str, dict] = {}

        def run(tag: str) -> None:
            results[tag] = execute_code(code=f"print({tag!r})\n__result__ = {tag!r}", timeout_seconds=5)

        threads = [threading.Thread(target=run, args=(tag,)) for tag in ("alpha", "beta", "gamma")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        for tag in ("alpha", "beta", "gamma"):
            assert results[tag]["stdout"].strip() == tag
            assert results[tag]["result"] == tag


class TestRenderApiGuard:
    """The guard must match real calls, not raw text."""

    def test_comment_mentioning_a_blocked_name_is_allowed(self, safe_handler):
        handler, _pvs = safe_handler
        result = handler.handle(
            "python.execute", {"code": "# Show the user a number\n__result__ = 1", "timeout_seconds": 5}
        )
        assert result["result"] == 1

    def test_unrelated_identifier_is_allowed(self, safe_handler):
        handler, _pvs = safe_handler
        result = handler.handle(
            "python.execute", {"code": "Rendering = 2\n__result__ = Rendering", "timeout_seconds": 5}
        )
        assert result["result"] == 2

    def test_attribute_call_is_blocked(self, safe_handler):
        handler, _pvs = safe_handler
        with pytest.raises(RuntimeError, match="Blocked API"):
            handler.handle("python.execute", {"code": 'pvs.Show(src, pvs.GetActiveViewOrCreate("RenderView"))'})

    def test_bare_name_call_is_blocked(self, safe_handler):
        handler, _pvs = safe_handler
        with pytest.raises(RuntimeError, match="Blocked API"):
            handler.handle("python.execute", {"code": "from paraview.simple import Show\nShow(src)"})

    def test_getattr_indirection_is_blocked(self, safe_handler):
        """The old substring check waved this through."""
        handler, _pvs = safe_handler
        with pytest.raises(RuntimeError, match="Blocked API"):
            handler.handle("python.execute", {"code": "fn = getattr(pvs, 'Show')\nfn(src)"})

    def test_syntax_error_is_left_to_exec(self, safe_handler):
        handler, _pvs = safe_handler
        result = handler.handle("python.execute", {"code": "def (:", "timeout_seconds": 5})
        assert "SyntaxError" in (result["error"] or "")

    def test_shipped_pipeline_library_scripts_pass_the_guard(self, safe_handler):
        """The scripts we ship must work in the mode we ship them for."""
        handler, _pvs = safe_handler
        library = Path(__file__).resolve().parents[1] / "scripts" / "library"
        for name in ("open_dataset.py", "create_slice.py", "create_contour.py"):
            source = (library / name).read_text(encoding="utf-8")
            handler._validate_python_exec_does_not_control_rendering(code=source, script_path=None)

    def test_shipped_render_library_scripts_are_labelled(self):
        """Render-only scripts must say so, since the default bridge rejects them."""
        library = Path(__file__).resolve().parents[1] / "scripts" / "library"
        for name in ("color_by.py", "reset_camera.py", "save_screenshot.py"):
            source = (library / name).read_text(encoding="utf-8")
            assert "RENDER-VIEW SCRIPT" in source


class TestScriptPathValidation:
    def test_approved_root_is_not_a_bare_prefix_match(self, tmp_path, monkeypatch):
        """'/srv/safe' must not also admit '/srv/safe-evil/script.py'."""
        from paraview_mcp_bridge import execution

        safe = tmp_path / "safe"
        evil = tmp_path / "safe-evil"
        safe.mkdir()
        evil.mkdir()
        allowed = safe / "ok.py"
        allowed.write_text("__result__ = 1", encoding="utf-8")
        sneaky = evil / "bad.py"
        sneaky.write_text("__result__ = 2", encoding="utf-8")

        monkeypatch.setattr(execution, "APPROVED_SCRIPT_ROOTS", [str(safe)])

        assert execution._validate_script_path(str(allowed)) == str(allowed.resolve())
        with pytest.raises(PermissionError):
            execution._validate_script_path(str(sneaky))

    def test_roots_can_be_configured_from_the_environment(self, tmp_path, monkeypatch):
        from paraview_mcp_bridge import execution

        safe = tmp_path / "safe"
        safe.mkdir()
        script = safe / "ok.py"
        script.write_text("__result__ = 1", encoding="utf-8")
        outside = tmp_path / "outside.py"
        outside.write_text("__result__ = 2", encoding="utf-8")

        monkeypatch.setattr(execution, "APPROVED_SCRIPT_ROOTS", None)
        monkeypatch.setenv(execution.APPROVED_SCRIPT_ROOTS_ENV, str(safe))

        assert execution._validate_script_path(str(script)) == str(script.resolve())
        with pytest.raises(PermissionError):
            execution._validate_script_path(str(outside))

    def test_inline_code_can_be_disabled_from_the_environment(self, monkeypatch):
        from paraview_mcp_bridge import execution

        monkeypatch.setattr(execution, "ALLOW_INLINE_CODE", None)
        monkeypatch.setenv(execution.ALLOW_INLINE_CODE_ENV, "0")

        with pytest.raises(PermissionError, match="Inline code execution is disabled"):
            execution.execute_code(code="__result__ = 1")


class TestParamValidationRejectsUnknownKeys:
    def test_typo_is_reported_rather_than_forwarded(self):
        from paraview_mcp_bridge.models import BridgeValidationError, SourceOpenFileParams

        with pytest.raises(BridgeValidationError, match="Unknown parameter"):
            SourceOpenFileParams.model_validate({"filepath": "/x.vtu", "filepth": "/y.vtu"})

    def test_known_keys_still_validate(self):
        from paraview_mcp_bridge.models import SourceOpenFileParams

        assert SourceOpenFileParams.model_validate({"filepath": "/x.vtu"}).model_dump() == {"filepath": "/x.vtu"}

    def test_stream_tracer_default_matches_the_handler(self):
        from paraview_mcp_bridge.command_handler import DEFAULT_STREAM_TRACER_SEED_TYPE
        from paraview_mcp_bridge.models import FilterStreamTracerParams

        values = FilterStreamTracerParams.model_validate({"input": "src"}).model_dump()
        assert values["seed_type"] == DEFAULT_STREAM_TRACER_SEED_TYPE


class TestBackgroundColorActuallyApplies:
    """Regression: the tool used to report success while changing nothing."""

    def test_opts_out_of_the_color_palette(self, handler):
        h, pvs = handler
        view = pvs.GetActiveViewOrCreate.return_value
        view.ListProperties.return_value = [
            "Background",
            "Background2",
            "BackgroundColorMode",
            "UseColorPaletteForBackground",
        ]

        result = h.handle("view.set_background", {"color": [0.1, 0.2, 0.3]})

        # ParaView >= 5.10 renders the palette background unless this is cleared,
        # so setting Background alone has no visible effect.
        assert view.UseColorPaletteForBackground == 0
        assert list(view.Background) == [0.1, 0.2, 0.3]
        assert result["gradient"] is False

    def test_older_paraview_without_the_property_still_works(self, handler):
        h, pvs = handler
        view = pvs.GetActiveViewOrCreate.return_value
        view.ListProperties.return_value = ["Background", "Background2", "UseGradientBackground"]

        result = h.handle("view.set_background", {"color": [0.1, 0.2, 0.3], "color2": [0.4, 0.5, 0.6]})

        assert view.UseGradientBackground is True
        assert result["gradient"] is True


class TestFiltersReportTheirCreatedName:
    """Without a name, a caller cannot address the object the filter just made."""

    def test_every_filter_returns_the_new_pipeline_name(self, handler):
        h, pvs = handler
        existing = next(iter(pvs.GetSources.return_value.values()))

        calls = [
            ("filter.slice", {"input": "disk.ex2"}, pvs.Slice),
            ("filter.clip", {"input": "disk.ex2"}, pvs.Clip),
            ("filter.contour", {"input": "disk.ex2", "array": "P", "values": [1.0]}, pvs.Contour),
            ("filter.threshold", {"input": "disk.ex2", "array": "P", "lower": 0.0, "upper": 1.0}, pvs.Threshold),
            ("filter.calculator", {"input": "disk.ex2", "expression": "P*2"}, pvs.Calculator),
            ("filter.stream_tracer", {"input": "disk.ex2"}, pvs.StreamTracer),
            ("filter.glyph", {"input": "disk.ex2"}, pvs.Glyph),
        ]
        for command, params, constructor in calls:
            expected = f"{command.split('.')[1].title()}1"
            # Register the created proxy the way ParaView registers a filter.
            pvs.GetSources.return_value = {
                ("disk.ex2", 1): existing,
                (expected, 2): constructor.return_value,
            }
            result = h.handle(command, params)
            assert "name" in result, f"{command} must report the object it created"
            assert result["name"] == expected, command

    def test_name_is_null_when_it_cannot_be_determined(self, handler):
        """A filter that worked must not fail just because naming did."""
        h, pvs = handler
        existing = next(iter(pvs.GetSources.return_value.values()))
        pvs.GetSources.return_value = {("disk.ex2", 1): existing}

        result = h.handle("filter.slice", {"input": "disk.ex2"})

        assert result["filter"] == "Slice"
        assert result["name"] is None
