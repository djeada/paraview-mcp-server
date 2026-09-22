# ParaView MCP — demo scenario run

**14/14 scenarios passed.**

| | |
|---|---|
| ParaView | 6.0.1 |
| Bridge | standalone pvpython on 127.0.0.1:9899 |
| Render control | PARAVIEW_MCP_ALLOW_DETACHED_RENDER_WINDOW=1 (headless screenshots) |
| Display | Xvfb |

Each scenario below is a prompt a user could give an MCP client, the tool calls that satisfy it, and what ParaView actually returned. Regenerate with `python demos/run_scenarios.py`.

## 01-inspect — Inspect an empty session (PASS)

> **Prompt:** What's currently loaded in ParaView?

| Step | Tool | Result |
|---|---|---|
| ✓ | `paraview_scene_get_info` | `{"source_count": 0, "active_view_type": "RenderView", "render_view_available": true}` |
| ✓ | `paraview_scene_list_sources` | `{"sources": []}` |
| ✓ | `paraview_scene_list_views` | `{"views": [{"type": "RenderView", "id": "281"}]}` |

- **`paraview_scene_get_info`** — Asking the session to describe itself.
- **`paraview_scene_list_sources`** — A fresh session has an empty pipeline.
- **`paraview_scene_list_views`** — The bridge reports the views it can see.

## 02-open-and-render — Open a dataset and render it (PASS)

> **Prompt:** Open /home/adam/my_repos/paraview-mcp-server/demos/output/demo.vti and save a picture of it to disk.

| Step | Tool | Result |
|---|---|---|
| ✓ | `paraview_source_open_file` | `{"name": "XMLImageDataReader1", "label": "XML Image Data Reader", "filepath": "/home/adam/my_repos/paraview-mcp-server/demos/output/demo.vti", "proxy_class":…` |
| ✓ | `paraview_source_rename` | `{"old_name": "XMLImageDataReader1", "new_name": "Volume"}` |
| ✓ | `paraview_scene_list_sources` | `{"sources": [{"name": "Volume", "id": "3219", "proxy_class": "XMLImageDataReader"}]}` |
| ✓ | `paraview_display_set_representation` | `{"name": "Volume", "representation": "Surface"}` |
| ✓ | `paraview_view_reset_camera` | `{"reset": true}` |
| ✓ | `paraview_export_screenshot` | `{"filepath": "/home/adam/my_repos/paraview-mcp-server/demos/output/02-open-and-render.png", "resolution": [800, 600], "transparent": false}` |

- **`paraview_source_open_file`** — ParaView picks the registered name (here XMLImageDataReader1), and the tool reports it.
- **`paraview_source_rename`** — Rename it to something readable; later steps address it as 'Volume'.
- **`paraview_scene_list_sources`** — The pipeline now holds exactly the renamed source.
- **`paraview_display_set_representation`** — ParaView shows image data as an Outline by default, which renders as an empty wireframe box. Ask for Surface to actually see the data.
- **`paraview_view_reset_camera`** — Fit the data in the view before capturing.
- **`paraview_export_screenshot`** — Render the view to a PNG.

![Open a dataset and render it](images/02-open-and-render.png)

## 03-color-by-array — Colour the data by a scalar array (PASS)

> **Prompt:** Colour it by the RTData array and rescale the colour map to the data range.

| Step | Tool | Result |
|---|---|---|
| ✓ | `paraview_display_color_by` | `{"name": "Volume", "array": "RTData", "association": "POINTS", "component": -1}` |
| ✓ | `paraview_display_rescale_transfer_function` | `{"name": "Volume", "rescaled": true}` |
| ✓ | `paraview_view_set_background` | `{"color": [0.08, 0.09, 0.12], "gradient": false}` |
| ✓ | `paraview_export_screenshot` | `{"filepath": "/home/adam/my_repos/paraview-mcp-server/demos/output/03-color-by-array.png", "resolution": [800, 600], "transparent": false}` |

- **`paraview_display_color_by`** — Map the RTData point array onto the surface.
- **`paraview_display_rescale_transfer_function`** — Fit the colour map to the actual value range.
- **`paraview_view_set_background`** — A dark background so the colour map reads clearly.

![Colour the data by a scalar array](images/03-color-by-array.png)

## 04-contour — Extract an isosurface (PASS)

> **Prompt:** Add a contour of RTData at values 80 and 150, and hide the original volume.

