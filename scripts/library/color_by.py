"""Library script: color a source by a data array.

Expected args:
    name (str): Source name.
    array (str): Array name.
    association (str): 'POINTS' or 'CELLS' (default 'POINTS').
"""

from paraview.simple import (
    ColorBy,
    GetActiveViewOrCreate,
    GetDisplayProperties,
    GetSources,
    UpdateScalarBars,
)

name = args["name"]
array = args["array"]
association = args.get("association", "POINTS")

src = None
for (src_name, _id), proxy in GetSources().items():
    if src_name == name:
        src = proxy
        break
if src is None:
    raise ValueError(f"Source {name!r} not found")

view = GetActiveViewOrCreate("RenderView")
display = GetDisplayProperties(src, view)
ColorBy(display, (association, array))
UpdateScalarBars(view)

__result__ = {
    "name": name,
    "array": array,
    "association": association,
}
