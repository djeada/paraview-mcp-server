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
| ParaView bridge | `bridge/` | `pvpython` subprocess |

Scripts in `scripts/library/` run inside `pvpython` via `python.execute` and may
reference `args` or `paraview.simple` at module level — this is expected.

### 3. Lint and Format

```bash
ruff check src/ bridge/ tests/ scripts/
ruff format src/ bridge/ tests/ scripts/
mypy src/ bridge/
```

All three commands must pass with zero errors. CI will reject PRs that fail.

### 4. Run Tests

```bash
pytest tests/ -v
```

Tests do **not** require ParaView to be installed. Bridge handler tests patch
`_import_pv` with a `MagicMock` that mimics the `paraview.simple` API.

Coverage is collected automatically. The minimum coverage threshold is 50 %.

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
├── bridge/                       # ParaView bridge (TCP server + handlers)
├── src/paraview_mcp_server/      # MCP server (stdio + tool definitions)
├── scripts/
│   ├── library/                  # Reusable pvpython snippets
│   ├── start_paraview_bridge.py  # Bridge launcher
│   └── paraview_bridge_request.py # Debug CLI
├── tests/                        # Unit tests (no ParaView install required)
├── docs/                         # Architecture & design documentation
└── pyproject.toml                # Build, lint, test, and type-check config
```

## Adding a New MCP Tool

1. Add the bridge command handler in `bridge/command_handler.py` under `CommandHandler`.
2. Register the MCP tool in `src/paraview_mcp_server/server.py` using `@mcp.tool(...)`.
3. Add tests in `tests/test_server.py` (tool registration) and
   `tests/test_command_handler.py` (handler logic).
4. Document the tool in `README.md` under the appropriate namespace.

## Reporting Issues

- Use [GitHub Issues](https://github.com/djeada/paraview-mcp-server/issues).
- Include: ParaView version, Python version, OS, steps to reproduce, and error output.

## License

By contributing you agree that your contributions will be licensed under the
[MIT License](LICENSE).
