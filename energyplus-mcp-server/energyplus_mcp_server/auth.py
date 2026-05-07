"""Bearer-token authentication for streamable-http transport.

EnergyPlus Model Context Protocol Server (EnergyPlus-MCP)
Copyright (c) 2025, The Regents of the University of California,
through Lawrence Berkeley National Laboratory (subject to receipt of
any required approvals from the U.S. Dept. of Energy). All rights reserved.
"""
from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Optional

logger = logging.getLogger(__name__)

# Per-request token label propagation. Set by AuthMiddleware after a successful
# token lookup; read by path-resolution helpers to scope user file I/O.
# Stdio mode never sets this — default None, helpers fall back to unscoped paths.
_token_label: ContextVar[Optional[str]] = ContextVar("mcp_token_label", default=None)


def current_token_label() -> Optional[str]:
    """Return the token label for the current request, or None if unset."""
    return _token_label.get()


from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402


class AuthMiddleware(BaseHTTPMiddleware):
    """Bearer-token middleware that bypasses /health and stamps _token_label."""

    BYPASS_PATHS = frozenset({"/health"})

    def __init__(self, app, tokens: dict):
        """tokens: dict mapping raw token string → human label."""
        super().__init__(app)
        self._tokens = tokens

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.BYPASS_PATHS:
            return await call_next(request)

        header = request.headers.get("authorization", "")
        if not header:
            logger.info("auth.fail reason=missing_header path=%s", request.url.path)
            return _unauthorized()

        if not header.startswith("Bearer "):
            logger.info("auth.fail reason=malformed_header path=%s", request.url.path)
            return _unauthorized()

        token = header[len("Bearer "):]
        label = self._tokens.get(token)
        if label is None:
            logger.info("auth.fail reason=unknown_token path=%s", request.url.path)
            return _unauthorized()

        ctx_token = _token_label.set(label)
        try:
            logger.info("auth.success label=%s path=%s", label, request.url.path)
            return await call_next(request)
        finally:
            _token_label.reset(ctx_token)


def _unauthorized() -> JSONResponse:
    return JSONResponse({"error": "authentication required"}, status_code=401)
