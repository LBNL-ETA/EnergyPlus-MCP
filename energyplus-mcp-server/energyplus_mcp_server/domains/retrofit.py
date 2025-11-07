from typing import Any, Dict, Optional, Literal
import json
import logging

logger = logging.getLogger(__name__)


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    """Register the retrofit_manager tool with the MCP server."""
    logger.info("domains.retrofit.register starting")
    
    @mcp.tool()
    async def retrofit_manager(
        action: Literal["list_measures", "apply", "capabilities"],
        idf_path: Optional[str] = None,
        # Apply parameters
        measure: Optional[Literal[
            "add_window_film",
            "add_cool_roof_coating",
            "add_cool_wall_coating",
            "reduce_infiltration",
        ]] = None,
        params: Optional[Dict[str, Any]] = None,
        output_path: Optional[str] = None,
    ) -> str:
        """
        Retrofit manager for applying energy conservation measures (ECMs).
        
        Actions:
        - list_measures: Show available retrofit measures with descriptions
        - apply: Apply a specific energy conservation measure
        - capabilities: List supported operations and parameters
        
        Available Measures:
        
        1. add_window_film
           Description: Add high-performance window film to exterior windows
           Parameters:
             - u_value: U-factor (W/m²·K), default: 4.94
             - shgc: Solar Heat Gain Coefficient, default: 0.45
             - visible_transmittance: Visible light transmittance, default: 0.66
           Purpose: Reduce solar heat gain and improve window performance
        
        2. add_cool_roof_coating
           Description: Apply reflective coating to exterior roof surfaces
           Parameters:
             - solar_absorptance: Solar absorptance (0-1), default: 0.3
             - thermal_absorptance: Thermal emittance (0-1), default: 0.9
           Purpose: Reduce cooling load by reflecting solar radiation
        
        3. add_cool_wall_coating
           Description: Apply reflective coating to exterior wall surfaces
           Parameters:
             - solar_absorptance: Solar absorptance (0-1), default: 0.4
             - thermal_absorptance: Thermal emittance (0-1), default: 0.9
           Purpose: Reduce cooling load by reflecting solar radiation
        
        4. reduce_infiltration
           Description: Seal building envelope to reduce air leakage
           Parameters:
             - multiplier: Infiltration multiplier (0-1), default: 0.7
           Purpose: Reduce heating/cooling load from air infiltration
        
        Returns:
        - list_measures: JSON with detailed measure descriptions
        - apply: JSON with retrofit results and modified file path
        - capabilities: JSON describing tool capabilities
        
        Examples:
            # Apply window film with default parameters
            {"action": "apply", "measure": "add_window_film", 
             "idf_path": "model.idf"}
            
            # Apply cool roof coating with custom reflectivity
            {"action": "apply", "measure": "add_cool_roof_coating",
             "idf_path": "model.idf",
             "params": {"solar_absorptance": 0.2, "thermal_absorptance": 0.95}}
            
            # Reduce infiltration by 30%
            {"action": "apply", "measure": "reduce_infiltration",
             "idf_path": "model.idf",
             "params": {"multiplier": 0.7}}
        """
        try:
            if action == "capabilities":
                return json.dumps({
                    "tool": "retrofit_manager",
                    "purpose": "Apply energy conservation measures (ECMs) to improve building performance",
                    "actions": [
                        {
                            "name": "list_measures",
                            "description": "List all available retrofit measures with parameters",
                            "required": []
                        },
                        {
                            "name": "apply",
                            "description": "Apply a specific energy conservation measure",
                            "required": ["idf_path", "measure"],
                            "optional": ["params", "output_path"]
                        }
                    ],
                    "measures_count": 4,
                    "notes": [
                        "All retrofits create a new output file (does not overwrite input)",
                        "Use list_measures to see detailed parameter information",
                        "Measures can be combined by applying them sequentially",
                        "Parameters are optional - sensible defaults are provided"
                    ]
                }, indent=2)
            
            if action == "list_measures":
                measures = {
                    "available_measures": [
                        {
                            "id": "add_window_film",
                            "name": "High-Performance Window Film",
                            "category": "Envelope - Windows",
                            "description": "Add spectrally selective window film to exterior windows to reduce solar heat gain while maintaining visible light transmission",
                            "typical_savings": "10-20% cooling energy",
                            "parameters": {
                                "u_value": {
                                    "description": "U-factor (W/m²·K)",
                                    "default": 4.94,
                                    "typical_range": "3.0 - 6.0",
                                    "note": "Lower is better (less heat transfer)"
                                },
                                "shgc": {
                                    "description": "Solar Heat Gain Coefficient",
                                    "default": 0.45,
                                    "typical_range": "0.25 - 0.70",
                                    "note": "Lower reduces cooling load, higher increases passive heating"
                                },
                                "visible_transmittance": {
                                    "description": "Visible light transmittance",
                                    "default": 0.66,
                                    "typical_range": "0.50 - 0.80",
                                    "note": "Higher allows more natural light"
                                }
                            },
                            "best_for": ["Cooling-dominated climates", "Buildings with large window areas", "Glare reduction"]
                        },
                        {
                            "id": "add_cool_roof_coating",
                            "name": "Cool Roof Coating",
                            "category": "Envelope - Roof",
                            "description": "Apply high-albedo reflective coating to roof surfaces to reduce solar heat absorption",
                            "typical_savings": "10-30% cooling energy",
                            "parameters": {
                                "solar_absorptance": {
                                    "description": "Solar absorptance (fraction of solar energy absorbed)",
                                    "default": 0.3,
                                    "typical_range": "0.20 - 0.40",
                                    "note": "Lower is more reflective (typical cool roof: 0.20-0.30)"
                                },
                                "thermal_absorptance": {
                                    "description": "Thermal emittance (ability to radiate heat)",
                                    "default": 0.9,
                                    "typical_range": "0.85 - 0.95",
                                    "note": "Higher is better for heat rejection"
                                }
                            },
                            "best_for": ["Hot climates", "Flat or low-slope roofs", "Commercial buildings"]
                        },
                        {
                            "id": "add_cool_wall_coating",
                            "name": "Cool Wall Coating",
                            "category": "Envelope - Walls",
                            "description": "Apply reflective coating to exterior wall surfaces to reduce solar heat gain",
                            "typical_savings": "5-15% cooling energy",
                            "parameters": {
                                "solar_absorptance": {
                                    "description": "Solar absorptance",
                                    "default": 0.4,
                                    "typical_range": "0.30 - 0.50",
                                    "note": "Lower is more reflective (light colors: 0.30-0.40)"
                                },
                                "thermal_absorptance": {
                                    "description": "Thermal emittance",
                                    "default": 0.9,
                                    "typical_range": "0.85 - 0.95",
                                    "note": "Higher is better for heat rejection"
                                }
                            },
                            "best_for": ["Hot sunny climates", "East/west facing walls", "Dark-colored buildings"]
                        },
                        {
                            "id": "reduce_infiltration",
                            "name": "Air Sealing / Infiltration Reduction",
                            "category": "Envelope - Air Tightness",
                            "description": "Seal envelope penetrations and cracks to reduce uncontrolled air leakage",
                            "typical_savings": "10-30% heating/cooling energy",
                            "parameters": {
                                "multiplier": {
                                    "description": "Infiltration multiplier (fraction of original)",
                                    "default": 0.7,
                                    "typical_range": "0.50 - 0.90",
                                    "note": "0.7 = 30% reduction, 0.5 = 50% reduction (typical retrofit)"
                                }
                            },
                            "best_for": ["Older buildings", "Cold/hot climates", "High heating/cooling costs"]
                        }
                    ],
                    "total_measures": 4,
                    "categories": ["Envelope - Windows", "Envelope - Roof", "Envelope - Walls", "Envelope - Air Tightness"]
                }
                return json.dumps(measures, indent=2)
            
            if action == "apply":
                if not idf_path:
                    return json.dumps({"error": "Missing required parameter: idf_path"})
                if not measure:
                    return json.dumps({"error": "Missing required parameter: measure"})
                
                # Apply the selected measure
                p = params or {}
                
                if measure == "add_window_film":
                    return ep_manager.add_window_film_outside(
                        idf_path,
                        float(p.get("u_value", 4.94)),
                        float(p.get("shgc", 0.45)),
                        float(p.get("visible_transmittance", 0.66)),
                        output_path,
                    )
                
                elif measure == "add_cool_roof_coating":
                    return ep_manager.add_coating_outside(
                        idf_path,
                        "roof",
                        float(p.get("solar_absorptance", 0.3)),
                        float(p.get("thermal_absorptance", 0.9)),
                        output_path,
                    )
                
                elif measure == "add_cool_wall_coating":
                    return ep_manager.add_coating_outside(
                        idf_path,
                        "wall",
                        float(p.get("solar_absorptance", 0.4)),
                        float(p.get("thermal_absorptance", 0.9)),
                        output_path,
                    )
                
                elif measure == "reduce_infiltration":
                    return ep_manager.change_infiltration_by_mult(
                        idf_path,
                        float(p.get("multiplier", 0.7)),
                        output_path
                    )
                
                else:
                    return json.dumps({"error": f"Unsupported measure: {measure}"})
            
            return json.dumps({"error": f"Unsupported action: {action}"})
            
        except FileNotFoundError as e:
            logger.warning(f"Retrofit file not found: {str(e)}")
            return json.dumps({"error": f"File not found: {str(e)}"})
        except Exception as e:
            logger.error(f"retrofit_manager error: {str(e)}", exc_info=True)
            return json.dumps({"error": f"Error in retrofit_manager: {str(e)}"})
    
    logger.info("domains.retrofit.register complete: retrofit_manager available")


