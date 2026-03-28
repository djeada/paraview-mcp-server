"""Tests for the bridge CommandHandler — routing and dispatch logic.

The CommandHandler imports ``paraview.simple`` lazily (inside _import_pv).
These tests patch _import_pv so ParaView does not need to be installed.
"""

from __future__ import annotations

import json
import sys
import types
from unittest.mock import MagicMock, patch, call

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
    pvs.GetActiveViewOrCreate.return_value = MagicMock()
    pvs.GetViews.return_value = [MagicMock()]
    pvs.OpenDataFile.return_value = fake_proxy
    pvs.Show.return_value = None
    pvs.Hide.return_value = None
    pvs.Delete.return_value = None
    pvs.ResetCamera.return_value = None
    pvs.RenameSource.return_value = None
    pvs.SaveScreenshot.return_value = None
    pvs.SaveData.return_value = None
    pvs.ColorBy.return_value = None
    pvs.UpdateScalarBars.return_value = None
    pvs.GetDisplayProperties.return_value = MagicMock()

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

    return pvs


@pytest.fixture()
def handler():
    """Provide a CommandHandler with _import_pv patched to return a mock pvs."""
    from bridge.command_handler import CommandHandler
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
            "view.reset_camera",
            "export.screenshot",
            "export.data",
            "filter.slice",
            "filter.clip",
            "filter.contour",
            "filter.threshold",
            "python.execute",
        }
        assert set(h._handlers.keys()) == expected


class TestSceneHandlers:
    def test_scene_get_info(self, handler):
        h, pvs = handler
        result = h.handle("scene.get_info", {})
        assert "source_count" in result
        assert "active_view_type" in result

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


class TestDataLoadingHandlers:
    def test_source_open_file(self, handler):
        h, pvs = handler
        result = h.handle("source.open_file", {"filepath": "/data/disk.ex2"})
        assert result["filepath"] == "/data/disk.ex2"
        pvs.OpenDataFile.assert_called_once_with("/data/disk.ex2")
        pvs.Show.assert_called()

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

    def test_display_hide(self, handler):
        h, pvs = handler
        result = h.handle("display.hide", {"name": "disk.ex2"})
        assert result["hidden"] == "disk.ex2"
        pvs.Hide.assert_called()

    def test_display_color_by(self, handler):
        h, pvs = handler
        result = h.handle("display.color_by", {"name": "disk.ex2", "array": "Pressure"})
        assert result["array"] == "Pressure"
        pvs.ColorBy.assert_called_once()

    def test_display_set_representation(self, handler):
        h, pvs = handler
        display_mock = pvs.GetDisplayProperties.return_value
        result = h.handle(
            "display.set_representation",
            {"name": "disk.ex2", "representation": "Wireframe"},
        )
        assert result["representation"] == "Wireframe"
        assert display_mock.Representation == "Wireframe"


class TestViewHandlers:
    def test_view_reset_camera(self, handler):
        h, pvs = handler
        result = h.handle("view.reset_camera", {})
        assert result["reset"] is True
        pvs.ResetCamera.assert_called_once()


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

    def test_export_screenshot_defaults(self, handler):
        h, pvs = handler
        result = h.handle("export.screenshot", {"filepath": "/tmp/shot.png"})
        assert result["resolution"] == [1920, 1080]

    def test_export_data(self, handler):
        h, pvs = handler
        result = h.handle("export.data", {"name": "disk.ex2", "filepath": "/tmp/out.vtu"})
        assert result["filepath"] == "/tmp/out.vtu"
        pvs.SaveData.assert_called_once()


class TestFilterHandlers:
    def test_filter_slice(self, handler):
        h, pvs = handler
        result = h.handle(
            "filter.slice",
            {"input": "disk.ex2", "origin": [1, 2, 3], "normal": [0, 1, 0]},
        )
        assert result["filter"] == "Slice"
        assert result["origin"] == [1, 2, 3]
        pvs.Slice.assert_called_once()

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
