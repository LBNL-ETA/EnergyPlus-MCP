from typing import Any, Dict, List, Optional, Literal
import json
import logging

logger = logging.getLogger(__name__)


PARAMETERS = ("COP", "HE", "FAN")


def _require_owned_parameter(parameter: Optional[str]) -> str:
    normalized = parameter.strip().upper() if isinstance(parameter, str) else ""
    if normalized not in PARAMETERS:
        raise ValueError(
            "hvac_manager supports semantic parameters: " + ", ".join(PARAMETERS)
        )
    return normalized


def _tag_parameter_response(payload: Dict[str, Any], action: str) -> Dict[str, Any]:
    result = dict(payload)
    result["tool"] = "hvac_manager"
    result["manager"] = "hvac_manager"
    result["action"] = action
    return result


def _parameter_capabilities(ep_manager: Any, idf_path: Optional[str]) -> Dict[str, Any]:
    payload = ep_manager.parameter_capabilities(idf_path, list(PARAMETERS))
    result = _tag_parameter_response(payload, "parameter_capabilities")
    for detail in result.get("parameters", {}).values():
        detail["tool"] = "hvac_manager"
        detail["manager"] = "hvac_manager"
        detail["action"] = "adjust_percentage"
        detail["absolute_set"]["tool"] = "hvac_manager"
        detail["absolute_set"]["manager"] = "hvac_manager"
        detail["absolute_set"]["action"] = "set_parameter"
    return result


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    logger.info("domains.hvac.register starting")
    @mcp.tool()
    async def hvac_manager(
        action: Literal[
            "discover", "topology", "visualize", "capabilities",
            "parameter_capabilities", "inspect_parameter", "adjust_percentage", "set_parameter",
        ],
        idf_path: Optional[str] = None,
        loop_name: Optional[str] = None,
        output_path: Optional[str] = None,
        image_format: str = "png",
        show_legend: bool = True,
        # Semantic parameter operations
        parameter: Optional[str] = None,
        value: Optional[float] = None,
        target_ids: Optional[List[str]] = None,
        assignments: Optional[Dict[str, float]] = None,
        expected_model_sha256: Optional[str] = None,
    ) -> str:
        """
        HVAC domain manager (unified).

        - discover: list loops and components
        - topology: detailed loop topology for a given loop
        - visualize: generate a diagram (returns path)
        - capabilities: enumerate actions
        """
        try:
            if action == "capabilities":
                return (
                    '{"tool":"hvac_manager","actions":[{"name":"discover","required":["idf_path"]},{"name":"topology","required":["idf_path","loop_name"]},{"name":"visualize","required":["idf_path"],"optional":["loop_name","output_path","image_format","show_legend"]},{"name":"parameter_capabilities","required":[],"optional":["idf_path"]},{"name":"inspect_parameter","required":["idf_path","parameter"]},{"name":"adjust_percentage","required":["idf_path","parameter","value","output_path"]},{"name":"set_parameter","required":["idf_path","parameter","output_path"],"optional":["value","target_ids","assignments","expected_model_sha256"]}]}'
                )
            if action == "parameter_capabilities":
                return json.dumps(_parameter_capabilities(ep_manager, idf_path), indent=2)
            if not idf_path:
                return "Missing required parameter: idf_path"
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
                    ep_manager.adjust_parameter_percentage(idf_path, normalized, value, output_path), action
                ), indent=2)
            if action == "set_parameter":
                normalized = _require_owned_parameter(parameter)
                if not output_path or (value is None and assignments is None):
                    return json.dumps({"error": "Missing required parameters: idf_path, parameter, value or assignments, output_path"})
                return json.dumps(_tag_parameter_response(
                    ep_manager.set_parameter(
                        idf_path, normalized, value, output_path, target_ids,
                        assignments, expected_model_sha256,
                    ), action
                ), indent=2)
            if action == "discover":
                return ep_manager.discover_hvac_loops(idf_path)
            if action == "topology":
                if not loop_name:
                    return "Missing required parameter: loop_name"
                return ep_manager.get_loop_topology(idf_path, loop_name)
            if action == "visualize":
                return ep_manager.visualize_loop_diagram(idf_path, loop_name, output_path, image_format, show_legend)
            return f"Unsupported action: {action}"
        except FileNotFoundError as e:
            logger.warning(f"HVAC file not found: {str(e)}")
            return f"File not found: {str(e)}"
        except Exception as e:
            logger.error(f"hvac_manager error: {str(e)}")
            return f"Error in hvac_manager: {str(e)}"
    logger.info("domains.hvac.register complete: hvac_manager available")


# --- Reusable domain helpers (importable by orchestrators) ---
def hvac_discover(ep_manager: Any, idf_path: str) -> str:
    return ep_manager.discover_hvac_loops(idf_path)


def hvac_topology(ep_manager: Any, idf_path: str, loop_name: str) -> str:
    return ep_manager.get_loop_topology(idf_path, loop_name)


def hvac_visualize(
    ep_manager: Any,
    idf_path: str,
    loop_name: Optional[str] = None,
    output_path: Optional[str] = None,
    image_format: str = "png",
    show_legend: bool = True,
) -> str:
    return ep_manager.visualize_loop_diagram(idf_path, loop_name, output_path, image_format, show_legend)
