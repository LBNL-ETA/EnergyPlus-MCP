from typing import Any, Dict, Optional, Literal, List
import json
import logging

logger = logging.getLogger(__name__)


PARAMETERS = ("INF", "WIN-U", "WIN-SHGC")


def _require_owned_parameter(parameter: Optional[str]) -> str:
    normalized = parameter.strip().upper() if isinstance(parameter, str) else ""
    if normalized not in PARAMETERS:
        raise ValueError(
            "envelope_manager supports semantic parameters: " + ", ".join(PARAMETERS)
        )
    return normalized


def _tag_parameter_response(payload: Dict[str, Any], action: str) -> Dict[str, Any]:
    """Attach the public domain identity without changing edit semantics."""
    result = dict(payload)
    result["tool"] = "envelope_manager"
    result["manager"] = "envelope_manager"
    result["action"] = action
    return result


def _parameter_capabilities(ep_manager: Any, idf_path: Optional[str]) -> Dict[str, Any]:
    payload = ep_manager.parameter_capabilities(idf_path, list(PARAMETERS))
    result = _tag_parameter_response(payload, "parameter_capabilities")
    for detail in result.get("parameters", {}).values():
        detail["tool"] = "envelope_manager"
        detail["manager"] = "envelope_manager"
        detail["action"] = "adjust_percentage"
        detail["absolute_set"]["tool"] = "envelope_manager"
        detail["absolute_set"]["manager"] = "envelope_manager"
        detail["absolute_set"]["action"] = "set_parameter"
    return result


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    """Register the envelope_manager tool with the MCP server."""
    logger.info("domains.envelope.register starting")
    
    @mcp.tool()
    async def envelope_manager(
        action: Literal[
            "inspect", "modify", "generate_html_str", "capabilities",
            "parameter_capabilities", "inspect_parameter", "adjust_percentage", "set_parameter",
        ],
        idf_path: Optional[str] = None,
        # Inspect parameters
        focus: Literal["all", "surfaces", "constructions", "materials", "relationships"] = "all",
        # Modify parameters
        op: Optional[Literal[
            "material.edit",
            "construction.edit",
            "window.add_film",
            "surface.apply_coating",
            "infiltration.scale",
        ]] = None,
        target: Optional[str] = None,  # Material or construction name
        properties: Optional[Dict[str, Any]] = None,  # For material.edit
        layers: Optional[List[str]] = None,  # For construction.edit
        output_path: Optional[str] = None,  # For modify action only; deprecated for generate_html_str
        # Semantic parameter operations
        parameter: Optional[str] = None,
        value: Optional[float] = None,
        target_ids: Optional[List[str]] = None,
        assignments: Optional[Dict[str, float]] = None,
        expected_model_sha256: Optional[str] = None,
        mode: Literal["apply", "dry_run"] = "apply",
    ) -> str:
        """
        Envelope domain manager for building envelope components.

        Actions:
        - inspect: Get comprehensive envelope data (surfaces, constructions, materials, relationships)
        - modify: Edit material properties or construction layers (optionally specify output_path for modified IDF)
        - generate_html_str: Generate interactive HTML visualization of envelope relationships as string
        - parameter_capabilities: Model-specific support for INF, WIN-U, and WIN-SHGC
        - inspect_parameter: Inspect canonical absolute semantic targets
        - adjust_percentage: Apply a signed semantic percentage change to a new IDF
        - set_parameter: Apply inspected absolute values, optionally source-hash bound
        - capabilities: List supported operations

        Args:
            action: The operation to perform
            idf_path: Path to the IDF file (required for all actions except capabilities)
            focus: Level of detail for inspect action (all/surfaces/constructions/materials/relationships)
            op: Operation type for modify action (material.edit/construction.edit)
            target: Material or construction name for modify action
            properties: Dictionary of material properties for material.edit
            layers: List of material layer names for construction.edit

        Inspection Focus:
        - "all": Complete envelope with all components and relationships (default)
        - "surfaces": Building surfaces only
        - "constructions": Construction definitions only
        - "materials": Material definitions only
        - "relationships": Usage and dependency analysis

        Modification Operations:
        - "material.edit": Modify material properties
          Required: target (material name), properties (dict of field: value pairs)
          Example: {"op": "material.edit", "target": "M01 100mm brick",
                   "properties": {"Conductivity": 0.75, "Solar_Absorptance": 0.6}}

        - "construction.edit": Modify construction layers
          Required: target (construction name), layers (list of material names from outside to inside)
          Example: {"op": "construction.edit", "target": "WALL-1",
                   "layers": ["M01 100mm brick", "NEW_INSULATION", "I02 50mm insulation board"]}

        Returns:
        - inspect: JSON with envelope data based on focus
        - modify: JSON with modification results and changelog
        - generate_html_str: HTML string with interactive viewer
        - capabilities: JSON describing available operations
        """
        try:
            if action == "capabilities":
                return json.dumps({
                    "tool": "envelope_manager",
                    "purpose": "Manage building envelope components (surfaces, constructions, materials)",
                    "actions": [
                        {
                            "name": "inspect",
                            "description": "Get envelope data with relationships",
                            "required": ["idf_path"],
                            "optional": ["focus"],
                            "focus_options": ["all", "surfaces", "constructions", "materials", "relationships"]
                        },
                        {
                            "name": "modify",
                            "description": "Edit material properties or construction layers",
                            "required": ["idf_path", "op"],
                            "optional": ["output_path"]
                        },
                        {
                            "name": "generate_html_str",
                            "description": "Generate interactive HTML visualization of envelope relationships as string",
                            "required": ["idf_path"],
                            "optional": [],
                            "returns": "HTML string with React-based interactive viewer showing zones, constructions, materials, and their relationships"
                        },
                        {
                            "name": "parameter_capabilities",
                            "description": "Report complete-only semantic parameter support",
                            "required": [],
                            "optional": ["idf_path"]
                        },
                        {
                            "name": "inspect_parameter",
                            "description": "Inspect canonical absolute INF, WIN-U, or WIN-SHGC targets",
                            "required": ["idf_path", "parameter"]
                        },
                        {
                            "name": "adjust_percentage",
                            "description": "Apply signed percentage change to a semantic parameter",
                            "required": ["idf_path", "parameter", "value", "output_path"],
                            "optional": ["expected_model_sha256"]
                        },
                        {
                            "name": "set_parameter",
                            "description": "Set absolute semantic target value(s) after inspection",
                            "required": ["idf_path", "parameter", "output_path"],
                            "optional": ["value", "target_ids", "assignments", "expected_model_sha256"]
                        }
                    ],
                    "operations": [
                        {
                            "op": "material.edit",
                            "description": "Modify material properties",
                            "required": ["target", "properties"],
                            "example": {
                                "target": "M01 100mm brick",
                                "properties": {
                                    "Conductivity": 0.75,
                                    "Solar_Absorptance": 0.6,
                                    "Thermal_Absorptance": 0.9
                                }
                            }
                        },
                        {
                            "op": "construction.edit",
                            "description": "Modify construction layers",
                            "required": ["target", "layers"],
                            "example": {
                                "target": "WALL-1",
                                "layers": [
                                    "M01 100mm brick",
                                    "NEW_INSULATION_LAYER",
                                    "M15 200mm heavyweight concrete",
                                    "I02 50mm insulation board"
                                ]
                            }
                        },
                        {
                            "op": "window.add_film",
                            "description": "Add simple-glazing window-film constructions to exterior windows",
                            "required": [],
                            "optional": ["properties", "output_path"]
                        },
                        {
                            "op": "surface.apply_coating",
                            "description": "Apply a reflective coating to exterior roof or wall surfaces",
                            "required": ["target"],
                            "optional": ["properties", "output_path"]
                        },
                        {
                            "op": "infiltration.scale",
                            "description": "Scale native infiltration fields by a multiplier",
                            "required": ["properties.multiplier"],
                            "optional": ["output_path"]
                        }
                    ],
                    "notes": [
                        "All modifications create a new output file (does not overwrite input)",
                        "Use inspect with focus='all' to see complete envelope picture",
                        "Relationships show which materials/constructions are used and orphaned objects",
                        "Material properties use IDF field names (case-insensitive with underscores)"
                    ]
                }, indent=2)

            if action == "parameter_capabilities":
                return json.dumps(_parameter_capabilities(ep_manager, idf_path), indent=2)
            
            if not idf_path:
                return json.dumps({"error": "Missing required parameter: idf_path"})

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
            
            # Handle HTML generation
            if action == "generate_html_str":
                return ep_manager.generate_envelope_html(idf_path)
            
            # Handle inspection
            if action == "inspect":
                if focus == "all":
                    # Comprehensive inspection
                    return ep_manager.inspect_envelope_comprehensive(idf_path)
                elif focus == "surfaces":
                    return ep_manager.get_surfaces(idf_path)
                elif focus == "constructions":
                    return ep_manager.get_constructions(idf_path)
                elif focus == "materials":
                    return ep_manager.get_materials(idf_path)
                elif focus == "relationships":
                    # Get comprehensive data but return only relationships
                    comprehensive = json.loads(ep_manager.inspect_envelope_comprehensive(idf_path))
                    return json.dumps({
                        "file_path": comprehensive["file_path"],
                        "summary": comprehensive["summary"],
                        "relationships": comprehensive["relationships"]
                    }, indent=2)
                else:
                    return json.dumps({"error": f"Unsupported focus: {focus}"})
            
            # Handle modification
            if action == "modify":
                if not op:
                    return json.dumps({"error": "Missing required parameter: op (operation)"})
                
                if op == "material.edit":
                    if not target:
                        return json.dumps({"error": "Missing required parameter: target (material name)"})
                    if not properties:
                        return json.dumps({"error": "Missing required parameter: properties (dict of material properties)"})
                    
                    return ep_manager.edit_material(idf_path, target, properties, output_path)
                
                elif op == "construction.edit":
                    if not target:
                        return json.dumps({"error": "Missing required parameter: target (construction name)"})
                    if not layers:
                        return json.dumps({"error": "Missing required parameter: layers (list of material names)"})
                    
                    return ep_manager.edit_construction(idf_path, target, layers, output_path)

                elif op == "window.add_film":
                    p = properties or {}
                    return add_window_film(
                        ep_manager, idf_path,
                        float(p.get("u_value", 4.94)),
                        float(p.get("shgc", 0.45)),
                        float(p.get("visible_transmittance", 0.66)),
                        output_path,
                    )

                elif op == "surface.apply_coating":
                    if not target or target.strip().lower() not in {"roof", "wall"}:
                        return json.dumps({"error": "target must be 'roof' or 'wall' for surface.apply_coating"})
                    p = properties or {}
                    defaults = (0.3, 0.9) if target.strip().lower() == "roof" else (0.4, 0.9)
                    return apply_surface_coating(
                        ep_manager, idf_path, target,
                        float(p.get("solar_absorptance", defaults[0])),
                        float(p.get("thermal_absorptance", defaults[1])), output_path,
                    )

                elif op == "infiltration.scale":
                    p = properties or {}
                    if "multiplier" not in p:
                        return json.dumps({"error": "Missing required property: multiplier"})
                    return scale_infiltration(ep_manager, idf_path, float(p["multiplier"]), output_path)
                
                else:
                    return json.dumps({"error": f"Unsupported operation: {op}"})
            
            return json.dumps({"error": f"Unsupported action: {action}"})
            
        except FileNotFoundError as e:
            logger.warning(f"Envelope file not found: {str(e)}")
            return json.dumps({"error": f"File not found: {str(e)}"})
        except Exception as e:
            logger.error(f"envelope_manager error: {str(e)}", exc_info=True)
            return json.dumps({"error": f"Error in envelope_manager: {str(e)}"})
    
    logger.info("domains.envelope.register complete: envelope_manager available")


