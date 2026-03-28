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
        self._handlers["scene.get_info"] = self._scene_get_info
        self._handlers["scene.list_sources"] = self._scene_list_sources
        self._handlers["scene.list_views"] = self._scene_list_views
        self._handlers["source.get_properties"] = self._source_get_properties
        self._handlers["source.open_file"] = self._source_open_file
        self._handlers["source.delete"] = self._source_delete
        self._handlers["source.rename"] = self._source_rename
        self._handlers["display.show"] = self._display_show
        self._handlers["display.hide"] = self._display_hide
        self._handlers["display.color_by"] = self._display_color_by
        self._handlers["display.set_representation"] = self._display_set_representation
        self._handlers["view.reset_camera"] = self._view_reset_camera
        self._handlers["export.screenshot"] = self._export_screenshot
        self._handlers["export.data"] = self._export_data
        self._handlers["filter.slice"] = self._filter_slice
        self._handlers["filter.clip"] = self._filter_clip
        self._handlers["filter.contour"] = self._filter_contour
        self._handlers["filter.threshold"] = self._filter_threshold
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

    # ------------------------------------------------------------------
    # View / camera handlers
    # ------------------------------------------------------------------

    def _view_reset_camera(self, params: dict) -> dict:
        pvs = self._import_pv()
        view = pvs.GetActiveViewOrCreate("RenderView")
        pvs.ResetCamera(view)
        return {"reset": True}

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

    # ------------------------------------------------------------------
    # Filter handlers
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
    # Python execution handler
    # ------------------------------------------------------------------

    def _python_execute(self, params: dict) -> dict:
        from bridge.execution import execute_code  # noqa: PLC0415
        code = params.get("code")
        if not code:
            raise ValueError("Missing required parameter 'code'")
        args = params.get("args", {})
        return execute_code(code, args)
