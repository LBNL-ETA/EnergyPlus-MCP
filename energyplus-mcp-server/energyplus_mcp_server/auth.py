"""Bearer-token authentication for streamable-http transport.

EnergyPlus Model Context Protocol Server (EnergyPlus-MCP)
Copyright (c) 2025, The Regents of the University of California,
through Lawrence Berkeley National Laboratory (subject to receipt of
any required approvals from the U.S. Dept. of Energy). All rights reserved.
"""
from __future__ import annotations

import hmac
import logging
from collections import OrderedDict
from contextvars import ContextVar
from typing import Optional

logger = logging.getLogger(__name__)

# Key under request.state (i.e. scope["state"]) where AuthMiddleware stores the
# authenticated token label. Tool handlers read it back through the MCP request
# context (see energyplus_mcp_server.scope): with streamable-http they run in the
# session's task, whose ContextVars were copied from the session's first request.
REQUEST_STATE_LABEL_KEY = "mcp_token_label"

# Per-request token label for code that runs in the HTTP request's own task
# (and for tests). Stdio mode never sets this — default None.
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
    SESSION_HEADER = "mcp-session-id"
    MAX_TRACKED_SESSIONS = 10_000

    def __init__(self, app, tokens: dict):
        """tokens: dict mapping raw token string → human label."""
        super().__init__(app)
        self._tokens = tokens
        # MCP session id → label of the token that created it. A session may
        # only be used by the identity that opened it.
        self._session_owner: "OrderedDict[str, str]" = OrderedDict()

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
        label = _lookup_label(self._tokens, token)
        if label is None:
            logger.info("auth.fail reason=unknown_token path=%s", request.url.path)
            return _unauthorized()

        session_id = request.headers.get(self.SESSION_HEADER)
        if session_id:
            owner = self._session_owner.get(session_id)
            if owner is not None and owner != label:
                logger.warning(
                    "auth.fail reason=session_owner_mismatch label=%s path=%s",
                    label, request.url.path,
                )
                return JSONResponse(
                    {"error": "session belongs to a different token"}, status_code=403
                )

        setattr(request.state, REQUEST_STATE_LABEL_KEY, label)
        ctx_token = _token_label.set(label)
        try:
            logger.info("auth.success label=%s path=%s", label, request.url.path)
            response = await call_next(request)
        finally:
            _token_label.reset(ctx_token)

        new_session_id = response.headers.get(self.SESSION_HEADER)
        if new_session_id and new_session_id not in self._session_owner:
            self._session_owner[new_session_id] = label
            while len(self._session_owner) > self.MAX_TRACKED_SESSIONS:
                self._session_owner.popitem(last=False)
        if request.method == "DELETE" and session_id:
            self._session_owner.pop(session_id, None)
        return response


def _lookup_label(tokens: dict, presented: str) -> Optional[str]:
    """Constant-time token lookup: compare against every configured token."""
    presented_b = presented.encode()
    match = None
    for token, label in tokens.items():
        if hmac.compare_digest(token.encode(), presented_b):
            match = label
    return match


def _unauthorized() -> JSONResponse:
    return JSONResponse({"error": "authentication required"}, status_code=401)
