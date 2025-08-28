from typing import Any, Dict, Optional, Literal
import json


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    @mcp.tool()
    async def simulation_manager(
        action: Literal["run", "update_settings", "update_run_period", "status", "capabilities"],
        idf_path: Optional[str] = None,
        weather_file: Optional[str] = None,
        output_directory: Optional[str] = None,
        annual: bool = True,
        design_day: bool = False,
        readvars: bool = True,
        expandobjects: bool = True,
        settings: Optional[Dict[str, Any]] = None,
        run_period: Optional[Dict[str, Any]] = None,
        run_period_index: int = 0,
        run_id: Optional[str] = None,
        detail: Literal["summary", "detailed"] = "summary",
    ) -> str:
        if action == "capabilities":
            return json.dumps({
                "tool": "simulation_manager",
                "actions": [
                    {"name": "run", "required": ["idf_path"], "optional": ["weather_file", "output_directory", "annual", "design_day", "readvars", "expandobjects"]},
                    {"name": "update_settings", "required": ["idf_path", "settings"]},
                    {"name": "update_run_period", "required": ["idf_path", "run_period"], "optional": ["run_period_index"]},
                    {"name": "status", "optional": ["run_id"]},
                ],
                "detail": detail,
            }, indent=2)
        if action == "run":
            if not idf_path:
                return "Missing required parameter: idf_path"
            result = ep_manager.run_simulation(idf_path, weather_file, output_directory, annual, design_day, readvars, expandobjects)
            return f"Simulation run complete:\n{result}"
        if action == "update_settings":
            if not idf_path or not isinstance(settings, dict) or not settings:
                return "Missing required parameters: idf_path, settings"
            result = ep_manager.modify_simulation_settings(idf_path=idf_path, object_type="SimulationControl", field_updates=settings, output_path=None)
            return f"SimulationControl updated:\n{result}"
        if action == "update_run_period":
            if not idf_path or not isinstance(run_period, dict) or not run_period:
                return "Missing required parameters: idf_path, run_period"
            result = ep_manager.modify_simulation_settings(idf_path=idf_path, object_type="RunPeriod", field_updates=run_period, run_period_index=int(run_period_index or 0), output_path=None)
            return f"RunPeriod updated:\n{result}"
        if action == "status":
            return json.dumps({"run_id": run_id or None, "mode": "synchronous", "queueing": False}, indent=2)
        return f"Unsupported action: {action}"

