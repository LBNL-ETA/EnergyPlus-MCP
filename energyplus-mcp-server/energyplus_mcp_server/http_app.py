"""HTTP app assembly for streamable-http transport.

Wraps FastMCP's underlying Starlette app with:
- A no-auth GET /health endpoint
- /files/... routes for one-time upload and download links (file_routes.py)
- AuthMiddleware that validates bearer tokens

EnergyPlus Model Context Protocol Server (EnergyPlus-MCP)
Copyright (c) 2025, The Regents of the University of California,
through Lawrence Berkeley National Laboratory (subject to receipt of
any required approvals from the U.S. Dept. of Energy). All rights reserved.
"""
from __future__ import annotations

import contextlib
import logging

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from energyplus_mcp_server.auth import AuthMiddleware
from energyplus_mcp_server.config import Config
from energyplus_mcp_server.file_routes import file_routes

logger = logging.getLogger(__name__)


async def _health(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def build_app(mcp: FastMCP, config: Config) -> Starlette:
    """Compose FastMCP's streamable-http app with /health and auth middleware.

    The resulting app exposes:
      GET  /health   → 200, no auth (Cloud Run probe + manual liveness check)
      /files/...     → one-time upload/download links; the code in the URL is
                       the credential, so no bearer token
      POST /mcp      → FastMCP, behind AuthMiddleware
    """
    # FastMCP exposes its Starlette app via .streamable_http_app() in mcp>=1.8.
    # If your installed mcp version uses a different accessor, adapt here.
    inner = mcp.streamable_http_app()

    # Mounting `inner` at `/` does NOT propagate its lifespan, so we wire
    # FastMCP's session_manager.run() into the outer app's lifespan ourselves.
    # Without this, _task_group stays None and any authenticated POST /mcp
    # raises RuntimeError on first request.
    @contextlib.asynccontextmanager
    async def _lifespan(_app: Starlette):
        async with mcp.session_manager.run():
            yield

    app = Starlette(
        routes=[
            Route("/health", _health, methods=["GET"]),
            *file_routes(),
            Mount("/", app=inner),  # everything else routes into FastMCP
        ],
        lifespan=_lifespan,
    )
    app.add_middleware(AuthMiddleware, tokens=config.auth.tokens)
    logger.info(
        "http_app built: /health (open) + /files (one-time links) + /mcp (auth) with %d token(s)",
        len(config.auth.tokens),
    )
    return app
