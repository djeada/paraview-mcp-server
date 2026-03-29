"""Pydantic models for bridge command parameter validation.

Each model corresponds to a command accepted by the ParaView bridge.
The CommandHandler calls ``model.model_validate(params)`` on incoming dicts
so that invalid or missing fields are caught early with clear error messages.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ── Scene / session ────────────────────────────────────────────────


class SourceNameParams(BaseModel):
    name: str = Field(..., description="Pipeline source name")


class SourceOpenFileParams(BaseModel):
    filepath: str = Field(..., description="Path to dataset (VTK, VTU, CSV, ExodusII, …)")


class SourceRenameParams(BaseModel):
    name: str
    new_name: str


# ── Display / coloring ────────────────────────────────────────────


class DisplayColorByParams(BaseModel):
    name: str
    array: str = Field(..., description="Data array name to color by")
    component: int = Field(-1, description="-1 for magnitude, 0+ for component index")
    association: str = Field("POINTS", description="POINTS or CELLS")


class DisplaySetRepresentationParams(BaseModel):
    name: str
    representation: str = Field(..., description="Surface, Wireframe, Points, Volume, …")


class DisplaySetOpacityParams(BaseModel):
    name: str
    opacity: float = Field(..., ge=0.0, le=1.0, description="Transparency: 0.0 = invisible, 1.0 = opaque")


# ── Camera / view ─────────────────────────────────────────────────


class ViewSetCameraParams(BaseModel):
    position: list[float] | None = Field(None, min_length=3, max_length=3)
    focal_point: list[float] | None = Field(None, min_length=3, max_length=3)
    view_up: list[float] | None = Field(None, min_length=3, max_length=3)
    parallel_scale: float | None = None


class ViewSetBackgroundParams(BaseModel):
    color: list[float] = Field(..., description="RGB [r, g, b] in 0-1 range", min_length=3, max_length=3)
    color2: list[float] | None = Field(None, description="Gradient bottom color", min_length=3, max_length=3)


# ── Export ─────────────────────────────────────────────────────────


class ExportScreenshotParams(BaseModel):
    filepath: str
    width: int = Field(1920, gt=0)
    height: int = Field(1080, gt=0)
    transparent: bool = Field(False)


class ExportDataParams(BaseModel):
    name: str
    filepath: str


class ExportAnimationParams(BaseModel):
    filepath: str
    width: int = Field(1920, gt=0)
    height: int = Field(1080, gt=0)
    frame_rate: int = Field(15, gt=0)
    frame_start: int | None = None
    frame_end: int | None = None


# ── Filters — basic ───────────────────────────────────────────────


class FilterSliceParams(BaseModel):
    input: str = Field(..., description="Source name to slice")
    origin: list[float] | None = Field(None, min_length=3, max_length=3)
    normal: list[float] | None = Field(None, min_length=3, max_length=3)


class FilterClipParams(BaseModel):
    input: str
    origin: list[float] | None = Field(None, min_length=3, max_length=3)
    normal: list[float] | None = Field(None, min_length=3, max_length=3)


class FilterContourParams(BaseModel):
    input: str
    array: str = Field(..., description="Scalar array name")
    values: list[float] = Field(..., description="Isosurface values", min_length=1)


class FilterThresholdParams(BaseModel):
    input: str
    array: str
    lower: float
    upper: float


# ── Filters — advanced ────────────────────────────────────────────


class FilterCalculatorParams(BaseModel):
    input: str
    expression: str
    result_name: str = Field("Result")
    attribute_type: str = Field("Point Data", description="Point Data or Cell Data")


class FilterStreamTracerParams(BaseModel):
    input: str
    seed_type: str = Field("Line", description="Line or Point Cloud")
    integration_direction: str = Field("BOTH", description="FORWARD, BACKWARD, or BOTH")
    num_points: int = Field(100, gt=0)
    max_length: float | None = None


class FilterGlyphParams(BaseModel):
    input: str
    glyph_type: str = Field("Arrow", description="Arrow, Sphere, Cone, …")
    scale_factor: float = Field(1.0, gt=0)
    scale_array: str | None = None


# ── Python execution ───────────────────────────────────────────────


class PythonExecuteParams(BaseModel):
    code: str | None = Field(None, description="Inline Python code")
    script_path: str | None = Field(None, description="Path to a .py script file")
    args: dict | None = Field(None, description="Keyword arguments passed to the script namespace")
    timeout_seconds: float | None = Field(None, gt=0)


class JobIdParams(BaseModel):
    job_id: str
