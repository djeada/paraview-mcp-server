"""Library script: reset the camera of the active render view.

RENDER-VIEW SCRIPT. Needs the in-GUI bridge
(scripts/start_paraview_gui_bridge.py) or
PARAVIEW_MCP_ALLOW_DETACHED_RENDER_WINDOW=1. From the default standalone
pvpython bridge, use the paraview_view_reset_camera tool instead.
"""

view = pvs.GetActiveViewOrCreate("RenderView")
pvs.ResetCamera(view)

__result__ = {"reset": True}
