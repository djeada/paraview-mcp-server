"""Command registry for the ParaView bridge.

Each handler method receives a *params* dict and returns a JSON-serializable dict.
The handlers assume they run inside a pvpython session where ``paraview.simple``
is available.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


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
        self._handlers["display.rescale_transfer_function"] = (
            self._display_rescale_transfer_function
        )

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

    # ------------------------------------------------------------------
    # Scene / session handlers
    # ------------------------------------------------------------------

    def _scene_get_info(self, params: dict) -> dict:
        pvs = self._import_pv()
        view = pvs.GetActiveViewOrCreate("RenderView")
        sources = pvs.GetSources()
        return {
            "source_count": len(sources),
            "active_view_type": type(view).__name__,
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
        view = pvs.GetActiveViewOrCreate("RenderView")
        pvs.Show(src, view)
        pvs.ResetCamera(view)
        label = src.GetXMLLabel() if hasattr(src, "GetXMLLabel") else type(src).__name__
        return {
            "name": label,
            "filepath": filepath,
            "proxy_class": type(src).__name__,
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
        view = pvs.GetActiveViewOrCreate("RenderView")
        pvs.Show(src, view)
        return {"shown": params["name"]}

    def _display_hide(self, params: dict) -> dict:
        pvs = self._import_pv()
        src = self._find_source(params["name"])
        view = pvs.GetActiveViewOrCreate("RenderView")
        pvs.Hide(src, view)
        return {"hidden": params["name"]}

    def _display_color_by(self, params: dict) -> dict:
        pvs = self._import_pv()
        src = self._find_source(params["name"])
        view = pvs.GetActiveViewOrCreate("RenderView")
        display = pvs.GetDisplayProperties(src, view)
        array = params["array"]
        association = params.get("association", "POINTS")
        pvs.ColorBy(display, (association, array))
        pvs.UpdateScalarBars(view)
        return {"name": params["name"], "array": array, "association": association}

    def _display_set_representation(self, params: dict) -> dict:
        pvs = self._import_pv()
        src = self._find_source(params["name"])
        view = pvs.GetActiveViewOrCreate("RenderView")
        display = pvs.GetDisplayProperties(src, view)
        display.Representation = params["representation"]
        return {"name": params["name"], "representation": params["representation"]}

    def _display_set_opacity(self, params: dict) -> dict:
        pvs = self._import_pv()
        src = self._find_source(params["name"])
        view = pvs.GetActiveViewOrCreate("RenderView")
        display = pvs.GetDisplayProperties(src, view)
        opacity = float(params["opacity"])
        display.Opacity = opacity
        return {"name": params["name"], "opacity": opacity}

    def _display_rescale_transfer_function(self, params: dict) -> dict:
        pvs = self._import_pv()
        src = self._find_source(params["name"])
        view = pvs.GetActiveViewOrCreate("RenderView")
        display = pvs.GetDisplayProperties(src, view)
        display.RescaleTransferFunctionToDataRange(False)
        pvs.UpdateScalarBars(view)
        return {"name": params["name"], "rescaled": True}

    # ------------------------------------------------------------------
    # View / camera handlers
    # ------------------------------------------------------------------

    def _view_reset_camera(self, params: dict) -> dict:
        pvs = self._import_pv()
        view = pvs.GetActiveViewOrCreate("RenderView")
        pvs.ResetCamera(view)
        return {"reset": True}

    def _view_set_camera(self, params: dict) -> dict:
        pvs = self._import_pv()
        view = pvs.GetActiveViewOrCreate("RenderView")
        camera = view.GetActiveCamera()
        if "position" in params:
            camera.SetPosition(*params["position"])
        if "focal_point" in params:
            camera.SetFocalPoint(*params["focal_point"])
        if "view_up" in params:
            camera.SetViewUp(*params["view_up"])
        if "parallel_scale" in params:
            camera.SetParallelScale(params["parallel_scale"])
        view.StillRender()
        pos = list(camera.GetPosition())
        fp = list(camera.GetFocalPoint())
        up = list(camera.GetViewUp())
        return {"position": pos, "focal_point": fp, "view_up": up}

    def _view_set_background(self, params: dict) -> dict:
        pvs = self._import_pv()
        view = pvs.GetActiveViewOrCreate("RenderView")
        color = params["color"]
        view.Background = color
        if "color2" in params:
            view.Background2 = params["color2"]
            view.UseGradientBackground = True
        else:
            view.UseGradientBackground = False
        return {"color": color, "gradient": "color2" in params}

    # ------------------------------------------------------------------
    # Export handlers
    # ------------------------------------------------------------------

    def _export_screenshot(self, params: dict) -> dict:
        pvs = self._import_pv()
        filepath = params["filepath"]
        width = int(params.get("width", 1920))
        height = int(params.get("height", 1080))
        view = pvs.GetActiveViewOrCreate("RenderView")
        pvs.SaveScreenshot(filepath, view, ImageResolution=[width, height])
        return {"filepath": filepath, "resolution": [width, height]}

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
        view = pvs.GetActiveViewOrCreate("RenderView")
        pvs.SaveAnimation(
            filepath,
            view,
            ImageResolution=[width, height],
            FrameRate=frame_rate,
        )
        return {
            "filepath": filepath,
            "resolution": [width, height],
            "frame_rate": frame_rate,
        }

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
        view = pvs.GetActiveViewOrCreate("RenderView")
        pvs.Show(filt, view)
        return {"input": params["input"], "filter": "Slice", "origin": origin, "normal": normal}

    def _filter_clip(self, params: dict) -> dict:
        pvs = self._import_pv()
        src = self._find_source(params["input"])
        origin = params.get("origin", [0.0, 0.0, 0.0])
        normal = params.get("normal", [1.0, 0.0, 0.0])
        filt = pvs.Clip(Input=src)
        filt.ClipType.Origin = origin
        filt.ClipType.Normal = normal
        view = pvs.GetActiveViewOrCreate("RenderView")
        pvs.Show(filt, view)
        return {"input": params["input"], "filter": "Clip", "origin": origin, "normal": normal}

    def _filter_contour(self, params: dict) -> dict:
        pvs = self._import_pv()
        src = self._find_source(params["input"])
        array = params["array"]
        values = list(params["values"])
        filt = pvs.Contour(Input=src)
        filt.ContourBy = ["POINTS", array]
        filt.Isosurfaces = values
        view = pvs.GetActiveViewOrCreate("RenderView")
        pvs.Show(filt, view)
        return {"input": params["input"], "filter": "Contour", "array": array, "values": values}

    def _filter_threshold(self, params: dict) -> dict:
        pvs = self._import_pv()
        src = self._find_source(params["input"])
        array = params["array"]
        lower = float(params["lower"])
        upper = float(params["upper"])
        filt = pvs.Threshold(Input=src)
        filt.Scalars = ["POINTS", array]
        filt.ThresholdRange = [lower, upper]
        view = pvs.GetActiveViewOrCreate("RenderView")
        pvs.Show(filt, view)
        return {
            "input": params["input"],
            "filter": "Threshold",
            "array": array,
            "lower": lower,
            "upper": upper,
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
        view = pvs.GetActiveViewOrCreate("RenderView")
        pvs.Show(filt, view)
        return {
            "input": params["input"],
            "filter": "Calculator",
            "expression": expression,
            "result_name": result_name,
        }

    def _filter_stream_tracer(self, params: dict) -> dict:
        pvs = self._import_pv()
        src = self._find_source(params["input"])
        seed_type = params.get("seed_type", "Point Cloud")
        num_points = int(params.get("num_points", 100))
        max_length = float(params.get("max_length", 1.0))
        filt = pvs.StreamTracer(Input=src, SeedType=seed_type)
        filt.MaximumStreamlineLength = max_length
        if hasattr(filt, "SeedType") and hasattr(filt.SeedType, "NumberOfPoints"):
            filt.SeedType.NumberOfPoints = num_points
        view = pvs.GetActiveViewOrCreate("RenderView")
        pvs.Show(filt, view)
        return {
            "input": params["input"],
            "filter": "StreamTracer",
            "seed_type": seed_type,
            "num_points": num_points,
            "max_length": max_length,
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
        view = pvs.GetActiveViewOrCreate("RenderView")
        pvs.Show(filt, view)
        return {
            "input": params["input"],
            "filter": "Glyph",
            "glyph_type": glyph_type,
            "scale_factor": scale_factor,
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
        args = params.get("args", {})
        timeout = params.get("timeout_seconds")
        return execute_code(
            code=code,
            args=args,
            script_path=script_path,
            timeout_seconds=timeout,
        )
