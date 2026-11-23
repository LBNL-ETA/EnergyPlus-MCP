from typing import Any, Dict
import json
import logging

logger = logging.getLogger(__name__)


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    @mcp.tool()
    async def get_outputs(
        idf_path: str,
        type: str = "variables",
        discover_available: bool = False,
        run_days: int = 1,
    ) -> str:
        try:
            kind = (type or "variables").lower()
            if kind not in ("variables", "meters", "both"):
                return json.dumps({"error": "Invalid type", "allowed": ["variables", "meters", "both"]}, indent=2)
            payload: Dict[str, Any] = {}
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
        except FileNotFoundError as e:
            return f"File not found: {str(e)}"
        except Exception as e:
            return f"Error getting outputs for {idf_path}: {str(e)}"

