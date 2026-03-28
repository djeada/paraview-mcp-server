"""Library script: create a Slice filter on the active source.

Expected args:
    input (str): Name of the source to slice.
    origin (list[float]): [x, y, z] origin of the slice plane (default [0, 0, 0]).
    normal (list[float]): [nx, ny, nz] normal of the slice plane (default [1, 0, 0]).
"""
from paraview.simple import GetActiveViewOrCreate, GetSources, Show, Slice

input_name = args["input"]
origin = args.get("origin", [0.0, 0.0, 0.0])
normal = args.get("normal", [1.0, 0.0, 0.0])

# Find source by name
src = None
for (name, _id), proxy in GetSources().items():
    if name == input_name:
        src = proxy
        break
if src is None:
    raise ValueError(f"Source {input_name!r} not found")

filt = Slice(Input=src)
filt.SliceType.Origin = origin
filt.SliceType.Normal = normal

view = GetActiveViewOrCreate("RenderView")
Show(filt, view)

__result__ = {
    "input": input_name,
    "filter": "Slice",
    "origin": origin,
    "normal": normal,
}
