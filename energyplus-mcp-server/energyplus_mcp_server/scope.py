"""Per-token file-access scoping for the streamable-http transport.

Each bearer token's label maps to a private directory under
``config.paths.user_data_root``. While a request is scoped to a label:

- reads are allowed only inside that directory and the shared, read-only
  reference directories (sample files, EnergyPlus example files, weather data);
- writes are allowed only inside that directory.

In stdio mode there is no label and the server keeps its unscoped behavior
(a single local user who already owns the filesystem). In streamable-http mode
a missing label is an error: file access fails closed rather than falling back
to unscoped paths.

EnergyPlus Model Context Protocol Server (EnergyPlus-MCP)
Copyright (c) 2025, The Regents of the University of California,
through Lawrence Berkeley National Laboratory (subject to receipt of
any required approvals from the U.S. Dept. of Energy). All rights reserved.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

from energyplus_mcp_server.auth import REQUEST_STATE_LABEL_KEY, current_token_label


class ScopeError(PermissionError):
    """Raised when a path falls outside the caller's permitted directories."""


@dataclass(frozen=True)
class AccessScope:
    """The directories one authenticated caller may use."""

    label: str
    user_root: str
    read_roots: tuple

    def can_read(self, path: str) -> bool:
        return any(_is_within(path, root) for root in self.read_roots)

    def can_write(self, path: str) -> bool:
        return _is_within(path, self.user_root)


def _real(path: str) -> str:
    return os.path.realpath(os.path.abspath(path))


def _is_within(path: str, root: str) -> bool:
    """True if ``path`` (after resolving symlinks and ``..``) is ``root`` or below it."""
    if not root:
        return False
    real_path, real_root = _real(path), _real(root)
    try:
        return os.path.commonpath([real_path, real_root]) == real_root
    except ValueError:  # different drives on Windows
        return False


def _label_from_mcp_request() -> Optional[str]:
    """Read the label stamped on the HTTP request that triggered this tool call.

    With the streamable-http transport, tool handlers run inside the MCP
    session's long-lived task. That task copies its context from the request
    that created the session, so a ContextVar set in AuthMiddleware reflects
    the session's first caller, not the caller of the current request. The MCP
    SDK attaches the originating Starlette Request to each call's request
    context, which is the per-request source of truth.
    """
    try:
        from mcp.server.lowlevel.server import request_ctx
    except ImportError:  # pragma: no cover - very old mcp
        return None
    try:
        ctx = request_ctx.get()
    except LookupError:
        return None
    request = getattr(ctx, "request", None)
    state = getattr(request, "scope", {}).get("state", {}) if request is not None else {}
    label = state.get(REQUEST_STATE_LABEL_KEY) if isinstance(state, dict) else None
    return label if isinstance(label, str) else None


def current_label() -> Optional[str]:
    """Token label for the current call: MCP request state first, then the ContextVar."""
    return _label_from_mcp_request() or current_token_label()


def user_root_for(config, label: str) -> str:
    return os.path.join(config.paths.user_data_root, label)


def current_scope(config) -> Optional[AccessScope]:
    """Return the caller's scope, or None when file access is unscoped (stdio).

    Raises ScopeError in streamable-http mode when no label is available, so a
    wiring mistake can never silently grant unscoped access.
    """
    label = current_label()
    if label is None:
        if config.transport.transport == "streamable-http":
            raise ScopeError("file access denied: request has no authenticated identity")
        return None

    user_root = user_root_for(config, label)
    os.makedirs(user_root, exist_ok=True)
    shared: List[str] = [
        config.paths.sample_files_path,
        config.energyplus.example_files_path,
        config.energyplus.weather_data_path,
    ]
    read_roots = tuple([user_root] + [p for p in shared if p])
    return AccessScope(label=label, user_root=user_root, read_roots=read_roots)


def is_admin(config) -> bool:
    """True for stdio callers and for HTTP tokens listed in MCP_ADMIN_LABELS."""
    label = current_label()
    if label is None:
        return config.transport.transport != "streamable-http"
    return label in config.auth.admin_labels


def require_admin(config, action: str) -> None:
    if not is_admin(config):
        raise ScopeError(f"{action} requires an admin token")


def check_read(scope: Optional[AccessScope], path: str, description: str = "file") -> str:
    """Return the real path if readable in ``scope``; raise ScopeError otherwise."""
    if scope is None:
        return path
    if not scope.can_read(path):
        raise ScopeError(f"{description} is outside the directories this token may read: {path}")
    return _real(path)


def check_write(scope: Optional[AccessScope], path: str, description: str = "output") -> str:
    """Return the real path if writable in ``scope``; raise ScopeError otherwise."""
    if scope is None:
        return path
    if not scope.can_write(path):
        raise ScopeError(
            f"{description} must be inside this token's workspace ({scope.user_root}): {path}"
        )
    return _real(path)