# --- Reusable domain helpers (importable by orchestrators) ---
def apply_window_film(
    ep_manager: Any,
    idf_path: str,
    u_value: float = 4.94,
    shgc: float = 0.45,
    visible_transmittance: float = 0.66,
    output_path: Optional[str] = None
) -> str:
    """Apply window film retrofit."""
    return ep_manager.add_window_film_outside(idf_path, u_value, shgc, visible_transmittance, output_path)


def apply_cool_roof(
    ep_manager: Any,
    idf_path: str,
    solar_absorptance: float = 0.3,
    thermal_absorptance: float = 0.9,
    output_path: Optional[str] = None
) -> str:
    """Apply cool roof coating retrofit."""
    return ep_manager.add_coating_outside(idf_path, "roof", solar_absorptance, thermal_absorptance, output_path)


def apply_cool_walls(
    ep_manager: Any,
    idf_path: str,
    solar_absorptance: float = 0.4,
    thermal_absorptance: float = 0.9,
    output_path: Optional[str] = None
) -> str:
    """Apply cool wall coating retrofit."""
    return ep_manager.add_coating_outside(idf_path, "wall", solar_absorptance, thermal_absorptance, output_path)


def reduce_infiltration(
    ep_manager: Any,
    idf_path: str,
    multiplier: float = 0.7,
    output_path: Optional[str] = None
) -> str:
    """Reduce building infiltration."""
    return ep_manager.change_infiltration_by_mult(idf_path, multiplier, output_path)