| Step | Tool | Result |
|---|---|---|
| ✓ | `paraview_filter_contour` | `{"name": "Contour1", "input": "Volume", "filter": "Contour", "array": "RTData", "values": [80.0, 150.0], "shown": true}` |
| ✓ | `paraview_display_hide` | `{"hidden": "Volume"}` |
| ✓ | `paraview_display_color_by` | `{"name": "Contour1", "array": "RTData", "association": "POINTS", "component": -1}` |
| ✓ | `paraview_scene_list_sources` | `{"sources": [{"name": "Contour1", "id": "3605", "proxy_class": "Contour"}, {"name": "Volume", "id": "3219", "proxy_class": "XMLImageDataReader"}]}` |
| ✓ | `paraview_view_reset_camera` | `{"reset": true}` |
| ✓ | `paraview_export_screenshot` | `{"filepath": "/home/adam/my_repos/paraview-mcp-server/demos/output/04-contour.png", "resolution": [800, 600], "transparent": false}` |

- **`paraview_filter_contour`** — The filter reports the name of the object it created, so it can be addressed next.
- **`paraview_display_hide`** — Hide the input so only the isosurfaces remain visible.
- **`paraview_display_color_by`** — Colour the contour using the name the filter returned.
- **`paraview_scene_list_sources`** — Both the reader and the contour are in the pipeline.

![Extract an isosurface](images/04-contour.png)

## 05-slice-and-camera — Slice the volume and aim the camera (PASS)

> **Prompt:** Slice the dataset through the origin along X, then look at it from the front.

| Step | Tool | Result |
|---|---|---|
| ✓ | `paraview_display_hide` | `{"hidden": "Contour1"}` |
| ✓ | `paraview_filter_slice` | `{"name": "Slice1", "input": "Volume", "filter": "Slice", "origin": [0.0, 0.0, 0.0], "normal": [1.0, 0.0, 0.0], "shown": true}` |
| ✓ | `paraview_display_color_by` | `{"name": "Slice1", "array": "RTData", "association": "POINTS", "component": -1}` |
| ✓ | `paraview_view_set_camera` | `{"position": [90.0, 0.0, 0.0], "focal_point": [0.0, 0.0, 0.0], "view_up": [0.0, 0.0, 1.0], "parallel_scale": 34.64101615137755}` |
| ✓ | `paraview_export_screenshot` | `{"filepath": "/home/adam/my_repos/paraview-mcp-server/demos/output/05-slice-and-camera.png", "resolution": [800, 600], "transparent": false}` |

- **`paraview_display_hide`** — Clear the previous result to isolate the slice.
- **`paraview_filter_slice`** — A plane through the origin with an X normal.
- **`paraview_view_set_camera`** — Camera on the +X axis looking back at the origin.

![Slice the volume and aim the camera](images/05-slice-and-camera.png)

## 06-threshold-and-export — Threshold a range and export the result (PASS)

> **Prompt:** Keep only cells where RTData is between 100 and 200, then export that to a .vtu file.

| Step | Tool | Result |
|---|---|---|
| ✓ | `paraview_filter_threshold` | `{"name": "Threshold1", "input": "Volume", "filter": "Threshold", "array": "RTData", "lower": 100.0, "upper": 200.0, "shown": true}` |
| ✓ | `paraview_export_data` | `{"name": "Threshold1", "filepath": "/home/adam/my_repos/paraview-mcp-server/demos/output/06-threshold.vtu"}` |
| ✓ | `paraview_source_get_properties` | `{"name": "Threshold1", "properties": {"AllScalars": 1, "Invert": 0, "LowerThreshold": 100.0, "UpperThreshold": 200.0, "UseContinuousCellRange": 0}}` |

- **`paraview_export_data`** — Write the thresholded mesh out as an unstructured grid.
- **`paraview_source_get_properties`** — Read the filter's properties back from the pipeline.

## 07-python-escape-hatch — Compute something the fixed tools do not cover (PASS)

> **Prompt:** Report the RTData range and cell count of the dataset.

| Step | Tool | Result |
|---|---|---|
| ✓ | `paraview_python_exec` | `{"result": {"points": 68921, "cells": 64000, "range": [34.015, 286.341]}, "stdout": "", "stderr": "", "error": null, "duration_seconds": 0.0016, "timed_out":…` |
| ✓ | `paraview_python_exec` | `{"result": {"shown": true}, "stdout": "", "stderr": "", "error": null, "duration_seconds": 0.0435, "timed_out": false, "abandoned_threads": 0}` |
| ✓ | `paraview_scene_list_sources` | `{"sources": [{"name": "Contour1", "id": "3605", "proxy_class": "Contour"}, {"name": "DemoSphere", "id": "4955", "proxy_class": "Sphere"}, {"name": "Slice1", …` |

- **`paraview_python_exec`** — Arbitrary paraview.simple code, with args passed in and a JSON result out.
- **`paraview_python_exec`** — mcp.show() displays only when a render view exists, so this is safe in both bridge modes.
- **`paraview_scene_list_sources`** — The sphere created from Python is a first-class pipeline source.

