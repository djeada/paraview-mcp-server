"""Library script: open a dataset file in ParaView.

Set __result__ to a summary dict that the bridge returns as the tool result.

Expected args:
    filepath (str): Absolute path to the data file.
"""
from paraview.simple import GetActiveViewOrCreate, OpenDataFile, ResetCamera, Show

filepath = args["filepath"]
src = OpenDataFile(filepath)
if src is None:
    raise RuntimeError(f"ParaView could not open: {filepath!r}")
view = GetActiveViewOrCreate("RenderView")
Show(src, view)
ResetCamera(view)

__result__ = {
    "name": src.GetXMLLabel() if hasattr(src, "GetXMLLabel") else type(src).__name__,
    "filepath": filepath,
    "proxy_class": type(src).__name__,
}
