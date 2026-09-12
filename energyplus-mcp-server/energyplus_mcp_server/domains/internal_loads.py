from typing import Any, Dict, List, Optional, Literal
import json
import logging
from hashlib import sha256
from pathlib import Path

from eppy.modeleditor import IDF

from ..utils import coupled_occupancy

logger = logging.getLogger(__name__)


PARAMETERS = ("LPD", "EPD", "OCD")


def _require_owned_parameter(parameter: Optional[str]) -> str:
    normalized = parameter.strip().upper() if isinstance(parameter, str) else ""
    if normalized not in PARAMETERS:
        raise ValueError(
            "internal_load_manager supports semantic parameters: " + ", ".join(PARAMETERS)
        )
    return normalized


def _tag_parameter_response(payload: Dict[str, Any], action: str) -> Dict[str, Any]:
    result = dict(payload)
    result["tool"] = "internal_load_manager"
    result["manager"] = "internal_load_manager"
    result["action"] = action
    return result


def _parameter_capabilities(ep_manager: Any, idf_path: Optional[str]) -> Dict[str, Any]:
    payload = ep_manager.parameter_capabilities(idf_path, list(PARAMETERS))
    result = _tag_parameter_response(payload, "parameter_capabilities")
    for detail in result.get("parameters", {}).values():
        detail["tool"] = "internal_load_manager"
        detail["manager"] = "internal_load_manager"
        detail["action"] = "adjust_percentage"
        detail["absolute_set"]["tool"] = "internal_load_manager"
        detail["absolute_set"]["manager"] = "internal_load_manager"
        detail["absolute_set"]["action"] = "set_parameter"
    if idf_path and hasattr(ep_manager, "_resolve_idf_path"):
        resolved = ep_manager._resolve_idf_path(idf_path)
        ep_manager._assert_simulation_version_matches(resolved)
        detail = coupled_occupancy.capabilities(IDF(resolved))
        detail.update({
            "parameter": "coupled_occupancy",
            "tool": "internal_load_manager",
            "manager": "internal_load_manager",
            "action": "set_occupancy_ratio",
            "capability_action": "parameter_capabilities",
            "inspect_action": "inspect_coupled_occupancy",
            "required_args": ["idf_path", "value", "output_path"],
            "returns": ["output_file", "before", "after", "changes", "skipped", "ambiguous"],
            "operations": ["set_occupancy_ratio"],
            "units": "fraction",
            "value_semantics": "absolute coupled occupancy ratio",
            "minimum_value": 0.5,
            "minimum_inclusive": True,
            "maximum_value": 1.0,
            "maximum_inclusive": True,
            "applicable_field_count": len(detail.get("applicable_targets", [])),
            "affected_semantics": ["people", "lighting", "electric_equipment"],
            "input_file": resolved,
            "input_sha256": sha256(Path(resolved).read_bytes()).hexdigest(),
        })
    else:
        detail = {
            "parameter": "coupled_occupancy",
            "operation": "set_occupancy_ratio",
            "tool": "internal_load_manager",
            "manager": "internal_load_manager",
            "action": "set_occupancy_ratio",
            "capability_action": "parameter_capabilities",
            "inspect_action": "inspect_coupled_occupancy",
            "coverage": "unverified",
            "supported": False,
            "required_args": ["idf_path", "value", "output_path"],
            "returns": ["output_file", "before", "after", "changes", "skipped", "ambiguous"],
            "operations": ["set_occupancy_ratio"],
            "units": "fraction",
            "value_semantics": "absolute coupled occupancy ratio",
            "minimum_value": 0.5,
            "minimum_inclusive": True,
            "maximum_value": 1.0,
            "maximum_inclusive": True,
            "applicable_field_count": 0,
            "affected_semantics": ["people", "lighting", "electric_equipment"],
        }
    result.setdefault("parameters", {})["coupled_occupancy"] = detail
    return result


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    logger.info("domains.internal_loads.register starting")
    @mcp.tool()
    async def internal_load_manager(
        action: Literal[
            "inspect", "modify", "capabilities", "parameter_capabilities",
            "inspect_parameter", "adjust_percentage", "set_parameter",
            "coupled_occupancy_capabilities", "inspect_coupled_occupancy",
            "set_occupancy_ratio",
        ],
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
        # Semantic parameter operations
        parameter: Optional[str] = None,
        value: Optional[float] = None,
        target_ids: Optional[List[str]] = None,
        assignments: Optional[Dict[str, float]] = None,
        expected_model_sha256: Optional[str] = None,
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
                        {"name": "parameter_capabilities", "required": [], "optional": ["idf_path"]},
                        {"name": "inspect_parameter", "required": ["idf_path", "parameter"]},
                        {"name": "adjust_percentage", "required": ["idf_path", "parameter", "value", "output_path"], "optional": ["expected_model_sha256"]},
                        {"name": "set_parameter", "required": ["idf_path", "parameter", "output_path"], "optional": ["value", "target_ids", "assignments", "expected_model_sha256"]},
                        {"name": "coupled_occupancy_capabilities", "required": [], "optional": ["idf_path"]},
                        {"name": "inspect_coupled_occupancy", "required": ["idf_path"]},
                        {"name": "set_occupancy_ratio", "required": ["idf_path", "value", "output_path"], "optional": ["mode", "expected_model_sha256"]},
                    ],
                    "ops": [
                        {"op": "people.update", "params": {"modifications": [{"target": "all", "field_updates": {"Number_of_People": 10}}]}},
                        {"op": "lights.update", "params": {"modifications": [{"target": "all", "field_updates": {"Watts_per_Floor_Area": 10.0}}]}},
                        {"op": "electric_equipment.update", "params": {"modifications": [{"target": "all", "field_updates": {"Design_Level": 500}}]}},
                    ],
                }, indent=2)

            if action == "parameter_capabilities":
                return json.dumps(_parameter_capabilities(ep_manager, idf_path), indent=2)

            if not idf_path:
                return "Missing required parameter: idf_path"

            if action in {"coupled_occupancy_capabilities", "inspect_coupled_occupancy", "set_occupancy_ratio"}:
                resolved = ep_manager._resolve_idf_path(idf_path)
                ep_manager._assert_simulation_version_matches(resolved)
                idf = IDF(resolved)
                if action == "coupled_occupancy_capabilities":
                    payload = coupled_occupancy.capabilities(idf)
                    payload.update({
                        "input_file": resolved,
                        "input_sha256": sha256(Path(resolved).read_bytes()).hexdigest(),
                        "mode": "inspect",
                    })
                elif action == "inspect_coupled_occupancy":
                    payload = coupled_occupancy.inspect(idf)
                    payload.update({
                        "input_file": resolved,
                        "input_sha256": sha256(Path(resolved).read_bytes()).hexdigest(),
                        "mode": "inspect",
                    })
                else:
                    if value is None or not output_path:
                        return json.dumps({"success": False, "error": "set_occupancy_ratio requires value and output_path"})
                    payload = coupled_occupancy.execute(
                        idf,
                        input_path=resolved,
                        output_path=output_path,
                        ratio=value,
                        mode=mode,
                        expected_model_sha256=expected_model_sha256,
                    )
                return json.dumps(_tag_parameter_response(payload, action), indent=2)

            if action == "inspect_parameter":
                normalized = _require_owned_parameter(parameter)
                return json.dumps(_tag_parameter_response(
                    ep_manager.inspect_parameter(idf_path, normalized), action
                ), indent=2)

            if action == "adjust_percentage":
                normalized = _require_owned_parameter(parameter)
                if value is None or not output_path:
                    return json.dumps({"error": "Missing required parameters: idf_path, parameter, value, output_path"})
                return json.dumps(_tag_parameter_response(
                    ep_manager.adjust_parameter_percentage(
                        idf_path, normalized, value, output_path, expected_model_sha256, mode
                    ), action
                ), indent=2)

            if action == "set_parameter":
                normalized = _require_owned_parameter(parameter)
                if not output_path or (value is None and assignments is None):
                    return json.dumps({"error": "Missing required parameters: idf_path, parameter, value or assignments, output_path"})
                return json.dumps(_tag_parameter_response(
                    ep_manager.set_parameter(
                        idf_path, normalized, value, output_path, target_ids,
                        assignments, expected_model_sha256, mode,
                    ), action
                ), indent=2)

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