## 10-vector-field — Build a vector field, then glyph and trace it (PASS)

> **Prompt:** Make a vector field from the coordinates, show it with arrows, and trace streamlines through it.

| Step | Tool | Result |
|---|---|---|
| ✓ | `paraview_filter_calculator` | `{"name": "Calculator1", "input": "Volume", "filter": "Calculator", "expression": "coordsY*iHat - coordsX*jHat + 2*kHat", "result_name": "Swirl", "shown": true}` |
| ✓ | `paraview_filter_glyph` | `{"name": "Glyph1", "input": "Calculator1", "filter": "Glyph", "glyph_type": "Arrow", "scale_factor": 2.0, "shown": true}` |
| ✓ | `paraview_display_hide` | `{"hidden": "Volume"}` |
| ✓ | `paraview_display_show` | `{"shown": "Glyph1"}` |
| ✓ | `paraview_view_reset_camera` | `{"reset": true}` |
| ✓ | `paraview_export_screenshot` | `{"filepath": "/home/adam/my_repos/paraview-mcp-server/demos/output/10-glyph.png", "resolution": [800, 600], "transparent": false}` |
| ✓ | `paraview_filter_stream_tracer` | `{"name": "StreamTracer1", "input": "Calculator1", "filter": "StreamTracer", "seed_type": "Point Cloud", "integration_direction": "BOTH", "num_points": 25, "m…` |
| ✓ | `paraview_display_hide` | `{"hidden": "Glyph1"}` |
| ✓ | `paraview_display_hide` | `{"hidden": "Calculator1"}` |
| ✓ | `paraview_display_color_by` | `{"name": "StreamTracer1", "array": "Swirl", "association": "POINTS", "component": -1}` |
| ✓ | `paraview_view_set_camera` | `{"position": [70.0, -70.0, 45.0], "focal_point": [0.0, 0.0, 0.0], "view_up": [0.0, 0.0, 1.0], "parallel_scale": 87.74916057497546}` |
| ✓ | `paraview_export_screenshot` | `{"filepath": "/home/adam/my_repos/paraview-mcp-server/demos/output/10-streamlines.png", "resolution": [800, 600], "transparent": false}` |

- **`paraview_filter_calculator`** — A swirling vector field, computed from point coordinates.
- **`paraview_filter_glyph`** — Arrows scaled by the computed vector.
- **`paraview_display_hide`** — Hide the source surface so the arrows are not buried in it.
- **`paraview_display_show`** — Explicitly display the glyphs.
- **`paraview_filter_stream_tracer`** — Streamlines seeded through the same vector field.
- **`paraview_display_hide`** — The Calculator surface is opaque and would hide the streamlines inside it.
- **`paraview_view_set_camera`** — An oblique view reads better for 3D curves than a face-on one.

![Build a vector field, then glyph and trace it](images/10-glyph.png)

![Build a vector field, then glyph and trace it](images/10-streamlines.png)

## 11-clip-and-cleanup — Clip the data, then tidy the pipeline (PASS)

> **Prompt:** Clip the volume in half along Y, then delete the filters I no longer need.

| Step | Tool | Result |
|---|---|---|
| ✓ | `paraview_filter_clip` | `{"name": "Clip1", "input": "Volume", "filter": "Clip", "origin": [0.0, 0.0, 0.0], "normal": [0.0, 1.0, 0.0], "shown": true}` |
| ✓ | `paraview_display_color_by` | `{"name": "Clip1", "array": "RTData", "association": "POINTS", "component": -1}` |
| ✓ | `paraview_display_set_opacity` | `{"name": "Clip1", "opacity": 0.85}` |
| ✓ | `paraview_export_screenshot` | `{"filepath": "/home/adam/my_repos/paraview-mcp-server/demos/output/11-clip.png", "resolution": [800, 600], "transparent": false}` |
| ✓ | `paraview_source_delete` | `{"deleted": "StreamTracer1"}` |
| ✓ | `paraview_scene_list_sources` | `{"sources": [{"name": "Calculator1", "id": "5203", "proxy_class": "Calculator"}, {"name": "Clip1", "id": "6124", "proxy_class": "Clip"}, {"name": "Contour1",…` |

- **`paraview_display_set_opacity`** — A legal opacity, unlike the rejected one in scenario 08.
- **`paraview_source_delete`** — Remove the streamlines built in the previous scenario.
- **`paraview_scene_list_sources`** — The deleted source is gone from the pipeline.

![Clip the data, then tidy the pipeline](images/11-clip.png)

## 12-animation — Export an animation (PASS)

> **Prompt:** Export an animation of the current scene as a series of frames.

