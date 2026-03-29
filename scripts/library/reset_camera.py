"""Library script: reset the camera of the active render view."""

from paraview.simple import GetActiveViewOrCreate, ResetCamera

view = GetActiveViewOrCreate("RenderView")
ResetCamera(view)

__result__ = {"reset": True}
