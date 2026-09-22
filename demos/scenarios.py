"""Demo scenarios exercised against a real ParaView session.

Each scenario pairs the natural-language *prompt* a user would give an MCP
client with the concrete tool calls an assistant should make to satisfy it, and
with checks on what came back. The runner drives the real MCP server over
stdio, so a passing scenario proves the whole chain works:

    runner (MCP client) → paraview-mcp-server → bridge → ParaView

Checks are plain callables over the parsed JSON a tool returned. Keep them
about observable behaviour — a source appearing in the pipeline, a file being
written — rather than about wording.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

Check = Callable[[Any], bool]


class Step:
    """One MCP tool call plus what must be true of its result.

    ``bind`` captures fields of the result into the scenario's context, and any
    ``"$name"`` string in a later step's ``args`` is substituted from it. This
    matters because ParaView chooses the registered names: opening ``demo.vti``
    produces a source called ``XMLImageDataReader1``, and a Slice becomes
    ``Slice1``. Hard-coding those would make the demos fragile and would not
    reflect how an assistant actually has to work.
    """

    def __init__(
        self,
        tool: str,
        args: dict[str, Any] | None = None,
        *,
        note: str = "",
        check: Check | None = None,
        screenshot: str | None = None,
        bind: dict[str, str] | None = None,
    ):
        self.tool = tool
        self.args = args or {}
        self.note = note
        self.check = check
        self.screenshot = screenshot
        self.bind = bind or {}


class Scenario:
    def __init__(self, ident: str, title: str, prompt: str, steps: list[Step], *, needs_render: bool = False):
        self.ident = ident
        self.title = title
        self.prompt = prompt
        self.steps = steps
        self.needs_render = needs_render


def _sources(result: Any) -> list[str]:
    return [source["name"] for source in result.get("sources", [])]


def _png_written(path: str, min_bytes: int = 1000) -> Check:
    def check(result: Any) -> bool:
        target = Path(result.get("filepath", path))
        return target.is_file() and target.stat().st_size >= min_bytes

    return check


def build_scenarios(dataset: str, outdir: Path) -> list[Scenario]:
    """Scenarios parameterised by the generated dataset and output directory."""
    shot = lambda name: str(outdir / name)  # noqa: E731

    return [
        Scenario(
            "01-inspect",
            "Inspect an empty session",
            "What's currently loaded in ParaView?",
            [
                Step(
                    "paraview_scene_get_info",
                    note="Asking the session to describe itself.",
                    check=lambda r: "source_count" in r and "render_view_available" in r,
                ),
                Step(
                    "paraview_scene_list_sources",
                    note="A fresh session has an empty pipeline.",
                    check=lambda r: _sources(r) == [],
                ),
                Step(
                    "paraview_scene_list_views",
                    note="The bridge reports the views it can see.",
                    check=lambda r: isinstance(r.get("views"), list),
                ),
            ],
        ),
        Scenario(
            "02-open-and-render",
            "Open a dataset and render it",
            f"Open {dataset} and save a picture of it to disk.",
            [
                Step(
                    "paraview_source_open_file",
                    {"filepath": dataset},
                    note="ParaView picks the registered name (here XMLImageDataReader1), and the tool reports it.",
                    check=lambda r: r.get("shown") is True and bool(r.get("name")),
                    bind={"data": "name"},
                ),
                Step(
                    "paraview_source_rename",
                    {"name": "$data", "new_name": "Volume"},
                    note="Rename it to something readable; later steps address it as 'Volume'.",
                    check=lambda r: r.get("new_name") == "Volume",
                ),
                Step(
                    "paraview_scene_list_sources",
                    note="The pipeline now holds exactly the renamed source.",
                    check=lambda r: _sources(r) == ["Volume"],
                ),
                Step(
                    "paraview_display_set_representation",
                    {"name": "Volume", "representation": "Surface"},
                    note=(
                        "ParaView shows image data as an Outline by default, which renders as an "
                        "empty wireframe box. Ask for Surface to actually see the data."
                    ),
                    check=lambda r: r.get("representation") == "Surface",
                ),
                Step(
                    "paraview_view_reset_camera",
                    note="Fit the data in the view before capturing.",
                    check=lambda r: r.get("reset") is True,
                ),
                Step(
                    "paraview_export_screenshot",
                    {"filepath": shot("02-open-and-render.png"), "width": 800, "height": 600},
                    note="Render the view to a PNG.",
                    check=_png_written(shot("02-open-and-render.png")),
                    screenshot="02-open-and-render.png",
                ),
            ],
            needs_render=True,
        ),
        Scenario(
            "03-color-by-array",
            "Colour the data by a scalar array",
            "Colour it by the RTData array and rescale the colour map to the data range.",
            [
                Step(
                    "paraview_display_color_by",
                    {"name": "Volume", "array": "RTData", "association": "POINTS"},
                    note="Map the RTData point array onto the surface.",
                    check=lambda r: r.get("array") == "RTData",
                ),
                Step(
                    "paraview_display_rescale_transfer_function",
                    {"name": "Volume"},
                    note="Fit the colour map to the actual value range.",
                    check=lambda r: r.get("rescaled") is True,
                ),
                Step(
                    "paraview_view_set_background",
                    {"color": [0.08, 0.09, 0.12]},
                    note="A dark background so the colour map reads clearly.",
                    check=lambda r: r.get("gradient") is False,
                ),
                Step(
                    "paraview_export_screenshot",
                    {"filepath": shot("03-color-by-array.png"), "width": 800, "height": 600},
                    check=_png_written(shot("03-color-by-array.png")),
                    screenshot="03-color-by-array.png",
                ),
            ],
            needs_render=True,
        ),
        Scenario(
            "04-contour",
            "Extract an isosurface",
            "Add a contour of RTData at values 80 and 150, and hide the original volume.",
            [
                Step(
                    "paraview_filter_contour",
                    {"input": "Volume", "array": "RTData", "values": [80.0, 150.0]},
                    note="The filter reports the name of the object it created, so it can be addressed next.",
                    check=lambda r: r.get("filter") == "Contour" and bool(r.get("name")),
                    bind={"contour": "name"},
                ),
                Step(
                    "paraview_display_hide",
                    {"name": "Volume"},
                    note="Hide the input so only the isosurfaces remain visible.",
                    check=lambda r: r.get("hidden") == "Volume",
                ),
                Step(
                    "paraview_display_color_by",
                    {"name": "$contour", "array": "RTData"},
                    note="Colour the contour using the name the filter returned.",
                    check=lambda r: r.get("array") == "RTData",
                ),
                Step(
                    "paraview_scene_list_sources",
                    note="Both the reader and the contour are in the pipeline.",
                    check=lambda r: len(_sources(r)) == 2,
                ),
                Step("paraview_view_reset_camera", check=lambda r: r.get("reset") is True),
                Step(
                    "paraview_export_screenshot",
                    {"filepath": shot("04-contour.png"), "width": 800, "height": 600},
                    check=_png_written(shot("04-contour.png")),
                    screenshot="04-contour.png",
                ),
            ],
            needs_render=True,
        ),
        Scenario(
            "05-slice-and-camera",
            "Slice the volume and aim the camera",
            "Slice the dataset through the origin along X, then look at it from the front.",
            [
                Step(
                    "paraview_display_hide",
                    {"name": "$contour"},
                    note="Clear the previous result to isolate the slice.",
                    check=lambda r: bool(r.get("hidden")),
                ),
                Step(
                    "paraview_filter_slice",
                    {"input": "Volume", "origin": [0.0, 0.0, 0.0], "normal": [1.0, 0.0, 0.0]},
                    note="A plane through the origin with an X normal.",
                    check=lambda r: r.get("filter") == "Slice" and r.get("normal") == [1.0, 0.0, 0.0],
                    bind={"slice": "name"},
                ),
                Step(
                    "paraview_display_color_by",
                    {"name": "$slice", "array": "RTData"},
                    check=lambda r: r.get("array") == "RTData",
                ),
                Step(
                    "paraview_view_set_camera",
                    {"position": [90.0, 0.0, 0.0], "focal_point": [0.0, 0.0, 0.0], "view_up": [0.0, 0.0, 1.0]},
                    note="Camera on the +X axis looking back at the origin.",
                    check=lambda r: r.get("position") == [90.0, 0.0, 0.0],
                ),
                Step(
                    "paraview_export_screenshot",
                    {"filepath": shot("05-slice-and-camera.png"), "width": 800, "height": 600},
                    check=_png_written(shot("05-slice-and-camera.png")),
                    screenshot="05-slice-and-camera.png",
                ),
            ],
            needs_render=True,
        ),
        Scenario(
            "06-threshold-and-export",
            "Threshold a range and export the result",
            "Keep only cells where RTData is between 100 and 200, then export that to a .vtu file.",
            [
                Step(
                    "paraview_filter_threshold",
                    {"input": "Volume", "array": "RTData", "lower": 100.0, "upper": 200.0},
                    check=lambda r: r.get("filter") == "Threshold" and r.get("lower") == 100.0,
                    bind={"threshold": "name"},
                ),
                Step(
                    "paraview_export_data",
                    {"name": "$threshold", "filepath": shot("06-threshold.vtu")},
                    note="Write the thresholded mesh out as an unstructured grid.",
                    check=lambda r: "filepath" in r and Path(r["filepath"]).exists(),
                ),
                Step(
                    "paraview_source_get_properties",
                    {"name": "$threshold"},
                    note="Read the filter's properties back from the pipeline.",
                    check=lambda r: isinstance(r.get("properties"), dict) and len(r["properties"]) > 0,
                ),
            ],
        ),
        Scenario(
            "07-python-escape-hatch",
            "Compute something the fixed tools do not cover",
            "Report the RTData range and cell count of the dataset.",
            [
                Step(
                    "paraview_python_exec",
                    {
                        "code": (
                            "src = None\n"
                            "for (name, _id), proxy in pvs.GetSources().items():\n"
                            "    if name == args['name']:\n"
                            "        src = proxy\n"
                            "if src is None:\n"
                            "    raise ValueError('source %r not found' % args['name'])\n"
                            "src.UpdatePipeline()\n"
                            "info = src.GetDataInformation()\n"
                            "array = src.PointData[args['array']]\n"
                            "__result__ = {\n"
                            "    'points': int(info.GetNumberOfPoints()),\n"
                            "    'cells': int(info.GetNumberOfCells()),\n"
                            "    'range': [round(v, 3) for v in array.GetRange()],\n"
                            "}\n"
                        ),
                        "args": {"name": "Volume", "array": "RTData"},
                        "timeout_seconds": 30,
                    },
                    note="Arbitrary paraview.simple code, with args passed in and a JSON result out.",
                    check=lambda r: (
                        r.get("error") is None and r["result"]["cells"] > 0 and len(r["result"]["range"]) == 2
                    ),
                ),
                Step(
                    "paraview_python_exec",
                    {
                        "code": (
                            "sphere = pvs.Sphere(registrationName='DemoSphere')\n"
                            "sphere.Radius = 12.0\n"
                            "sphere.ThetaResolution = 64\n"
                            "sphere.UpdatePipeline()\n"
                            "__result__ = {'shown': mcp.show(sphere)}\n"
                        ),
                        "timeout_seconds": 30,
                    },
                    note="mcp.show() displays only when a render view exists, so this is safe in both bridge modes.",
                    check=lambda r: r.get("error") is None and r["result"]["shown"] is True,
                ),
                Step(
                    "paraview_scene_list_sources",
                    note="The sphere created from Python is a first-class pipeline source.",
                    check=lambda r: "DemoSphere" in _sources(r),
                ),
            ],
            needs_render=True,
        ),
        Scenario(
            "10-vector-field",
            "Build a vector field, then glyph and trace it",
            "Make a vector field from the coordinates, show it with arrows, and trace streamlines through it.",
            [
                Step(
                    "paraview_filter_calculator",
                    {
                        "input": "Volume",
                        "expression": "coordsY*iHat - coordsX*jHat + 2*kHat",
                        "result_name": "Swirl",
                        "attribute_type": "Point Data",
                    },
                    note="A swirling vector field, computed from point coordinates.",
                    check=lambda r: r.get("filter") == "Calculator" and bool(r.get("name")),
                    bind={"calc": "name"},
                ),
                Step(
                    "paraview_filter_glyph",
                    {"input": "$calc", "glyph_type": "Arrow", "scale_array": "Swirl", "scale_factor": 2.0},
                    note="Arrows scaled by the computed vector.",
                    check=lambda r: r.get("filter") == "Glyph" and bool(r.get("name")),
                    bind={"glyph": "name"},
                ),
                Step(
                    "paraview_display_hide",
                    {"name": "Volume"},
                    note="Hide the source surface so the arrows are not buried in it.",
                    check=lambda r: r.get("hidden") == "Volume",
                ),
                Step(
                    "paraview_display_show",
                    {"name": "$glyph"},
                    note="Explicitly display the glyphs.",
                    check=lambda r: bool(r.get("shown")),
                ),
                Step(
                    "paraview_view_reset_camera",
                    check=lambda r: r.get("reset") is True,
                ),
                Step(
                    "paraview_export_screenshot",
                    {"filepath": shot("10-glyph.png"), "width": 800, "height": 600},
                    check=_png_written(shot("10-glyph.png")),
                    screenshot="10-glyph.png",
                ),
                Step(
                    "paraview_filter_stream_tracer",
                    {"input": "$calc", "seed_type": "Point Cloud", "num_points": 25, "max_length": 150.0},
                    note="Streamlines seeded through the same vector field.",
                    check=lambda r: r.get("filter") == "StreamTracer" and bool(r.get("name")),
                    bind={"streams": "name"},
                ),
                Step(
                    "paraview_display_hide",
                    {"name": "$glyph"},
                    check=lambda r: bool(r.get("hidden")),
                ),
                Step(
                    "paraview_display_hide",
                    {"name": "$calc"},
                    note="The Calculator surface is opaque and would hide the streamlines inside it.",
                    check=lambda r: bool(r.get("hidden")),
                ),
                Step(
                    "paraview_display_color_by",
                    {"name": "$streams", "array": "Swirl"},
                    check=lambda r: r.get("array") == "Swirl",
                ),
                Step(
                    "paraview_view_set_camera",
                    {"position": [70.0, -70.0, 45.0], "focal_point": [0.0, 0.0, 0.0], "view_up": [0.0, 0.0, 1.0]},
                    note="An oblique view reads better for 3D curves than a face-on one.",
                    check=lambda r: r.get("view_up") == [0.0, 0.0, 1.0],
                ),
                Step(
                    "paraview_export_screenshot",
                    {"filepath": shot("10-streamlines.png"), "width": 800, "height": 600},
                    check=_png_written(shot("10-streamlines.png")),
                    screenshot="10-streamlines.png",
                ),
            ],
            needs_render=True,
        ),
        Scenario(
            "11-clip-and-cleanup",
            "Clip the data, then tidy the pipeline",
            "Clip the volume in half along Y, then delete the filters I no longer need.",
            [
                Step(
                    "paraview_filter_clip",
                    {"input": "Volume", "origin": [0.0, 0.0, 0.0], "normal": [0.0, 1.0, 0.0]},
                    check=lambda r: r.get("filter") == "Clip" and bool(r.get("name")),
                    bind={"clip": "name"},
                ),
                Step(
                    "paraview_display_color_by",
                    {"name": "$clip", "array": "RTData"},
                    check=lambda r: r.get("array") == "RTData",
                ),
                Step(
                    "paraview_display_set_opacity",
                    {"name": "$clip", "opacity": 0.85},
                    note="A legal opacity, unlike the rejected one in scenario 08.",
                    check=lambda r: r.get("opacity") == 0.85,
                ),
                Step(
                    "paraview_export_screenshot",
                    {"filepath": shot("11-clip.png"), "width": 800, "height": 600},
                    check=_png_written(shot("11-clip.png")),
                    screenshot="11-clip.png",
                ),
                Step(
                    "paraview_source_delete",
                    {"name": "$streams"},
                    note="Remove the streamlines built in the previous scenario.",
                    check=lambda r: bool(r.get("deleted")),
                ),
                Step(
                    "paraview_scene_list_sources",
                    note="The deleted source is gone from the pipeline.",
                    check=lambda r: not any(name.startswith("StreamTracer") for name in _sources(r)),
                ),
            ],
            needs_render=True,
        ),
        Scenario(
            "12-animation",
            "Export an animation",
            "Export an animation of the current scene as a series of frames.",
            [
                Step(
                    "paraview_export_animation",
                    {"filepath": shot("12-animation.png"), "width": 320, "height": 240, "frame_rate": 5},
                    note="A .png target makes ParaView write a numbered frame series.",
                    check=lambda r: r.get("resolution") == [320, 240],
                ),
                Step(
                    "__check_animation_frames__",
                    note="At least one frame file must actually exist on disk.",
                    check=lambda r: r.get("frames", 0) >= 1,
                ),
            ],
            needs_render=True,
        ),
        Scenario(
            "13-cancel-a-job",
            "Cancel a job that is taking too long",
            "Start a long job, then change your mind and cancel it.",
            [
                Step(
                    "paraview_python_exec_async",
                    {"code": "import time\ntime.sleep(600)\n__result__ = {'done': True}\n"},
                    check=lambda r: r.get("job_id", "").startswith("headless-job-"),
                    bind={"job": "job_id"},
                ),
                Step(
                    "paraview_job_status",
                    {"job_id": "$job"},
                    note="The job is queued or running, not finished.",
                    check=lambda r: r.get("status") in {"queued", "running"},
                ),
                Step(
                    "paraview_job_cancel",
                    {"job_id": "$job"},
                    note="Cancelling must terminate the pvpython subprocess, not just mark the record.",
                    check=lambda r: r.get("status") == "cancelled",
                ),
                Step(
                    "paraview_job_status",
                    {"job_id": "$job"},
                    note="The cancellation is reflected when polled again.",
                    check=lambda r: r.get("status") == "cancelled" and r.get("cancelled") is True,
                ),
            ],
        ),
        Scenario(
            "14-session-status",
            "Ask about the session and the bridge",
            "Is the ParaView bridge reachable, and did you start it?",
            [
                Step(
                    "paraview_session_status",
                    note="Reports bridge reachability, auth state, and whether this server owns the session.",
                    check=lambda r: (
                        r["bridge"]["reachable"] is True
                        and r["session_process"]["managed"] is False
                        and "token_file" in r["auth"]
                    ),
                ),
                Step(
                    "paraview_session_stop",
                    note="There is no managed session to stop, and it says so rather than erroring.",
                    check=lambda r: r.get("stopped") is False and "no managed session" in r.get("reason", ""),
                ),
            ],
        ),
        Scenario(
            "08-guardrails",
            "Error handling and guardrails",
            "Try a few things that should fail cleanly rather than corrupt the session.",
            [
                Step(
                    "paraview_source_get_properties",
                    {"name": "NoSuchSource"},
                    note="An unknown source name is reported, not silently ignored.",
                    check=lambda r: r.get("__error__") and "not found" in r["__error__"],
                ),
                Step(
                    "paraview_display_set_opacity",
                    {"name": "Volume", "opacity": 4.0},
                    note="Opacity outside 0..1 is rejected by parameter validation.",
                    check=lambda r: r.get("__error__") and "between 0.0 and 1.0" in r["__error__"],
                ),
                Step(
                    "paraview_python_exec",
                    {"code": "x = 1", "transport": "sideways"},
                    note="An unknown transport is rejected instead of silently using the bridge.",
                    check=lambda r: r.get("__error__") and "transport must be one of" in r["__error__"],
                ),
                Step(
                    "paraview_python_exec",
                    {"code": "raise ValueError('boom')", "timeout_seconds": 15},
                    note="A failing script returns its traceback rather than killing the bridge.",
                    check=lambda r: "ValueError: boom" in (r.get("error") or ""),
                ),
                Step(
                    "paraview_scene_get_info",
                    note="The session is still healthy after all of that.",
                    check=lambda r: r.get("source_count", 0) > 0,
                ),
            ],
        ),
        Scenario(
            "09-async-job",
            "Run a long job without blocking",
            "Start a long-running computation in the background and poll it until it finishes.",
            [
                Step(
                    "paraview_python_exec_async",
                    {
                        "code": (
                            "import time\ntotal = sum(i * i for i in range(200000))\n__result__ = {'total': total}\n"
                        ),
                        "timeout_seconds": 120,
                    },
                    note="Returns a job id immediately; the work happens in a separate pvpython process.",
                    check=lambda r: r.get("job_id", "").startswith("headless-job-"),
                ),
                Step(
                    "paraview_job_list",
                    note="The job is tracked by the server.",
                    check=lambda r: len(r.get("jobs", [])) >= 1,
                ),
                Step(
                    "__poll_job__",
                    note="Poll paraview_job_status until the job leaves the running state.",
                    check=lambda r: r.get("status") == "succeeded" and r["result"]["total"] > 0,
                ),
            ],
        ),
    ]


def dataset_generator_script(target: str) -> str:
    """pvpython source that writes the demo dataset the scenarios load."""
    return (
        json.dumps(target)
        and f"""
import paraview.simple as pvs

wavelet = pvs.Wavelet()
wavelet.WholeExtent = [-20, 20, -20, 20, -20, 20]
wavelet.UpdatePipeline()
pvs.SaveData({target!r}, proxy=wavelet)
print("WROTE", {target!r})
"""
    )
