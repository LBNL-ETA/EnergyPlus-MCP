"""
EnergyPlus MCP Server bootstrap

This module boots FastMCP, reads tool-surface configuration (config.yaml or env),
and registers tool groups via submodules:
  - energyplus_mcp_server.tools.*  (master/unified tools)
  - energyplus_mcp_server.domains.* (domain manager tools)

All MCP tool implementations live in the modules above to keep this file lean.
"""

import os
import logging
from pathlib import Path
from datetime import datetime

from mcp.server.fastmcp import FastMCP

from energyplus_mcp_server.energyplus_tools import EnergyPlusManager
from energyplus_mcp_server.config import get_config
from energyplus_mcp_server.tool_surface import load_tool_surface, register_tool_surface

logger = logging.getLogger(__name__)

# Initialize configuration
config = get_config()


_surface_path = os.getenv("MCP_CONFIG_PATH") or str(Path(config.paths.workspace_root) / "config.yaml")
tool_surface_cfg = load_tool_surface(_surface_path)
logger.info("Loaded tool surface from %s: %s", _surface_path, tool_surface_cfg)

# Initialize FastMCP server.
#
# DNS rebinding protection (in mcp>=1.10) defaults to allowed_hosts=[], which
# makes the SDK reject ANY Host header with 421 "Invalid Host header". That's
# correct for browser-attack scenarios but unnecessary when bearer-token auth
# is enforced on every non-/health request.
#
# Behavior:
#   - MCP_ALLOWED_HOSTS unset (default) -> disable DNS rebinding check
#     (suitable for HTTP behind our AuthMiddleware, or stdio).
#   - MCP_ALLOWED_HOSTS="host1,host2"   -> keep check on with that allowlist.
_allowed_hosts_env = os.getenv("MCP_ALLOWED_HOSTS", "").strip()
if _allowed_hosts_env:
    from mcp.server.transport_security import TransportSecuritySettings
    _transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[h.strip() for h in _allowed_hosts_env.split(",") if h.strip()],
    )
    logger.info(
        "DNS rebinding protection ENABLED, allowed_hosts=%s",
        _transport_security.allowed_hosts,
    )
else:
    try:
        from mcp.server.transport_security import TransportSecuritySettings
        _transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
        logger.info("DNS rebinding protection DISABLED (MCP_ALLOWED_HOSTS unset)")
    except ImportError:
        # mcp<1.10 has no transport_security module; behavior was equivalent
        # to disabled-protection (no host check existed). Pass nothing.
        _transport_security = None

_mcp_kwargs: dict = {}
if _transport_security is not None:
    _mcp_kwargs["transport_security"] = _transport_security
# Hosts such as Claude Code place server instructions in the agent's context,
# so this is where agents learn that workflow skills exist.
SERVER_INSTRUCTIONS = (
    "EnergyPlus-MCP inspects, edits, and simulates native EnergyPlus IDF models. "
    "Prefer the domain managers for semantic changes; use idf_modification only "
    "when no domain operation fits. Step-by-step guides are available: call "
    "list_skills before a multi-step task you have not done with this server, "
    "and get_skill('learn-from-examples') before adding an object type you have "
    "not modelled, which uses example_library to read EnergyPlus's shipped "
    "example models and DataSets."
)
mcp = FastMCP(config.server.name, instructions=SERVER_INSTRUCTIONS, **_mcp_kwargs)

# Initialize EnergyPlus manager
ep_manager = EnergyPlusManager(config)

logger.info(f"EnergyPlus MCP Server '{config.server.name}' v{config.server.version} initialized")
STARTUP_TIME = datetime.utcnow()

registered_tools = register_tool_surface(mcp, ep_manager, config, tool_surface_cfg)
from energyplus_mcp_server.tools import server as tools_server

tools_server.STARTUP_TIME = STARTUP_TIME
logger.info("Registered %d MCP tools: %s", len(registered_tools), sorted(registered_tools))


if __name__ == "__main__":
    logger.info(f"Starting {config.server.name} v{config.server.version}")
    logger.info(f"EnergyPlus version: {config.energyplus.version}")
    logger.info(f"Sample files path: {config.paths.sample_files_path}")
    logger.info(f"Transport: {config.transport.transport}")

    try:
        if config.transport.transport == "stdio":
            mcp.run(transport="stdio")
        elif config.transport.transport == "streamable-http":
            import uvicorn
            from energyplus_mcp_server.http_app import build_app

            app = build_app(mcp, config)
            logger.info(
                "Listening on http://%s:%d (path=%s, %d tokens)",
                config.transport.http_host,
                config.transport.http_port,
                config.transport.http_path,
                len(config.auth.tokens),
            )
            uvicorn.run(
                app,
                host=config.transport.http_host,
                port=config.transport.http_port,
                log_level=config.server.log_level.lower(),
            )
        else:
            raise RuntimeError(
                f"Unknown transport: {config.transport.transport!r} "
                f"(should have been caught at config load)"
            )
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
        raise
    finally:
        logger.info("Server stopped")
