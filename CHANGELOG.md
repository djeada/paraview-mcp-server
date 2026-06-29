# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/djeada/paraview-mcp-server/compare/v0.1.6...HEAD
[0.1.6]: https://github.com/djeada/paraview-mcp-server/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/djeada/paraview-mcp-server/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/djeada/paraview-mcp-server/releases/tag/v0.1.4
[0.1.0]: https://github.com/djeada/paraview-mcp-server/releases/tag/v0.1.0
