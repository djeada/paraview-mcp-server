"""Library script: create a Contour (isosurface) filter on a source.

Expected args:
    input (str): Name of the source.
    array (str): Scalar array name to contour by.
    values (list[float]): One or more isovalues.
"""
from paraview.simple import Contour, GetActiveViewOrCreate, GetSources, Show

input_name = args["input"]
array = args["array"]
values = list(args["values"])

src = None
for (name, _id), proxy in GetSources().items():
    if name == input_name:
        src = proxy
        break
if src is None:
    raise ValueError(f"Source {input_name!r} not found")

filt = Contour(Input=src)
filt.ContourBy = ["POINTS", array]
filt.Isosurfaces = values

view = GetActiveViewOrCreate("RenderView")
Show(filt, view)

__result__ = {
    "input": input_name,
    "filter": "Contour",
    "array": array,
    "values": values,
}