# --- Reusable domain helpers (importable by orchestrators) ---
def inspect_envelope(
    ep_manager: Any, 
    idf_path: str, 
    focus: str = "all"
) -> str:
    """Get envelope data from IDF file."""
    if focus == "all":
        return ep_manager.inspect_envelope_comprehensive(idf_path)
    elif focus == "surfaces":
        return ep_manager.get_surfaces(idf_path)
    elif focus == "constructions":
        return ep_manager.get_constructions(idf_path)
    elif focus == "materials":
        return ep_manager.get_materials(idf_path)
    else:
        comprehensive = json.loads(ep_manager.inspect_envelope_comprehensive(idf_path))
        return json.dumps({
            "file_path": comprehensive["file_path"],
            "summary": comprehensive["summary"],
            "relationships": comprehensive["relationships"]
        }, indent=2)


def edit_material(
    ep_manager: Any,
    idf_path: str,
    material_name: str,
    properties: Dict[str, Any],
    output_path: Optional[str] = None
) -> str:
    """Edit material properties."""
    return ep_manager.edit_material(idf_path, material_name, properties, output_path)


def edit_construction(
    ep_manager: Any,
    idf_path: str,
    construction_name: str,
    layers: List[str],
    output_path: Optional[str] = None
) -> str:
    """Edit construction layers."""
    return ep_manager.edit_construction(idf_path, construction_name, layers, output_path)


