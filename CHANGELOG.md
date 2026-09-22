# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] — 2026-09-22

### Security
- The bridge now authenticates every request against a random token written at
  startup to a `0600` file in a private runtime directory. Previously any local
  process that could reach the loopback port could execute arbitrary Python in
  the ParaView session. Set `PARAVIEW_MCP_DISABLE_AUTH=1` to restore the old
  behaviour.
- Approved-root checks for `script_path` compare path components instead of
  string prefixes, so an approved root of `/srv/safe` no longer also admits
  `/srv/safe-evil/script.py`.
- The launcher log moved out of a predictable `/tmp` path into the private
  runtime directory and is opened without following symlinks.
- Requests are capped at 8 MB, so a peer that never sends a newline can no
  longer grow the receive buffer until the process dies.
- Binding the bridge to a non-loopback address now logs a warning.

### Fixed
- Cancelling an async job, and the headless execution timeout, now terminate the
  whole `pvpython` process tree. `pvpython` is a launcher that forks
  `pvpython-real` and waits for it, so signalling only the direct child left the
  process running the script alive indefinitely, holding CPU and the output
  pipes. Subprocesses are started in their own session and signalled as a group,
  escalating to `SIGKILL`. Found by the demo runner's post-run process check.
- `view.set_background` now actually changes the background. ParaView >= 5.10
  renders the colour palette background and ignores the view's `Background`
  property, so the tool reported success while nothing changed on screen. Found
  by looking at the demo screenshots, not by a test.
- Every filter tool now reports the registered `name` of the object it created,
  so a caller can address it in the next call instead of guessing `Contour1`.
  The call still succeeds with `"name": null` if the name cannot be resolved.
- A `python.execute` timeout no longer replaces the bridge process's
  `sys.stdout`/`sys.stderr` for the rest of its life. The worker thread cannot
  be killed and never unwound `redirect_stdout`, which silently swallowed the
  bridge's own logging and every later command's output. Capture is now routed
  per thread into bounded buffers, and the timeout result reports
  `abandoned_threads`.
- `paraview-mcp-launch` works from a PyPI install. The bridge entry points are
  shipped inside the wheel and the launcher hands `pvpython` a `PYTHONPATH`
  that reaches the bridge package; previously it looked for a `scripts/`
  directory that was never packaged and failed unless the working directory
  happened to be a source checkout. `paraview_session_start` failed the same
  way, and now reports the launcher log tail when a start fails.
- The in-GUI bridge answers pipelined requests. It handled one request per
  readable socket event, and `select()` cannot see requests already copied into
  a client buffer, so a client that batched two requests waited forever for the
  second.
- Headless timeouts keep the output produced before the process was killed,
  which is exactly what is needed to diagnose a hung script.
- Port readiness is detected portably instead of by parsing `/proc/net/tcp`,
  which silently never matched on macOS or Windows and always timed out.
- Concurrent tool calls no longer race to open two bridge connections and leak
  one of them.
- `paraview_python_exec` rejects an unknown `transport` instead of silently
  falling back to the bridge.
- Bridge commands reject unknown parameters instead of forwarding typos to the
  handlers.
- The stream tracer's default seed type is `Point Cloud` everywhere; the
  parameter model disagreed with the handler and the MCP tool.

### Added
- `demos/` — runnable end-to-end scenarios that drive a live ParaView session
  through the real MCP server as an MCP client, with screenshots and a
  generated report. See `docs/demos.md`.
- The bridge endpoint is configurable through `PARAVIEW_MCP_BRIDGE_HOST` and
  `PARAVIEW_MCP_BRIDGE_PORT` instead of being a constant in `server.py`.

### Changed
- **Breaking:** the bridge package is now `paraview_mcp_bridge` under `src/`,
  not a top-level `bridge`. A generic top-level name in site-packages collides
  with any other project claiming it.
- **Breaking:** the render-API guard for `python.execute` matches the parsed
  syntax tree instead of raw substrings. Comments and unrelated identifiers are
  no longer false positives, and `getattr(pvs, "Show")` is now caught. It
  remains a guardrail against accidental detached windows, not a sandbox.
- `python.execute` scripts get `mcp.show()`, `mcp.find_render_view()` and
  `mcp.reset_camera()` helpers, which no-op when no render view exists. The
  shipped pipeline library scripts use them and now run under the default
  bridge; the three render-only scripts are labelled as such. Previously every
  shipped script and every documented example was rejected by the guard.
