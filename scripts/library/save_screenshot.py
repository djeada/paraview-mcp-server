"""Library script: save a screenshot of the active render view.

Expected args:
    filepath (str): Output file path (PNG or JPEG).
    width (int): Image width in pixels (default 1920).
    height (int): Image height in pixels (default 1080).
"""

from paraview.simple import GetActiveViewOrCreate, SaveScreenshot

filepath = args["filepath"]
width = int(args.get("width", 1920))
height = int(args.get("height", 1080))

view = GetActiveViewOrCreate("RenderView")
SaveScreenshot(filepath, view, ImageResolution=[width, height])

__result__ = {
    "filepath": filepath,
    "resolution": [width, height],
}