def add_window_film(
    ep_manager: Any,
    idf_path: str,
    u_value: float = 4.94,
    shgc: float = 0.45,
    visible_transmittance: float = 0.66,
    output_path: Optional[str] = None,
) -> str:
    """Create window-film constructions for exterior windows.

    This is a generic envelope compound operation.  It intentionally keeps
    the established EnergyPlusManager construction and sharing behavior.
    """
    return ep_manager.add_window_film_outside(
        idf_path, u_value, shgc, visible_transmittance, output_path
    )


def apply_surface_coating(
    ep_manager: Any,
    idf_path: str,
    surface_kind: str,
    solar_absorptance: float,
    thermal_absorptance: float,
    output_path: Optional[str] = None,
) -> str:
    """Apply a coating to exterior roof or wall surfaces."""
    normalized = surface_kind.strip().lower()
    if normalized not in {"roof", "wall"}:
        raise ValueError("surface_kind must be 'roof' or 'wall'")
    return ep_manager.add_coating_outside(
        idf_path, normalized, solar_absorptance, thermal_absorptance, output_path
    )


def scale_infiltration(
    ep_manager: Any,
    idf_path: str,
    multiplier: float,
    output_path: Optional[str] = None,
) -> str:
    """Scale the manager's native infiltration representation by a multiplier."""
    return ep_manager.change_infiltration_by_mult(idf_path, multiplier, output_path)


