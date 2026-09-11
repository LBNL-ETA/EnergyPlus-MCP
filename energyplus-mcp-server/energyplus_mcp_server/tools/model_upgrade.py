"""MCP entry point for local, copy-only EnergyPlus IDF transitions."""

import asyncio
import json
from typing import Any, Literal, Optional

from energyplus_mcp_server.utils.model_upgrade import ModelUpgrade


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    upgrade = ModelUpgrade(config)

    @mcp.tool()
    async def model_upgrade(
        action: Literal["plan", "run"],
        idf_path: str,
        target_version: Optional[str] = None,
        output_directory: Optional[str] = None,
    ) -> str:
        """Plan or copy-upgrade one IDF with official local transition tools.

        ``plan`` only reads the source model and configured local transition
        directory. It reports the complete adjacent chain and every required
        executable, IDD, and report-variable mapping before any file is
        created. ``run`` requires a new ``output_directory`` for an upgrade;
        it stages copies there and does not simulate, adopt calibration state,
        or validate simulation results. If versions already match, ``run`` is
        an explicit no-op and writes no files.
        """
        if not idf_path:
            return json.dumps(
                {
                    "tool": "model_upgrade",
                    "action": action,
                    "status": "refused",
                    "simulation_validated": False,
                    "issues": ["idf_path is required"],
                },
                indent=2,
            )
        if action not in {"plan", "run"}:
            return json.dumps(
                {
                    "tool": "model_upgrade",
                    "action": action,
                    "status": "refused",
                    "simulation_validated": False,
                    "issues": ["action must be 'plan' or 'run'"],
                },
                indent=2,
            )
        if action == "plan":
            result = await asyncio.to_thread(upgrade.plan, idf_path, target_version)
        else:
            result = await asyncio.to_thread(upgrade.run, idf_path, target_version, output_directory)
        return json.dumps(result, indent=2)
