from typing import Any, Dict, List, Optional, Literal
import json
import logging

logger = logging.getLogger(__name__)


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    logger.info("domains.internal_loads.register starting")
    @mcp.tool()
    async def internal_load_manager(
        action: Literal["inspect", "modify", "capabilities"],
        idf_path: Optional[str] = None,
        # Inspect
        focus: Literal["people", "lights", "electric_equipment", "all"] = "all",
        # Modify
        op: Optional[Literal[
            "people.update",
            "lights.update",
            "electric_equipment.update",
        ]] = None,
        modifications: Optional[List[Dict[str, Any]]] = None,
        output_path: Optional[str] = None,
        mode: Literal["apply", "dry_run"] = "apply",
    ) -> str:
        """
        Internal loads domain manager.

        - inspect: people/lights/electric_equipment
        - modify: update target objects with field_updates
        - capabilities: describe supported actions
        """
        try:
            if action == "capabilities":
                return json.dumps({
                    "tool": "internal_load_manager",
                    "actions": [
                        {"name": "inspect", "required": ["idf_path"], "optional": ["focus"]},
                        {"name": "modify", "required": ["idf_path", "op", "modifications"], "optional": ["output_path", "mode"]},
                    ],
                    "ops": [
                        {"op": "people.update", "params": {"modifications": [{"target": "all", "field_updates": {"Number_of_People": 10}}]}},
                        {"op": "lights.update", "params": {"modifications": [{"target": "all", "field_updates": {"Watts_per_Floor_Area": 10.0}}]}},
                        {"op": "electric_equipment.update", "params": {"modifications": [{"target": "all", "field_updates": {"Design_Level": 500}}]}},
                    ],
                }, indent=2)

            if not idf_path:
                return "Missing required parameter: idf_path"

            if action == "inspect":
                payload: Dict[str, Any] = {"focus": focus}
                if focus in ("people", "all"):
                    payload["people"] = ep_manager.inspect_people(idf_path)
                if focus in ("lights", "all"):
                    payload["lights"] = ep_manager.inspect_lights(idf_path)
                if focus in ("electric_equipment", "all"):
                    payload["electric_equipment"] = ep_manager.inspect_electric_equipment(idf_path)
                return json.dumps(payload, indent=2)

            if action == "modify":
                if mode == "dry_run":
                    return json.dumps({
                        "mode": mode,
                        "plan": {"op": op, "count": len(modifications or [])}
                    }, indent=2)
                mods = modifications or []
                if op == "people.update":
                    return ep_manager.modify_people(idf_path, mods, output_path)
                if op == "lights.update":
                    return ep_manager.modify_lights(idf_path, mods, output_path)
                if op == "electric_equipment.update":
                    return ep_manager.modify_electric_equipment(idf_path, mods, output_path)
                return f"Unsupported op: {op}"

            return f"Unsupported action: {action}"
        except FileNotFoundError as e:
            logger.warning(f"Internal-loads file not found: {str(e)}")
            return f"File not found: {str(e)}"
        except Exception as e:
            logger.error(f"internal_load_manager error: {str(e)}")
            return f"Error in internal_load_manager: {str(e)}"
    logger.info("domains.internal_loads.register complete: internal_load_manager available")


# --- Reusable domain helpers (importable by orchestrators) ---
def inspect_internal_loads_data(ep_manager: Any, idf_path: str, focus: str | list[str] = "all") -> Dict[str, Any]:
    """Return internal-loads inspection data keyed by section names.

    focus: "people" | "lights" | "electric_equipment" | "all" | list of these
    Values are whatever `ep_manager` returns (usually JSON strings).
    """
    if isinstance(focus, str):
        focus_list = [focus] if focus != "all" else ["people", "lights", "electric_equipment"]
    else:
        focus_list = focus
    out: Dict[str, Any] = {}
    if "people" in focus_list:
        out["people"] = ep_manager.inspect_people(idf_path)
    if "lights" in focus_list:
        out["lights"] = ep_manager.inspect_lights(idf_path)
    if "electric_equipment" in focus_list:
        out["electric_equipment"] = ep_manager.inspect_electric_equipment(idf_path)
    return out

def modify_internal_loads(ep_manager: Any, idf_path: str, op: str, modifications: Optional[List[Dict[str, Any]]], output_path: Optional[str]) -> str:
    mods = modifications or []
    if op == "people.update":
        return ep_manager.modify_people(idf_path, mods, output_path)
    if op == "lights.update":
        return ep_manager.modify_lights(idf_path, mods, output_path)
    if op == "electric_equipment.update":
        return ep_manager.modify_electric_equipment(idf_path, mods, output_path)
    raise ValueError(f"Unsupported internal-loads op: {op}")