# Helpers consumed by the unified master tools.  They preserve the master's
# established operation names while routing to the one domain implementation.
def inspect_envelope_data(ep_manager: Any, idf_path: str, focus: List[str]) -> Dict[str, Any]:
    """Return requested envelope sections for the aggregated inspect tool."""
    payload: Dict[str, Any] = {}
    if "surfaces" in focus:
        payload["surfaces"] = ep_manager.get_surfaces(idf_path)
    if "materials" in focus:
        payload["materials"] = ep_manager.get_materials(idf_path)
    return payload


def modify_envelope(
    ep_manager: Any,
    idf_path: str,
    op: str,
    params: Optional[Dict[str, Any]],
    output_path: Optional[str],
) -> str:
    """Apply one workflow-neutral envelope master-tool operation."""
    p = params or {}
    if op == "infiltration.scale":
        if "multiplier" not in p:
            raise ValueError("infiltration.scale requires multiplier")
        return scale_infiltration(ep_manager, idf_path, float(p["multiplier"]), output_path)
    if op == "envelope.add_window_film":
        return add_window_film(
            ep_manager, idf_path,
            float(p.get("u_value", 4.94)),
            float(p.get("shgc", 0.45)),
            float(p.get("visible_transmittance", 0.66)), output_path,
        )
    if op == "envelope.add_coating":
        surface_kind = str(p.get("surface_type", p.get("target", ""))).strip().lower()
        if surface_kind not in {"roof", "wall"}:
            raise ValueError("envelope.add_coating requires surface_type 'roof' or 'wall'")
        defaults = (0.3, 0.9) if surface_kind == "roof" else (0.4, 0.9)
        return apply_surface_coating(
            ep_manager, idf_path, surface_kind,
            float(p.get("solar_absorptance", defaults[0])),
            float(p.get("thermal_absorptance", defaults[1])), output_path,
        )
    raise ValueError(f"Unsupported envelope op: {op}")