- Async job records are evicted by age and count, so a long-lived server no
  longer accumulates every job it ever ran.
- Removed the unused `pydantic` dependency; the bridge models have been
  dependency-free since they must import under ParaView's Python.
- Coverage flags moved out of `addopts` into CI, so a single test run is no
  longer forced through coverage.
- Added `py.typed` to both packages and `__version__` to the package.
- The Docker image runs as a non-root user.

## [0.1.7] — 2026-06-29

### Added
- Added MCP-managed ParaView session lifecycle tools for starting, stopping, and inspecting GUI-backed sessions.
- Added a `python.execute` helper namespace with `mcp.create_polydata_source(...)` for publishing custom polydata without relying on unavailable client-side VTK output.

### Fixed
- Blocked render-view controls from separate `pvpython` bridge sessions unless explicitly enabled, preventing accidental detached render windows.
- Kept pipeline-only source and filter operations usable when render-view control is disabled.

## [0.1.6] — 2026-06-29

### Fixed
- Hardened the launcher to fail fast when the pvserver or MCP bridge ports are already in use, avoiding ParaView startup into a known port collision that can segfault.

## [0.1.5] — 2026-06-29

### Added
- Documented default bridge GUI/Qt limitations and detached VTK render-window troubleshooting.
- Added launcher supervision that restarts the ParaView-side bridge if it exits while the GUI is still running.

### Fixed
- Retried stale MCP bridge TCP connections once before surfacing transport failures.
- Prevented default `pvpython` bridge commands from creating detached `RenderView` windows unless explicitly allowed.
- Allowed pipeline-only source/filter creation without forcing a render view; responses now report whether new objects were shown.

## [0.1.4] — 2026-06-27

### Added
- CI pipeline (`ci.yml`): ruff lint, ruff format, mypy, pytest with coverage across Python 3.10–3.13.
- PyPI publish workflow (`publish-pypi.yml`): OIDC-based publishing gated on CI, triggered by version tags, releases, or manual dispatch.
- Ruff configuration (pycodestyle, pyflakes, isort, pep8-naming, pyupgrade, bugbear, simplify, type-checking).
- Mypy configuration with `check_untyped_defs` and `ignore_missing_imports`.
- pytest-cov integration with 50 % minimum coverage threshold (currently 76 %).
- `CONTRIBUTING.md` with development workflow, code style, and PR guidelines.
- This `CHANGELOG.md`.
- Pydantic models for runtime validation of all bridge command parameters (`bridge/models.py`).
- `Dockerfile` and `.dockerignore` for containerized deployment.
- Explicit `pydantic>=2.0` dependency.

### Fixed
- Import sorting and formatting across all source files.
- Moved `Callable` import behind `TYPE_CHECKING` guard in command handler.
- Replaced bare `try/except pass` with `contextlib.suppress` in headless executor.
- Removed unused variable in test suite.

## [0.1.0] — 2026-03-28

### Added
- Initial MCP server with 31 tools across 9 namespaces: scene/session,
  data loading, basic filters (slice, clip, contour, threshold), advanced
  filters (calculator, stream tracer, glyph), display/coloring, camera/view,
  export, Python execution, and job management.
- ParaView bridge server running inside `pvpython` with 27 command handlers.
- Headless `pvpython` execution transport for standalone script execution.
- Async job system (create, poll, cancel, list) for long-running computations.
- Safety model: module blocklist (12 modules), output bounding (50 KB),
  cooperative timeouts (30 s default), script path validation.
- Script library with 6 reusable `pvpython` snippets.
- Architecture documentation and Python execution design spec.
- Unit tests: 85 tests covering bridge handlers, TCP protocol, MCP server
  tools, headless executor, and async job lifecycle.

[Unreleased]: https://github.com/djeada/paraview-mcp-server/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/djeada/paraview-mcp-server/compare/v0.1.7...v0.2.0
[0.1.7]: https://github.com/djeada/paraview-mcp-server/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/djeada/paraview-mcp-server/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/djeada/paraview-mcp-server/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/djeada/paraview-mcp-server/releases/tag/v0.1.4
[0.1.0]: https://github.com/djeada/paraview-mcp-server/releases/tag/v0.1.0
