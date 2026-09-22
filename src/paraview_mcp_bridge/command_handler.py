"""Command registry for the ParaView bridge.

Each handler method receives a *params* dict and returns a JSON-serializable dict.
The handlers assume they run inside a pvpython session where ``paraview.simple``
is available.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bridge.models import (
    DisplayColorByParams,
    DisplaySetOpacityParams,
    DisplaySetRepresentationParams,
    ExportAnimationParams,
    ExportDataParams,
    ExportScreenshotParams,
    FilterCalculatorParams,
    FilterClipParams,
    FilterContourParams,
    FilterGlyphParams,
    FilterSliceParams,
    FilterStreamTracerParams,
    FilterThresholdParams,
    JobIdParams,
    PythonExecuteParams,
    SourceNameParams,
    SourceOpenFileParams,
    SourceRenameParams,
    ViewSetBackgroundParams,
    ViewSetCameraParams,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from bridge.models import BridgeParams

logger = logging.getLogger(__name__)

_DETACHED_WINDOW_OPT_IN_ENV = "PARAVIEW_MCP_ALLOW_DETACHED_RENDER_WINDOW"
_LEGACY_VIEW_CREATE_OPT_IN_ENV = "PARAVIEW_MCP_ALLOW_VIEW_CREATE"
_GUI_BRIDGE_ENV = "PARAVIEW_MCP_GUI_BRIDGE"
_PYTHON_RENDER_TOKENS = (
    "GetActiveViewOrCreate",
    "CreateRenderView",
    "GetRenderViews",
    "GetViews",
    "GetDisplayProperties",
    "Show",
    "Hide",
    "Render",
    "StillRender",
    "ResetCamera",
    "SaveScreenshot",
    "SaveAnimation",
    "ColorBy",
    "UpdateScalarBars",
)

_VALIDATORS: dict[str, type[BridgeParams]] = {
    "source.get_properties": SourceNameParams,
    "source.open_file": SourceOpenFileParams,
    "source.delete": SourceNameParams,
    "source.rename": SourceRenameParams,
    "display.show": SourceNameParams,
    "display.hide": SourceNameParams,
    "display.color_by": DisplayColorByParams,
    "display.set_representation": DisplaySetRepresentationParams,
    "display.set_opacity": DisplaySetOpacityParams,
    "display.rescale_transfer_function": SourceNameParams,
    "view.set_camera": ViewSetCameraParams,
    "view.set_background": ViewSetBackgroundParams,
    "export.screenshot": ExportScreenshotParams,
    "export.data": ExportDataParams,
    "export.animation": ExportAnimationParams,
    "filter.slice": FilterSliceParams,
    "filter.clip": FilterClipParams,
    "filter.contour": FilterContourParams,
    "filter.threshold": FilterThresholdParams,
    "filter.calculator": FilterCalculatorParams,
    "filter.stream_tracer": FilterStreamTracerParams,
    "filter.glyph": FilterGlyphParams,
    "python.execute": PythonExecuteParams,
    "job.status": JobIdParams,
    "job.cancel": JobIdParams,
}


class CommandHandler:
    """Registry that maps bridge command names to handler functions."""

    def __init__(self):
        self._handlers: dict[str, Callable[[dict], Any]] = {}
        self._register()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def handle(self, command: str, params: dict) -> Any:
        handler = self._handlers.get(command)
        if not handler:
            raise ValueError(f"Unknown command: {command!r}")
        validator = _VALIDATORS.get(command)
        if validator is not None:
            params = validator.model_validate(params).model_dump(exclude_none=True)
        return handler(params)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def _register(self):
        # Scene / session
        self._handlers["scene.get_info"] = self._scene_get_info
        self._handlers["scene.list_sources"] = self._scene_list_sources
        self._handlers["scene.list_views"] = self._scene_list_views
        self._handlers["source.get_properties"] = self._source_get_properties

        # Data loading
        self._handlers["source.open_file"] = self._source_open_file
        self._handlers["source.delete"] = self._source_delete
        self._handlers["source.rename"] = self._source_rename

        # Display
        self._handlers["display.show"] = self._display_show
        self._handlers["display.hide"] = self._display_hide
        self._handlers["display.color_by"] = self._display_color_by
        self._handlers["display.set_representation"] = self._display_set_representation
        self._handlers["display.set_opacity"] = self._display_set_opacity
        self._handlers["display.rescale_transfer_function"] = self._display_rescale_transfer_function

        # View / camera
        self._handlers["view.reset_camera"] = self._view_reset_camera
        self._handlers["view.set_camera"] = self._view_set_camera
        self._handlers["view.set_background"] = self._view_set_background

        # Export
        self._handlers["export.screenshot"] = self._export_screenshot
        self._handlers["export.data"] = self._export_data
        self._handlers["export.animation"] = self._export_animation

        # Filters — basic
        self._handlers["filter.slice"] = self._filter_slice
        self._handlers["filter.clip"] = self._filter_clip
        self._handlers["filter.contour"] = self._filter_contour
        self._handlers["filter.threshold"] = self._filter_threshold

        # Filters — advanced
        self._handlers["filter.calculator"] = self._filter_calculator
        self._handlers["filter.stream_tracer"] = self._filter_stream_tracer
        self._handlers["filter.glyph"] = self._filter_glyph

        # Python execution
        self._handlers["python.execute"] = self._python_execute

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _import_pv():
        """Import paraview.simple — deferred so the module can be imported without ParaView."""
        import paraview.simple as pvs  # noqa: PLC0415

        return pvs

    def _find_source(self, name: str):
        pvs = self._import_pv()
        for (src_name, _id), proxy in pvs.GetSources().items():
            if src_name == name:
                return proxy
        raise ValueError(f"Source {name!r} not found in the pipeline")

    def _get_source_name(self, proxy: Any) -> str:
        pvs = self._import_pv()
        for (src_name, _id), candidate in pvs.GetSources().items():
            if candidate == proxy:
                return str(src_name)
        raise ValueError("Source proxy is not registered in the pipeline")

    @staticmethod
    def _proxy_has_property(proxy: Any, name: str) -> bool:
        list_properties = getattr(proxy, "ListProperties", None)
        if not callable(list_properties):
            return hasattr(proxy, name)
        try:
            return name in list_properties()
        except Exception:
            return hasattr(proxy, name)

    @staticmethod
    def _is_render_view(view: Any) -> bool:
        if view is None:
            return False
        get_xml_name = getattr(view, "GetXMLName", None)
        if callable(get_xml_name):
            try:
                return bool(get_xml_name() == "RenderView")
            except Exception:
                pass
        return type(view).__name__ == "RenderView"

    @staticmethod
    def _render_control_allowed() -> bool:
        return (
            os.environ.get(_GUI_BRIDGE_ENV) == "1"
            or os.environ.get(_DETACHED_WINDOW_OPT_IN_ENV) == "1"
            or os.environ.get(_LEGACY_VIEW_CREATE_OPT_IN_ENV) == "1"
        )

    @staticmethod
    def _render_control_error() -> RuntimeError:
        return RuntimeError(
            "Render-view control is disabled from the separate pvpython bridge because it can open "
            "a detached ParaView/VTK render window. Start the in-GUI bridge for GUI rendering, or set "
            f"{_DETACHED_WINDOW_OPT_IN_ENV}=1 to explicitly allow detached render windows."
        )

    def _find_render_view(self, pvs: Any) -> Any | None:
        """Return an existing render view without creating a detached VTK window."""
        get_active_view = getattr(pvs, "GetActiveView", None)
        if callable(get_active_view):
            view = get_active_view()
            if self._is_render_view(view):
                return view

        get_render_views = getattr(pvs, "GetRenderViews", None)
        if callable(get_render_views):
            for view in get_render_views():
                if self._is_render_view(view):
                    return view

        get_views = getattr(pvs, "GetViews", None)
        if callable(get_views):
            for view in get_views():
                if self._is_render_view(view):
                    return view
        return None

    def _get_render_view(self, pvs: Any, *, required: bool = True) -> Any | None:
        if not self._render_control_allowed():
            if required:
                raise self._render_control_error()
            return None

        view = self._find_render_view(pvs)
        if view is not None:
            return view

        if self._render_control_allowed():
            return pvs.GetActiveViewOrCreate("RenderView")

        if required:
            raise RuntimeError("No existing RenderView is available to the ParaView MCP bridge.")
        return None

    def _require_render_view(self, pvs: Any) -> Any:
        view = self._get_render_view(pvs)
        if view is None:
            raise RuntimeError("No RenderView is available")
        return view

    def _show_if_render_view(self, pvs: Any, proxy: Any) -> bool:
        view = self._get_render_view(pvs, required=False)
        if view is None:
            return False
        pvs.Show(proxy, view)
        return True

    # ------------------------------------------------------------------
    # Scene / session handlers
    # ------------------------------------------------------------------

    def _scene_get_info(self, params: dict) -> dict:
        pvs = self._import_pv()
        view = self._get_render_view(pvs, required=False)
        sources = pvs.GetSources()
        return {
            "source_count": len(sources),
            "active_view_type": type(view).__name__ if view is not None else None,
            "render_view_available": view is not None,
        }

    def _scene_list_sources(self, params: dict) -> dict:
        pvs = self._import_pv()
        sources = []
        for (name, _id), proxy in pvs.GetSources().items():
            sources.append(
                {
                    "name": name,
                    "id": str(_id),
                    "proxy_class": type(proxy).__name__,
                }
            )
        return {"sources": sources}

    def _scene_list_views(self, params: dict) -> dict:
        pvs = self._import_pv()
        views = []
        for view in pvs.GetViews():
            views.append(
                {
                    "type": type(view).__name__,
                    "id": str(view.GetGlobalID()),
                }
            )
        return {"views": views}

    def _source_get_properties(self, params: dict) -> dict:
        src = self._find_source(params["name"])
        props = {}
        for prop_name in src.ListProperties():
            try:
                value = getattr(src, prop_name)
                # Only keep simple JSON-serialisable values.
                if isinstance(value, (int, float, str, bool, list, type(None))):
                    props[prop_name] = value
            except Exception:
                pass
        return {"name": params["name"], "properties": props}

    # ------------------------------------------------------------------
    # Data loading handlers
    # ------------------------------------------------------------------

    def _source_open_file(self, params: dict) -> dict:
        pvs = self._import_pv()
        filepath = params["filepath"]
        src = pvs.OpenDataFile(filepath)
        if src is None:
            raise RuntimeError(f"ParaView could not open file: {filepath!r}")
        view = self._get_render_view(pvs, required=False)
        shown = False
        if view is not None:
            pvs.Show(src, view)
            pvs.ResetCamera(view)
            shown = True
        name = self._get_source_name(src)
        label = src.GetXMLLabel() if hasattr(src, "GetXMLLabel") else type(src).__name__
        return {
            "name": name,
            "label": label,
            "filepath": filepath,
            "proxy_class": type(src).__name__,
            "shown": shown,
        }

    def _source_delete(self, params: dict) -> dict:
        pvs = self._import_pv()
        src = self._find_source(params["name"])
        pvs.Delete(src)
        return {"deleted": params["name"]}

    def _source_rename(self, params: dict) -> dict:
        pvs = self._import_pv()
        src = self._find_source(params["name"])
        pvs.RenameSource(params["new_name"], src)
        return {"old_name": params["name"], "new_name": params["new_name"]}

    # ------------------------------------------------------------------
    # Display handlers
    # ------------------------------------------------------------------

    def _display_show(self, params: dict) -> dict:
        pvs = self._import_pv()
        src = self._find_source(params["name"])
        view = self._require_render_view(pvs)
        pvs.Show(src, view)
        return {"shown": params["name"]}

    def _display_hide(self, params: dict) -> dict:
        pvs = self._import_pv()
        src = self._find_source(params["name"])
        view = self._require_render_view(pvs)
        pvs.Hide(src, view)
        return {"hidden": params["name"]}

    def _display_color_by(self, params: dict) -> dict:
        pvs = self._import_pv()
        src = self._find_source(params["name"])
        view = self._require_render_view(pvs)
        display = pvs.GetDisplayProperties(src, view)
        array = params["array"]
        component = int(params.get("component", -1))
        association = params.get("association", "POINTS")
        pvs.ColorBy(display, (association, array))
        lut = pvs.GetColorTransferFunction(array)
        if component < 0:
            lut.VectorMode = "Magnitude"
        else:
            lut.VectorMode = "Component"
            lut.VectorComponent = component
        pvs.UpdateScalarBars(view)
        return {
            "name": params["name"],
            "array": array,
            "association": association,
            "component": component,
        }

    def _display_set_representation(self, params: dict) -> dict:
        pvs = self._import_pv()
        src = self._find_source(params["name"])
        view = self._require_render_view(pvs)
        display = pvs.GetDisplayProperties(src, view)
        display.Representation = params["representation"]
        return {"name": params["name"], "representation": params["representation"]}

    def _display_set_opacity(self, params: dict) -> dict:
        pvs = self._import_pv()
        src = self._find_source(params["name"])
        view = self._require_render_view(pvs)
        display = pvs.GetDisplayProperties(src, view)
        opacity = float(params["opacity"])
        display.Opacity = opacity
        return {"name": params["name"], "opacity": opacity}

    def _display_rescale_transfer_function(self, params: dict) -> dict:
        pvs = self._import_pv()
        src = self._find_source(params["name"])
        view = self._require_render_view(pvs)
        display = pvs.GetDisplayProperties(src, view)
        display.RescaleTransferFunctionToDataRange(False)
        pvs.UpdateScalarBars(view)
        return {"name": params["name"], "rescaled": True}

    # ------------------------------------------------------------------
    # View / camera handlers
    # ------------------------------------------------------------------

    def _view_reset_camera(self, params: dict) -> dict:
        pvs = self._import_pv()
        view = self._require_render_view(pvs)
        pvs.ResetCamera(view)
        return {"reset": True}

    def _view_set_camera(self, params: dict) -> dict:
        pvs = self._import_pv()
        view = self._require_render_view(pvs)
        camera = view.GetActiveCamera()
        if "position" in params:
            camera.SetPosition(*params["position"])
        if "focal_point" in params:
            camera.SetFocalPoint(*params["focal_point"])
        if "view_up" in params:
            camera.SetViewUp(*params["view_up"])
        if "parallel_scale" in params:
            camera.SetParallelScale(params["parallel_scale"])
        if os.environ.get("PARAVIEW_MCP_GUI_BRIDGE") != "1":
            view.StillRender()
        pos = list(camera.GetPosition())
        fp = list(camera.GetFocalPoint())
        up = list(camera.GetViewUp())
        parallel_scale = float(camera.GetParallelScale())
        return {
            "position": pos,
            "focal_point": fp,
            "view_up": up,
            "parallel_scale": parallel_scale,
        }

    def _view_set_background(self, params: dict) -> dict:
        pvs = self._import_pv()
        view = self._require_render_view(pvs)
        color = params["color"]
        view.Background = color
        result = {"color": color, "gradient": "color2" in params}
        if "color2" in params:
            view.Background2 = params["color2"]
            if self._proxy_has_property(view, "BackgroundColorMode"):
                view.BackgroundColorMode = "Gradient"
            else:
                view.UseGradientBackground = True
            result["color2"] = params["color2"]
        else:
            if self._proxy_has_property(view, "BackgroundColorMode"):
                view.BackgroundColorMode = "Single Color"
            else:
                view.UseGradientBackground = False
        return result

    # ------------------------------------------------------------------
    # Export handlers
    # ------------------------------------------------------------------

    def _export_screenshot(self, params: dict) -> dict:
        pvs = self._import_pv()
        filepath = params["filepath"]
        width = int(params.get("width", 1920))
        height = int(params.get("height", 1080))
        transparent = bool(params.get("transparent", False))
        view = self._require_render_view(pvs)
        pvs.SaveScreenshot(filepath, view, ImageResolution=[width, height], TransparentBackground=int(transparent))
        return {
            "filepath": filepath,
            "resolution": [width, height],
            "transparent": transparent,
        }

    def _export_data(self, params: dict) -> dict:
        pvs = self._import_pv()
        src = self._find_source(params["name"])
        filepath = params["filepath"]
        pvs.SaveData(filepath, proxy=src)
        return {"name": params["name"], "filepath": filepath}

    def _export_animation(self, params: dict) -> dict:
        pvs = self._import_pv()
        filepath = params["filepath"]
        width = int(params.get("width", 1920))
        height = int(params.get("height", 1080))
        frame_rate = int(params.get("frame_rate", 15))
        frame_start = params.get("frame_start")
        frame_end = params.get("frame_end")
        view = self._require_render_view(pvs)
        save_kwargs: dict[str, Any] = {
            "ImageResolution": [width, height],
            "FrameRate": frame_rate,
        }
        if frame_start is not None and frame_end is not None:
            save_kwargs["FrameWindow"] = [int(frame_start), int(frame_end)]
        pvs.SaveAnimation(filepath, view, **save_kwargs)
        result = {
            "filepath": filepath,
            "resolution": [width, height],
            "frame_rate": frame_rate,
        }
        if frame_start is not None and frame_end is not None:
            result["frame_start"] = int(frame_start)
            result["frame_end"] = int(frame_end)
        return result

    # ------------------------------------------------------------------
    # Filter handlers — basic
    # ------------------------------------------------------------------

    def _filter_slice(self, params: dict) -> dict:
        pvs = self._import_pv()
        src = self._find_source(params["input"])
        origin = params.get("origin", [0.0, 0.0, 0.0])
        normal = params.get("normal", [1.0, 0.0, 0.0])
        filt = pvs.Slice(Input=src)
        filt.SliceType.Origin = origin
        filt.SliceType.Normal = normal
        shown = self._show_if_render_view(pvs, filt)
        return {"input": params["input"], "filter": "Slice", "origin": origin, "normal": normal, "shown": shown}

    def _filter_clip(self, params: dict) -> dict:
        pvs = self._import_pv()
        src = self._find_source(params["input"])
        origin = params.get("origin", [0.0, 0.0, 0.0])
        normal = params.get("normal", [1.0, 0.0, 0.0])
        filt = pvs.Clip(Input=src)
        filt.ClipType.Origin = origin
        filt.ClipType.Normal = normal
        shown = self._show_if_render_view(pvs, filt)
        return {"input": params["input"], "filter": "Clip", "origin": origin, "normal": normal, "shown": shown}

    def _filter_contour(self, params: dict) -> dict:
        pvs = self._import_pv()
        src = self._find_source(params["input"])
        array = params["array"]
        values = list(params["values"])
        filt = pvs.Contour(Input=src)
        filt.ContourBy = ["POINTS", array]
        filt.Isosurfaces = values
        shown = self._show_if_render_view(pvs, filt)
        return {"input": params["input"], "filter": "Contour", "array": array, "values": values, "shown": shown}

    def _filter_threshold(self, params: dict) -> dict:
        pvs = self._import_pv()
        src = self._find_source(params["input"])
        array = params["array"]
        lower = float(params["lower"])
        upper = float(params["upper"])
        filt = pvs.Threshold(Input=src)
        filt.Scalars = ["POINTS", array]
        if self._proxy_has_property(filt, "ThresholdRange"):
            filt.ThresholdRange = [lower, upper]
        else:
            filt.LowerThreshold = lower
            filt.UpperThreshold = upper
            if self._proxy_has_property(filt, "ThresholdMethod"):
                filt.ThresholdMethod = "Between"
        shown = self._show_if_render_view(pvs, filt)
        return {
            "input": params["input"],
            "filter": "Threshold",
            "array": array,
            "lower": lower,
            "upper": upper,
            "shown": shown,
        }

    # ------------------------------------------------------------------
    # Filter handlers — advanced
    # ------------------------------------------------------------------

    def _filter_calculator(self, params: dict) -> dict:
        pvs = self._import_pv()
        src = self._find_source(params["input"])
        expression = params["expression"]
        result_name = params.get("result_name", "Result")
        attribute_type = params.get("attribute_type", "Point Data")
        filt = pvs.Calculator(Input=src)
        filt.Function = expression
        filt.ResultArrayName = result_name
        filt.AttributeType = attribute_type
        shown = self._show_if_render_view(pvs, filt)
        return {
            "input": params["input"],
            "filter": "Calculator",
            "expression": expression,
            "result_name": result_name,
            "shown": shown,
        }

    def _filter_stream_tracer(self, params: dict) -> dict:
        pvs = self._import_pv()
        src = self._find_source(params["input"])
        seed_type = params.get("seed_type", "Point Cloud")
        integration_direction = params.get("integration_direction", "BOTH")
        num_points = int(params.get("num_points", 100))
        max_length = float(params.get("max_length", 1.0))
        filt = pvs.StreamTracer(Input=src, SeedType=seed_type)
        filt.IntegrationDirection = integration_direction
        filt.MaximumStreamlineLength = max_length
        if hasattr(filt, "SeedType") and hasattr(filt.SeedType, "NumberOfPoints"):
            filt.SeedType.NumberOfPoints = num_points
        shown = self._show_if_render_view(pvs, filt)
        return {
            "input": params["input"],
            "filter": "StreamTracer",
            "seed_type": seed_type,
            "integration_direction": integration_direction,
            "num_points": num_points,
            "max_length": max_length,
            "shown": shown,
        }

    def _filter_glyph(self, params: dict) -> dict:
        pvs = self._import_pv()
        src = self._find_source(params["input"])
        glyph_type = params.get("glyph_type", "Arrow")
        scale_array = params.get("scale_array")
        scale_factor = float(params.get("scale_factor", 1.0))
        filt = pvs.Glyph(Input=src, GlyphType=glyph_type)
        filt.ScaleFactor = scale_factor
        if scale_array:
            filt.ScaleArray = ["POINTS", scale_array]
        shown = self._show_if_render_view(pvs, filt)
        return {
            "input": params["input"],
            "filter": "Glyph",
            "glyph_type": glyph_type,
            "scale_factor": scale_factor,
            "shown": shown,
        }

    # ------------------------------------------------------------------
    # Python execution handler
    # ------------------------------------------------------------------

    def _python_execute(self, params: dict) -> dict:
        from bridge.execution import execute_code  # noqa: PLC0415

        code = params.get("code")
        script_path = params.get("script_path")
        if not code and not script_path:
            raise ValueError("Missing required parameter 'code' or 'script_path'")
        if not self._render_control_allowed():
            self._validate_python_exec_does_not_control_rendering(code=code, script_path=script_path)
        args = params.get("args", {})
        timeout = params.get("timeout_seconds")
        return execute_code(
            code=code,
            args=args,
            script_path=script_path,
            timeout_seconds=timeout,
        )

    def _validate_python_exec_does_not_control_rendering(self, *, code: str | None, script_path: str | None) -> None:
        source = code
        if source is None and script_path is not None:
            try:
                source = Path(script_path).read_text(encoding="utf-8")
            except OSError:
                return
        if not source:
            return
        blocked = [token for token in _PYTHON_RENDER_TOKENS if token in source]
        if blocked:
            raise RuntimeError(
                "python.execute in the separate pvpython bridge may not call render/view/display APIs "
                f"because they can open detached windows. Blocked token(s): {', '.join(blocked)}. "
                "Use fixed pipeline tools without display calls, start the in-GUI bridge, or set "
                f"{_DETACHED_WINDOW_OPT_IN_ENV}=1 to explicitly allow detached render windows."
            )
