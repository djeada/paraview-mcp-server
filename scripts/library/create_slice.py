"""Library script: create a Slice filter on a named source.

Works with both bridge modes — see open_dataset.py.

Expected args:
    input (str): Name of the source to slice.
    origin (list[float]): [x, y, z] origin of the slice plane (default [0, 0, 0]).
    normal (list[float]): [nx, ny, nz] normal of the slice plane (default [1, 0, 0]).
"""

input_name = args["input"]
origin = args.get("origin", [0.0, 0.0, 0.0])
normal = args.get("normal", [1.0, 0.0, 0.0])

# Find source by name
src = None
for (name, _id), proxy in pvs.GetSources().items():
    if name == input_name:
        src = proxy
        break
if src is None:
    raise ValueError(f"Source {input_name!r} not found")

filt = pvs.Slice(Input=src)
filt.SliceType.Origin = origin
filt.SliceType.Normal = normal

__result__ = {
    "input": input_name,
    "filter": "Slice",
    "origin": origin,
    "normal": normal,
    "shown": mcp.show(filt),
}
