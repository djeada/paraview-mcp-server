"""Shared runtime locations and the bridge's local authentication token.

The bridge is a TCP endpoint that can execute arbitrary Python inside ParaView.
Binding to loopback keeps it off the network, but on a multi-user host every
local account can reach loopback, so the socket also requires a shared secret.

The secret lives in a file that only the owning user can read. The bridge
writes it at startup; the MCP server and the debug CLI read it. Both sides run
as the same user, so the file is the handshake — no key exchange is needed.

This module is imported by ParaView's Python runtime and therefore must not
depend on anything outside the standard library.
"""

from __future__ import annotations

import contextlib
import ipaddress
import os
import secrets
import stat
from pathlib import Path

TOKEN_ENV = "PARAVIEW_MCP_TOKEN"
TOKEN_FILE_ENV = "PARAVIEW_MCP_TOKEN_FILE"
STATE_DIR_ENV = "PARAVIEW_MCP_STATE_DIR"
DISABLE_AUTH_ENV = "PARAVIEW_MCP_DISABLE_AUTH"

_TOKEN_BYTES = 32


def auth_disabled() -> bool:
    """Whether the operator has explicitly opted out of bridge authentication."""
    return os.environ.get(DISABLE_AUTH_ENV) == "1"


def state_dir() -> Path:
    """Return a private, user-owned directory for bridge runtime state.

    Prefers ``$XDG_RUNTIME_DIR`` (tmpfs, already 0700 and per-user) and falls
    back to ``$XDG_STATE_HOME``/``~/.local/state``. Never ``/tmp``: a shared,
    world-writable directory invites symlink games and cross-user collisions.
    """
    override = os.environ.get(STATE_DIR_ENV)
    if override:
        base = Path(override)
    elif os.environ.get("XDG_RUNTIME_DIR"):
        base = Path(os.environ["XDG_RUNTIME_DIR"]) / "paraview-mcp-server"
    elif os.environ.get("XDG_STATE_HOME"):
        base = Path(os.environ["XDG_STATE_HOME"]) / "paraview-mcp-server"
    else:
        base = Path.home() / ".local" / "state" / "paraview-mcp-server"
    base.mkdir(parents=True, exist_ok=True)
    _harden_directory(base)
    return base


def _harden_directory(path: Path) -> None:
    # Windows and some network filesystems do not support POSIX modes.
    with contextlib.suppress(OSError):
        path.chmod(stat.S_IRWXU)


def token_file_path() -> Path:
    override = os.environ.get(TOKEN_FILE_ENV)
    if override:
        return Path(override)
    return state_dir() / "bridge.token"


def session_log_path() -> Path:
    override = os.environ.get("PARAVIEW_MCP_SESSION_LOG")
    if override:
        return Path(override)
    return state_dir() / "launch.log"


def open_private_append(path: Path):
    """Open *path* for appending without following a pre-existing symlink."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NOINHERIT", 0)
    fd = os.open(path, flags, 0o600)
    return os.fdopen(fd, "ab")


def create_token() -> str:
    """Generate a fresh token and persist it with owner-only permissions."""
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    path = token_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write through a private fd so the token is never briefly world-readable.
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token)
    with contextlib.suppress(OSError):
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return token


def read_token() -> str | None:
    """Return the token a bridge published, or ``None`` when there is none."""
    env_token = os.environ.get(TOKEN_ENV)
    if env_token:
        return env_token
    try:
        token = token_file_path().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None


def tokens_match(expected: str | None, supplied: object) -> bool:
    """Constant-time token comparison that tolerates missing/odd input."""
    if expected is None:
        return True
    if not isinstance(supplied, str):
        return False
    return secrets.compare_digest(expected, supplied)


def is_loopback(host: str) -> bool:
    if host in {"localhost", ""}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
