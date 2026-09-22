"""Library script: open a dataset file in ParaView.

Works with both bridge modes: ``mcp.show()`` displays the source when a render
view already exists and quietly skips it otherwise, so this never opens a
detached VTK window from a standalone pvpython bridge.

Set __result__ to a summary dict that the bridge returns as the tool result.

Expected args:
    filepath (str): Absolute path to the data file.
"""

filepath = args["filepath"]
src = pvs.OpenDataFile(filepath)
if src is None:
    raise RuntimeError(f"ParaView could not open: {filepath!r}")

shown = mcp.show(src)
if shown:
    mcp.reset_camera()

__result__ = {
    "name": src.GetXMLLabel() if hasattr(src, "GetXMLLabel") else type(src).__name__,
    "filepath": filepath,
    "proxy_class": type(src).__name__,
    "shown": shown,
}
