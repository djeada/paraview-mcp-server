"""Library script: save a screenshot of the active render view.

RENDER-VIEW SCRIPT. Needs the in-GUI bridge
(scripts/start_paraview_gui_bridge.py) or
PARAVIEW_MCP_ALLOW_DETACHED_RENDER_WINDOW=1. From the default standalone
pvpython bridge, use the paraview_export_screenshot tool instead.

Expected args:
    filepath (str): Output file path (PNG or JPEG).
    width (int): Image width in pixels (default 1920).
    height (int): Image height in pixels (default 1080).
"""

filepath = args["filepath"]
width = int(args.get("width", 1920))
height = int(args.get("height", 1080))

view = pvs.GetActiveViewOrCreate("RenderView")
pvs.SaveScreenshot(filepath, view, ImageResolution=[width, height])

__result__ = {
    "filepath": filepath,
    "resolution": [width, height],
}