| Step | Tool | Result |
|---|---|---|
| ✓ | `paraview_export_animation` | `{"filepath": "/home/adam/my_repos/paraview-mcp-server/demos/output/12-animation.png", "resolution": [320, 240], "frame_rate": 5}` |
| ✓ | `__check_animation_frames__` | `{"frames": 1, "files": ["12-animation.0000.png"]}` |

- **`paraview_export_animation`** — A .png target makes ParaView write a numbered frame series.
- **`__check_animation_frames__`** — At least one frame file must actually exist on disk.

## 13-cancel-a-job — Cancel a job that is taking too long (PASS)

> **Prompt:** Start a long job, then change your mind and cancel it.

| Step | Tool | Result |
|---|---|---|
| ✓ | `paraview_python_exec_async` | `{"job_id": "headless-job-8b625d54"}` |
| ✓ | `paraview_job_status` | `{"job_id": "headless-job-8b625d54", "status": "running", "created_at": 1790078144.3149111, "started_at": 1790078144.3154097, "completed_at": null, "result": …` |
| ✓ | `paraview_job_cancel` | `{"job_id": "headless-job-8b625d54", "status": "cancelled"}` |
| ✓ | `paraview_job_status` | `{"job_id": "headless-job-8b625d54", "status": "cancelled", "created_at": 1790078144.3149111, "started_at": 1790078144.3154097, "completed_at": 1790078144.319…` |

- **`paraview_job_status`** — The job is queued or running, not finished.
- **`paraview_job_cancel`** — Cancelling must terminate the pvpython subprocess, not just mark the record.
- **`paraview_job_status`** — The cancellation is reflected when polled again.

## 14-session-status — Ask about the session and the bridge (PASS)

> **Prompt:** Is the ParaView bridge reachable, and did you start it?

| Step | Tool | Result |
|---|---|---|
| ✓ | `paraview_session_status` | `{"bridge": {"host": "127.0.0.1", "port": 9899, "reachable": true}, "auth": {"token_file": "/run/user/1000/paraview-mcp-server/bridge.token", "token_available…` |
| ✓ | `paraview_session_stop` | `{"stopped": false, "reason": "no managed session process"}` |

- **`paraview_session_status`** — Reports bridge reachability, auth state, and whether this server owns the session.
- **`paraview_session_stop`** — There is no managed session to stop, and it says so rather than erroring.

## 08-guardrails — Error handling and guardrails (PASS)

> **Prompt:** Try a few things that should fail cleanly rather than corrupt the session.

| Step | Tool | Result |
|---|---|---|
| ✓ | `paraview_source_get_properties` | `{"__error__": "Error executing tool paraview_source_get_properties: Source 'NoSuchSource' not found in the pipeline"}` |
| ✓ | `paraview_display_set_opacity` | `{"__error__": "Error executing tool paraview_display_set_opacity: opacity must be between 0.0 and 1.0"}` |
| ✓ | `paraview_python_exec` | `{"__error__": "Error executing tool paraview_python_exec: transport must be one of bridge, headless, got 'sideways'"}` |
| ✓ | `paraview_python_exec` | `{"result": null, "stdout": "", "stderr": "", "error": "Traceback (most recent call last):\n  File \"/home/adam/my_repos/paraview-mcp-server/src/paraview_mcp_…` |
| ✓ | `paraview_scene_get_info` | `{"source_count": 8, "active_view_type": "RenderView", "render_view_available": true}` |

- **`paraview_source_get_properties`** — An unknown source name is reported, not silently ignored.
- **`paraview_display_set_opacity`** — Opacity outside 0..1 is rejected by parameter validation.
- **`paraview_python_exec`** — An unknown transport is rejected instead of silently using the bridge.
- **`paraview_python_exec`** — A failing script returns its traceback rather than killing the bridge.
- **`paraview_scene_get_info`** — The session is still healthy after all of that.

## 09-async-job — Run a long job without blocking (PASS)

> **Prompt:** Start a long-running computation in the background and poll it until it finishes.

| Step | Tool | Result |
|---|---|---|
| ✓ | `paraview_python_exec_async` | `{"job_id": "headless-job-548d17ea"}` |
| ✓ | `paraview_job_list` | `{"jobs": [{"job_id": "headless-job-8b625d54", "status": "cancelled", "created_at": 1790078144.3149111}, {"job_id": "headless-job-548d17ea", "status": "runnin…` |
| ✓ | `__poll_job__` | `{"job_id": "headless-job-548d17ea", "status": "succeeded", "created_at": 1790078144.3348544, "started_at": 1790078144.3354185, "completed_at": 1790078145.530…` |

- **`paraview_python_exec_async`** — Returns a job id immediately; the work happens in a separate pvpython process.
- **`paraview_job_list`** — The job is tracked by the server.
- **`__poll_job__`** — Poll paraview_job_status until the job leaves the running state.
