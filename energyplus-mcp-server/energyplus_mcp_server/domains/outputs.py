from typing import Any, Dict, Optional, Literal, List
import json
import logging

logger = logging.getLogger(__name__)


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    logger.info("domains.outputs.register starting")

    @mcp.tool()
    async def outputs_manager(
        action: Literal["list", "add_variables", "add_meters", "capabilities"],
        idf_path: Optional[str] = None,
        type: Literal["variables", "meters", "both"] = "variables",
        discover_available: bool = False,
        run_days: int = 1,
        variables: Optional[List] = None,
        meters: Optional[List] = None,
        validation_level: str = "moderate",
        allow_duplicates: bool = False,
        output_path: Optional[str] = None,
    ) -> str:
        """
        Outputs domain manager.

        - list: list variables/meters (or both); can optionally discover via short sim
        - add_variables: add Output:Variable entries
        - add_meters: add Output:Meter entries
        - capabilities: enumerate actions
        """
        try:
            if action == "capabilities":
                return json.dumps({
                    "tool": "outputs_manager",
                    "actions": [
                        {"name": "list", "required": ["idf_path"], "optional": ["type", "discover_available", "run_days"]},
                        {"name": "add_variables", "required": ["idf_path", "variables"], "optional": ["validation_level", "allow_duplicates", "output_path"]},
                        {"name": "add_meters", "required": ["idf_path", "meters"], "optional": ["validation_level", "allow_duplicates", "output_path"]},
                    ]
                }, indent=2)

            if not idf_path and action != "capabilities":
                return "Missing required parameter: idf_path"

            if action == "list":
                payload: Dict[str, Any] = {}
                kind = type.lower()
                if kind not in ("variables", "meters", "both"):
                    return json.dumps({"error": "Invalid type", "allowed": ["variables", "meters", "both"]}, indent=2)
                if kind in ("variables", "both"):
                    try:
                        payload["variables"] = ep_manager.get_output_variables(idf_path, discover_available, run_days)
                    except Exception as e:
                        payload.setdefault("errors", {})["variables"] = str(e)
                if kind in ("meters", "both"):
                    try:
                        payload["meters"] = ep_manager.get_output_meters(idf_path, discover_available, run_days)
                    except Exception as e:
                        payload.setdefault("errors", {})["meters"] = str(e)
                return json.dumps({"idf_path": idf_path, **payload}, indent=2)

            if action == "add_variables":
                return ep_manager.add_output_variables(idf_path, variables or [], validation_level, allow_duplicates, output_path)

            if action == "add_meters":
                return ep_manager.add_output_meters(idf_path, meters or [], validation_level, allow_duplicates, output_path)

            return f"Unsupported action: {action}"
        except FileNotFoundError as e:
            logger.warning(f"Outputs file not found: {str(e)}")
            return f"File not found: {str(e)}"
        except Exception as e:
            logger.error(f"outputs_manager error: {str(e)}")
            return f"Error in outputs_manager: {str(e)}"


# --- Reusable domain helpers ---
def outputs_list(ep_manager: Any, idf_path: str, type: str, discover_available: bool, run_days: int) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    kind = (type or "variables").lower()
    if kind not in ("variables", "meters", "both"):
        return {"error": "Invalid type", "allowed": ["variables", "meters", "both"]}
    if kind in ("variables", "both"):
        try:
            payload["variables"] = ep_manager.get_output_variables(idf_path, discover_available, run_days)
        except Exception as e:
            payload.setdefault("errors", {})["variables"] = str(e)
    if kind in ("meters", "both"):
        try:
            payload["meters"] = ep_manager.get_output_meters(idf_path, discover_available, run_days)
        except Exception as e:
            payload.setdefault("errors", {})["meters"] = str(e)
    return payload

