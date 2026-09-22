"""Shared test fixtures.

The bridge publishes its auth token into a per-user runtime directory. Tests
must never write there: doing so would overwrite the token of a bridge the
developer has actually running, silently breaking their live session.
"""

from __future__ import annotations

import pytest

from paraview_mcp_bridge import runtime


@pytest.fixture(autouse=True)
def isolated_state_dir(tmp_path, monkeypatch):
    """Redirect bridge runtime state (token, logs) into a per-test directory."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setenv(runtime.STATE_DIR_ENV, str(state_dir))
    monkeypatch.delenv(runtime.TOKEN_ENV, raising=False)
    monkeypatch.delenv(runtime.TOKEN_FILE_ENV, raising=False)
    monkeypatch.delenv(runtime.DISABLE_AUTH_ENV, raising=False)
    monkeypatch.delenv("PARAVIEW_MCP_SESSION_LOG", raising=False)
    return state_dir
