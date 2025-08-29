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
from typing import Any, Dict
from pathlib import Path
from datetime import datetime

from mcp.server.fastmcp import FastMCP

from energyplus_mcp_server.energyplus_tools import EnergyPlusManager
from energyplus_mcp_server.config import get_config
from energyplus_mcp_server.domains import register_all as register_domain_managers
from energyplus_mcp_server.tools import register_all as register_master_tools

logger = logging.getLogger(__name__)

# Initialize configuration
config = get_config()


def _load_tool_surface_config() -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "mode": None,
        "enable_wrappers": None,
        "domains": {"envelope": None, "internal_loads": None, "hvac": None, "outputs": None},
    }
    path = os.getenv("MCP_CONFIG_PATH") or str(Path(config.paths.workspace_root) / "config.yaml")
    try:
        import yaml  # type: ignore
        if os.path.exists(path):
            with open(path, "r") as f:
                data = yaml.safe_load(f) or {}
            ts = (data or {}).get("tool_surface", {})
            cfg["mode"] = ts.get("mode")
            cfg["enable_wrappers"] = ts.get("enable_wrappers")
            doms = ts.get("domains", {}) or {}
            for k in cfg["domains"].keys():
                cfg["domains"][k] = doms.get(k)
            logger.info(f"Loaded tool_surface config from {path}: {cfg}")
        else:
            logger.info(f"Tool surface config not found at {path}; using defaults/env flags")
    except Exception as e:
        logger.info(f"YAML not available or failed to parse ({e}); using defaults/env flags")
    return cfg


tool_surface_cfg = _load_tool_surface_config()

# Initialize FastMCP server
mcp = FastMCP(config.server.name)

# Defaults (env flags as secondary control)
EXPOSE_DOMAIN_MANAGERS = os.getenv("MCP_EXPOSE_DOMAIN_MANAGERS", "false").lower() in ("1", "true", "yes")
EXPOSE_MASTERS = os.getenv("MCP_EXPOSE_MASTERS", "true").lower() in ("1", "true", "yes")


def _apply_tool_surface_overrides() -> None:
    global EXPOSE_DOMAIN_MANAGERS, EXPOSE_MASTERS
    mode = (tool_surface_cfg.get("mode") or "").lower()
    if mode in ("masters", "domains", "hybrid"):
        EXPOSE_MASTERS = mode in ("masters", "hybrid")
        EXPOSE_DOMAIN_MANAGERS = mode in ("domains", "hybrid")
        logger.info(f"Tool surface mode='{mode}' => masters={EXPOSE_MASTERS}, domains={EXPOSE_DOMAIN_MANAGERS}")


_apply_tool_surface_overrides()

# Initialize EnergyPlus manager
ep_manager = EnergyPlusManager(config)

logger.info(f"EnergyPlus MCP Server '{config.server.name}' v{config.server.version} initialized")
STARTUP_TIME = datetime.utcnow()

logger.info("EXPOSE_DOMAIN_MANAGERS=%s EXPOSE_MASTERS=%s", EXPOSE_DOMAIN_MANAGERS, EXPOSE_MASTERS)

if EXPOSE_DOMAIN_MANAGERS:
    doms = tool_surface_cfg.get("domains") or {}
    register_domain_managers(
        mcp,
        ep_manager,
        config,
        envelope=True if doms.get("envelope") is None else bool(doms.get("envelope")),
        internal_loads=True if doms.get("internal_loads") is None else bool(doms.get("internal_loads")),
        hvac=True if doms.get("hvac") is None else bool(doms.get("hvac")),
        outputs=True if doms.get("outputs") else False,
    )
    logger.info("Domain manager tools registered")
else:
    logger.info("Domain manager tools not registered (flag disabled)")

if EXPOSE_MASTERS:
    register_master_tools(mcp, ep_manager, config)
    logger.info("Master tools registered via tools/ submodules")

# Always register the server management tool regardless of mode
try:
    from energyplus_mcp_server.tools import server as tools_server
    tools_server.register(mcp, ep_manager, config)
    # Provide STARTUP_TIME to tools.server for uptime reporting
    tools_server.STARTUP_TIME = STARTUP_TIME
    logger.info("Server management tool registered (always-on)")
except Exception as e:
    logger.error(f"Failed to register server management tool: {e}")

# Always register core functional tools regardless of mode
for _mod_name, _label in (
    ("preflight", "model_preflight"),
    ("simulation", "simulation_manager"),
    ("files", "file_utils"),
    ("post", "post_processing"),
):
    try:
        _mod = __import__(f"energyplus_mcp_server.tools.{_mod_name}", fromlist=["register"])  # type: ignore
        _mod.register(mcp, ep_manager, config)  # type: ignore
        logger.info(f"Core tool registered (always-on): {_label}")
    except Exception as e:
        logger.error(f"Failed to register core tool '{_label}': {e}")


if __name__ == "__main__":
    logger.info(f"Starting {config.server.name} v{config.server.version}")
    logger.info(f"EnergyPlus version: {config.energyplus.version}")
    logger.info(f"Sample files path: {config.paths.sample_files_path}")

    try:
        mcp.run(transport="stdio")
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    except Exception as e:
        logger.error(f"Server error: {str(e)}")
        raise
    finally:
        logger.info("Server stopped")
