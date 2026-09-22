"""Library script: create a Contour (isosurface) filter on a source.

Works with both bridge modes — see open_dataset.py.

Expected args:
    input (str): Name of the source.
    array (str): Scalar array name to contour by.
    values (list[float]): One or more isovalues.
"""

input_name = args["input"]
array = args["array"]
values = list(args["values"])

src = None
for (name, _id), proxy in pvs.GetSources().items():
    if name == input_name:
        src = proxy
        break
if src is None:
    raise ValueError(f"Source {input_name!r} not found")

filt = pvs.Contour(Input=src)
filt.ContourBy = ["POINTS", array]
filt.Isosurfaces = values

__result__ = {
    "input": input_name,
    "filter": "Contour",
    "array": array,
    "values": values,
    "shown": mcp.show(filt),
}
