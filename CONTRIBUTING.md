# Contributing to paraview-mcp-server

Thanks for your interest in contributing! This document explains how to get
started, what we expect from pull requests, and how the project is organised.

## Quick Start

```bash
git clone https://github.com/djeada/paraview-mcp-server.git
cd paraview-mcp-server
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Development Workflow

### 1. Create a Branch

```bash
git checkout -b your-feature-name
```

### 2. Make Changes

The project has two main components:

| Component | Location | Runs inside |
|-----------|----------|-------------|
| MCP server | `src/paraview_mcp_server/` | Standalone Python process (stdio) |
| ParaView bridge | `src/paraview_mcp_bridge/` | `pvpython` subprocess |

The bridge package must stay **standard-library only**. It is imported by
ParaView's own Python runtime, which does not share this project's virtualenv
and has neither `mcp` nor `pydantic` available.

Scripts in `scripts/library/` run inside `pvpython` via `python.execute` and
reference the injected `args`, `pvs` and `mcp` names at module level — this is
expected, and why they are exempt from the undefined-name lint.

### 3. Lint and Format

```bash
ruff check src/ tests/ scripts/
ruff format src/ tests/ scripts/
mypy src/
```

All three commands must pass with zero errors. CI will reject PRs that fail.

### 4. Run Tests

```bash
pytest tests/ -v
```

Tests do **not** require ParaView to be installed. Bridge handler tests patch
`_import_pv` with a `MagicMock` that mimics the `paraview.simple` API.

Coverage is not on by default, so a single test runs without it. To collect it
the way CI does:

```bash
pytest tests/ --cov=paraview_mcp_server --cov=paraview_mcp_bridge --cov-report=term-missing
```

The minimum coverage threshold is 50 %.

Tests must not leave runaway threads or processes behind. A timed-out
`execute_code` leaves a thread running by design, so block it on an event
rather than a busy loop, and never leave one writing output.

### 4b. Run the demo scenarios (when you changed behaviour)

Unit tests mock `paraview.simple`, so they cannot tell you whether a tool does
anything *in ParaView*. If you changed a handler, run the end-to-end scenarios
against a real install:

```bash
python demos/run_scenarios.py
```

Then **look at the screenshots** in `demos/output/`, and at what the runner says
about surviving processes. All three bugs found in 0.2.0's demo pass — a
background colour that was set but never rendered, filters that never reported
what they created, and a cancelled job that left ParaView running — returned
success to every assertion. None was visible from the return values alone.

### 5. Commit and Push

Write clear commit messages. One logical change per commit.

```bash
git push origin your-feature-name
```

### 6. Open a Pull Request

- Fill in a description of **what** changed and **why**.
- Link any related issues.
- CI must pass before merge.

## Code Style

- **Formatter/Linter**: [Ruff](https://docs.astral.sh/ruff/) — configured in `pyproject.toml`.
- **Type checker**: [mypy](https://mypy-lang.org/) — `ignore_missing_imports = true` for `paraview`.
- **Line length**: 120 characters.
- **Imports**: sorted by `isort` rules via Ruff.
- **Python version**: 3.10+ (use `X | Y` unions, not `Optional[X]`).

## Project Layout

```
paraview-mcp-server/
├── src/
│   ├── paraview_mcp_server/      # MCP server (stdio + tool definitions)
│   └── paraview_mcp_bridge/      # ParaView bridge (TCP server + handlers)
├── scripts/
│   ├── library/                  # Reusable pvpython snippets
│   ├── start_paraview_bridge.py  # Bridge launcher
│   ├── start_paraview_gui_bridge.py # In-GUI bridge launcher
│   └── paraview_bridge_request.py # Debug CLI
├── demos/                        # End-to-end scenarios (needs a real ParaView)
├── tests/                        # Unit tests (no ParaView install required)
├── docs/                         # Architecture & design documentation
└── pyproject.toml                # Build, lint, test, and type-check config
```

`scripts/` is shipped inside the wheel as `paraview_mcp_server/_scripts/`, so
`paraview-mcp-launch` can find the bridge entry point from a PyPI install.
Adding a script there means adding it to the `force-include` table in
`pyproject.toml`.

## Adding a New MCP Tool

1. Add the bridge command handler in `src/paraview_mcp_bridge/command_handler.py` under `CommandHandler`.
2. Add a parameter model in `src/paraview_mcp_bridge/models.py` and register it in `_VALIDATORS`.
3. Register the MCP tool in `src/paraview_mcp_server/server.py` using `@mcp.tool(...)`.
4. Add tests in `tests/test_server.py` (tool registration) and
   `tests/test_command_handler.py` (handler logic).
5. Document the tool in `README.md` and `docs/architecture.md` under the
   appropriate namespace, and keep the tool counts in both consistent.

## Reporting Issues

- Use [GitHub Issues](https://github.com/djeada/paraview-mcp-server/issues).
- Include: ParaView version, Python version, OS, steps to reproduce, and error output.

## License

By contributing you agree that your contributions will be licensed under the
[MIT License](LICENSE).
