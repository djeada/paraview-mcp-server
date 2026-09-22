"""Dependency-free bridge command parameter validation.

The bridge runs inside ParaView's Python runtime, which commonly does not have
the MCP server's Python dependencies installed. These classes intentionally
provide the small ``model_validate(...).model_dump(...)`` surface used by the
command handler without importing third-party packages.
"""

from __future__ import annotations

from typing import Any, ClassVar


class BridgeValidationError(ValueError):
    """Raised when bridge command parameters are invalid."""


def _missing(name: str) -> BridgeValidationError:
    return BridgeValidationError(f"Missing required parameter: {name}")


def _require(params: dict[str, Any], name: str) -> Any:
    if name not in params or params[name] is None:
        raise _missing(name)
    return params[name]


def _as_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise BridgeValidationError(f"{name} must be a non-empty string")
    return value


def _as_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise BridgeValidationError(f"{name} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise BridgeValidationError(f"{name} must be an integer") from exc


def _as_float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise BridgeValidationError(f"{name} must be a number")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise BridgeValidationError(f"{name} must be a number") from exc


def _as_bool(value: Any) -> bool:
    return bool(value)


def _as_dict(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise BridgeValidationError(f"{name} must be an object")
    return value


def _as_vec3(value: Any, name: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise BridgeValidationError(f"{name} must be a three-item list")
    return [_as_float(item, name) for item in value]


def _as_float_list(value: Any, name: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or not value:
        raise BridgeValidationError(f"{name} must be a non-empty list")
    return [_as_float(item, name) for item in value]


class BridgeParams:
    defaults: ClassVar[dict[str, Any]] = {}
    required: ClassVar[tuple[str, ...]] = ()
    strings: ClassVar[tuple[str, ...]] = ()
    floats: ClassVar[tuple[str, ...]] = ()
    ints: ClassVar[tuple[str, ...]] = ()
    bools: ClassVar[tuple[str, ...]] = ()
    vec3s: ClassVar[tuple[str, ...]] = ()
    float_lists: ClassVar[tuple[str, ...]] = ()
    dicts: ClassVar[tuple[str, ...]] = ()
    positive_ints: ClassVar[tuple[str, ...]] = ()
    positive_floats: ClassVar[tuple[str, ...]] = ()
    nonnegative_ints: ClassVar[tuple[str, ...]] = ()

    def __init__(self, values: dict[str, Any]):
        self._values = values

    @classmethod
    def model_validate(cls, params: dict[str, Any]):
        if not isinstance(params, dict):
            raise BridgeValidationError("params must be an object")

        values = dict(cls.defaults)
        for name in cls.required:
            values[name] = _require(params, name)

        for name, value in params.items():
            if value is not None:
                values[name] = value

        for name in cls.strings:
            if name in values:
                values[name] = _as_str(values[name], name)
        for name in cls.floats:
            if name in values:
                values[name] = _as_float(values[name], name)
        for name in cls.ints:
            if name in values:
                values[name] = _as_int(values[name], name)
        for name in cls.bools:
            if name in values:
                values[name] = _as_bool(values[name])
        for name in cls.vec3s:
            if name in values:
                values[name] = _as_vec3(values[name], name)
        for name in cls.float_lists:
            if name in values:
                values[name] = _as_float_list(values[name], name)
        for name in cls.dicts:
            if name in values:
                values[name] = _as_dict(values[name], name)

        cls._validate_ranges(values)
        cls._validate(values)
        return cls(values)

    @classmethod
    def _validate_ranges(cls, values: dict[str, Any]) -> None:
        for name in cls.positive_ints:
            if name in values and values[name] <= 0:
                raise BridgeValidationError(f"{name} must be greater than 0")
        for name in cls.positive_floats:
            if name in values and values[name] <= 0:
                raise BridgeValidationError(f"{name} must be greater than 0")
        for name in cls.nonnegative_ints:
            if name in values and values[name] < 0:
                raise BridgeValidationError(f"{name} must be greater than or equal to 0")

    @classmethod
    def _validate(cls, values: dict[str, Any]) -> None:
        return None

    def model_dump(self, *, exclude_none: bool = False) -> dict[str, Any]:
        if not exclude_none:
            return dict(self._values)
        return {key: value for key, value in self._values.items() if value is not None}


class SourceNameParams(BridgeParams):
    required = ("name",)
    strings = ("name",)


class SourceOpenFileParams(BridgeParams):
    required = ("filepath",)
    strings = ("filepath",)


class SourceRenameParams(BridgeParams):
    required = ("name", "new_name")
    strings = ("name", "new_name")


class DisplayColorByParams(BridgeParams):
    defaults = {"component": -1, "association": "POINTS"}
    required = ("name", "array")
    strings = ("name", "array", "association")
    ints = ("component",)


class DisplaySetRepresentationParams(BridgeParams):
    required = ("name", "representation")
    strings = ("name", "representation")


class DisplaySetOpacityParams(BridgeParams):
    required = ("name", "opacity")
    strings = ("name",)
    floats = ("opacity",)

    @classmethod
    def _validate(cls, values: dict[str, Any]) -> None:
        if values["opacity"] < 0.0 or values["opacity"] > 1.0:
            raise BridgeValidationError("opacity must be between 0.0 and 1.0")


class ViewSetCameraParams(BridgeParams):
    vec3s = ("position", "focal_point", "view_up")
    floats = ("parallel_scale",)


class ViewSetBackgroundParams(BridgeParams):
    required = ("color",)
    vec3s = ("color", "color2")


class ExportScreenshotParams(BridgeParams):
    defaults = {"width": 1920, "height": 1080, "transparent": False}
    required = ("filepath",)
    strings = ("filepath",)
    ints = ("width", "height")
    bools = ("transparent",)
    positive_ints = ("width", "height")


class ExportDataParams(BridgeParams):
    required = ("name", "filepath")
    strings = ("name", "filepath")


class ExportAnimationParams(BridgeParams):
    defaults = {"width": 1920, "height": 1080, "frame_rate": 15}
    required = ("filepath",)
    strings = ("filepath",)
    ints = ("width", "height", "frame_rate", "frame_start", "frame_end")
    positive_ints = ("width", "height", "frame_rate")
    nonnegative_ints = ("frame_start", "frame_end")

    @classmethod
    def _validate(cls, values: dict[str, Any]) -> None:
        if ("frame_start" in values) != ("frame_end" in values):
            raise BridgeValidationError("frame_start and frame_end must be provided together")
        if "frame_start" in values and values["frame_start"] > values["frame_end"]:
            raise BridgeValidationError("frame_start must be less than or equal to frame_end")


class FilterSliceParams(BridgeParams):
    required = ("input",)
    strings = ("input",)
    vec3s = ("origin", "normal")


class FilterClipParams(FilterSliceParams):
    pass


class FilterContourParams(BridgeParams):
    required = ("input", "array", "values")
    strings = ("input", "array")
    float_lists = ("values",)


class FilterThresholdParams(BridgeParams):
    required = ("input", "array", "lower", "upper")
    strings = ("input", "array")
    floats = ("lower", "upper")


class FilterCalculatorParams(BridgeParams):
    defaults = {"result_name": "Result", "attribute_type": "Point Data"}
    required = ("input", "expression")
    strings = ("input", "expression", "result_name", "attribute_type")


class FilterStreamTracerParams(BridgeParams):
    defaults = {"seed_type": "Line", "integration_direction": "BOTH", "num_points": 100}
    required = ("input",)
    strings = ("input", "seed_type", "integration_direction")
    ints = ("num_points",)
    floats = ("max_length",)
    positive_ints = ("num_points",)


class FilterGlyphParams(BridgeParams):
    defaults = {"glyph_type": "Arrow", "scale_factor": 1.0}
    required = ("input",)
    strings = ("input", "glyph_type", "scale_array")
    floats = ("scale_factor",)
    positive_floats = ("scale_factor",)


class PythonExecuteParams(BridgeParams):
    dicts = ("args",)
    strings = ("code", "script_path")
    floats = ("timeout_seconds",)
    positive_floats = ("timeout_seconds",)


class JobIdParams(BridgeParams):
    required = ("job_id",)
    strings = ("job_id",)
