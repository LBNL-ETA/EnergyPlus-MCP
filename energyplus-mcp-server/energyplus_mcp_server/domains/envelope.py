from typing import Any, Dict, Optional, Literal, List
import json
import logging

logger = logging.getLogger(__name__)


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    """Register the envelope_manager tool with the MCP server."""
    logger.info("domains.envelope.register starting")
    
    @mcp.tool()
    async def envelope_manager(
        action: Literal["inspect", "modify", "generate_html", "capabilities"],
        idf_path: Optional[str] = None,
        # Inspect parameters
        focus: Literal["all", "surfaces", "constructions", "materials", "relationships"] = "all",
        # Modify parameters
        op: Optional[Literal[
            "material.edit",
            "construction.edit",
        ]] = None,
        target: Optional[str] = None,  # Material or construction name
        properties: Optional[Dict[str, Any]] = None,  # For material.edit
        layers: Optional[List[str]] = None,  # For construction.edit
        output_path: Optional[str] = None,
    ) -> str:
        """
        Envelope domain manager for building envelope components.
        
        Actions:
        - inspect: Get comprehensive envelope data (surfaces, constructions, materials, relationships)
        - modify: Edit material properties or construction layers
        - generate_html: Generate interactive HTML visualization of envelope relationships
        - capabilities: List supported operations
        
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
                            "name": "generate_html",
                            "description": "Generate interactive HTML visualization of envelope relationships",
                            "required": ["idf_path"],
                            "returns": "HTML string with React-based interactive viewer showing zones, constructions, materials, and their relationships"
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
                        }
                    ],
                    "notes": [
                        "All modifications create a new output file (does not overwrite input)",
                        "Use inspect with focus='all' to see complete envelope picture",
                        "Relationships show which materials/constructions are used and orphaned objects",
                        "Material properties use IDF field names (case-insensitive with underscores)"
                    ]
                }, indent=2)
            
            if not idf_path:
                return json.dumps({"error": "Missing required parameter: idf_path"})
            
            # Handle HTML generation
            if action == "generate_html":
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
