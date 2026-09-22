# Demo scenarios

End-to-end scenarios that drive a **real ParaView session** through the **real
MCP server**, then check what actually happened:

```
run_scenarios.py (MCP client) → paraview-mcp-server → bridge → ParaView
```

Each scenario is a prompt a user could type into an MCP client, the tool calls
an assistant would make to satisfy it, and assertions on the results. Several
scenarios also save a screenshot, so the output can be judged by eye rather
than only by return codes — which is how two real bugs were found (see
[`docs/demos.md`](../docs/demos.md)).

## Running them

```bash
pip install -e ".[dev]"
python demos/run_scenarios.py
```

Requires ParaView (`pvpython` on `PATH`, or `PVPYTHON_BIN` set). `Xvfb` is used
automatically when available so nothing appears on your desktop.

```bash
python demos/run_scenarios.py --only 04 05     # just these scenarios
python demos/run_scenarios.py --keep-going     # do not stop at the first failure
python demos/run_scenarios.py --bridge-port 9900
```

Artifacts land in `demos/output/` (git-ignored) and a Markdown report is
written to `docs/demo-run.md`.

## What they cover

| Scenario | Prompt | Exercises |
|---|---|---|
| `01-inspect` | "What's currently loaded in ParaView?" | `scene_get_info`, `scene_list_sources`, `scene_list_views` |
| `02-open-and-render` | "Open this file and save a picture of it." | `source_open_file`, `source_rename`, `display_set_representation`, `view_reset_camera`, `export_screenshot` |
| `03-color-by-array` | "Colour it by RTData and rescale the colour map." | `display_color_by`, `display_rescale_transfer_function`, `view_set_background` |
| `04-contour` | "Contour RTData at 80 and 150, hide the volume." | `filter_contour`, `display_hide`, `display_color_by` |
| `05-slice-and-camera` | "Slice through the origin along X, look from the front." | `filter_slice`, `view_set_camera` |
| `06-threshold-and-export` | "Keep RTData between 100 and 200, export to .vtu." | `filter_threshold`, `export_data`, `source_get_properties` |
| `07-python-escape-hatch` | "Report the RTData range and cell count." | `python_exec`, the `mcp` helpers |
| `08-guardrails` | "Try things that should fail cleanly." | error paths, parameter validation, transport validation |
| `09-async-job` | "Run something long in the background and poll it." | `python_exec_async`, `job_list`, `job_status` |
| `10-vector-field` | "Make a vector field, show arrows, trace streamlines." | `filter_calculator`, `filter_glyph`, `filter_stream_tracer`, `display_show` |
| `11-clip-and-cleanup` | "Clip in half along Y, delete what I don't need." | `filter_clip`, `display_set_opacity`, `source_delete` |
| `12-animation` | "Export an animation of the scene." | `export_animation` |
| `13-cancel-a-job` | "Start a long job, then cancel it." | `job_cancel`, `job_status` |
| `14-session-status` | "Is the bridge reachable, and did you start it?" | `session_status`, `session_stop` |

Together they cover 31 of the 34 tools. The rest (`session_start`, and
`session_stop` against a live session) launch a full `pvserver` + ParaView GUI,
which an automated run should not spawn.

## Writing a scenario

Add a `Scenario` to `scenarios.py`:

```python
Scenario(
    "10-my-scenario",
    "Short title",
    "The prompt a user would actually type.",
    [
        Step(
            "paraview_filter_clip",
            {"input": "Volume", "normal": [0.0, 1.0, 0.0]},
            note="Shown under the table in the generated report.",
            check=lambda r: r["filter"] == "Clip",
            bind={"clip": "name"},          # capture r["name"] as $clip
        ),
        Step(
            "paraview_display_color_by",
            {"name": "$clip", "array": "RTData"},   # substituted from the context
            check=lambda r: r["array"] == "RTData",
        ),
    ],
)
```

`bind` and `$name` exist because **ParaView chooses the registered names**.
Opening `demo.vti` yields a source called `XMLImageDataReader1`, and a slice
becomes `Slice1`. Hard-coding those makes scenarios lie about how an assistant
actually has to work: it must read the name out of the previous result.

## Safety

These scenarios start real processes. The runner:

- starts every child in its own **process group** and tears the group down, so
  the `Xvfb` and `pvpython` that `xvfb-run` spawns cannot be orphaned;
- converts `SIGTERM`/`SIGHUP` into an exception so teardown still runs;
- warns if any `pvpython`, `pvserver` or `Xvfb` process survives the run;
- refuses to start if the bridge port is already in use, and defaults to
  **9899** rather than 9876 so it will not collide with a bridge you already
  have running.
