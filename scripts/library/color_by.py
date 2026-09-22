"""Library script: color a source by a data array.

RENDER-VIEW SCRIPT. Coloring is a display operation, so this needs the in-GUI
bridge (scripts/start_paraview_gui_bridge.py) or
PARAVIEW_MCP_ALLOW_DETACHED_RENDER_WINDOW=1. From the default standalone
pvpython bridge, use the paraview_display_color_by tool instead.

Expected args:
    name (str): Source name.
    array (str): Array name.
    association (str): 'POINTS' or 'CELLS' (default 'POINTS').
"""

name = args["name"]
array = args["array"]
association = args.get("association", "POINTS")

src = None
for (src_name, _id), proxy in pvs.GetSources().items():
    if src_name == name:
        src = proxy
        break
if src is None:
    raise ValueError(f"Source {name!r} not found")

view = pvs.GetActiveViewOrCreate("RenderView")
display = pvs.GetDisplayProperties(src, view)
pvs.ColorBy(display, (association, array))
pvs.UpdateScalarBars(view)

__result__ = {
    "name": name,
    "array": array,
    "association": association,
}
