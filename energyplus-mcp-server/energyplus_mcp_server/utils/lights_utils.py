"""
Lights object utility module for EnergyPlus MCP Server.
Handles inspection and modification of Lights objects in EnergyPlus models.
"""

import logging
from typing import Dict, List, Any, Optional
from eppy.modeleditor import IDF

from energyplus_mcp_server.utils.idf_modifier import IDFModifier

logger = logging.getLogger(__name__)


class LightsManager:
    """Manager for EnergyPlus Lights objects"""

    # Valid calculation methods for Lighting Level
    VALID_CALCULATION_METHODS = {
        "LightingLevel": "Lighting level (W)",
        "Watts/Area": "Lighting power density (W/m2)",
        "Watts/Person": "Lighting power per person (W/person)"
    }

    # Common lighting power densities (W/m2) - from ASHRAE 90.1
    COMMON_LIGHTING_DENSITIES = {
        "Office": 11.0,
        "Classroom": 12.9,
        "Conference Room": 13.2,
        "Corridor": 5.4,
        "Lobby": 12.9,
        "Restroom": 9.7,
        "Storage": 8.1,
        "Workshop": 14.0
    }

    def __init__(self):
        """Initialize the Lights manager"""
        self.idf_modifier = IDFModifier()
        self.object_type = "Lights"
    
    def get_lights_objects(self, idf_path: str) -> Dict[str, Any]:
        """
        Get all Lights objects from the IDF file with detailed information
        
        Args:
            idf_path: Path to the IDF file
            
        Returns:
            Dictionary with lights objects information
        """
        try:
            idf = IDF(idf_path)
            lights_objects = idf.idfobjects.get("Lights", [])
            
            result = {
                "success": True,
                "file_path": idf_path,
                "total_lights_objects": len(lights_objects),
                "lights_objects": [],
                "summary": {
                    "by_calculation_method": {},
                    "by_zone": {},
                    "total_lighting_power": 0.0,
                    "total_lighting_density": 0.0
                }
            }
            
            # Get all zones for reference
            zones = {zone.Name: zone for zone in idf.idfobjects.get("Zone", [])}
            
            for lights_obj in lights_objects:
                lights_info = {
                    "name": getattr(lights_obj, 'Name', 'Unknown'),
                    "zone_or_zonelist_or_space_or_spacelist_name": getattr(lights_obj, 'Zone_or_ZoneList_or_Space_or_SpaceList_Name', 'Unknown'),
                    "schedule_name": getattr(lights_obj, 'Schedule_Name', 'Unknown'),
                    "design_level_calculation_method": getattr(lights_obj, 'Design_Level_Calculation_Method', 'Unknown'),
                    "lighting_level": getattr(lights_obj, 'Lighting_Level', ''),
                    "watts_per_floor_area": getattr(lights_obj, 'Watts_per_Floor_Area', ''),
                    "watts_per_person": getattr(lights_obj, 'Watts_per_Person', ''),
                    "return_air_fraction": getattr(lights_obj, 'Return_Air_Fraction', ''),
                    "fraction_radiant": getattr(lights_obj, 'Fraction_Radiant', ''),
                    "fraction_visible": getattr(lights_obj, 'Fraction_Visible', ''),
                    "fraction_replaceable": getattr(lights_obj, 'Fraction_Replaceable', ''),
                    "end_use_subcategory": getattr(lights_obj, 'EndUse_Subcategory', ''),
                    "return_air_fraction_calculated_from_plenum_temperature": 
                        getattr(lights_obj, 'Return_Air_Fraction_Calculated_from_Plenum_Temperature', ''),
                    "return_air_fraction_function_of_plenum_temperature_coefficient_1":
                        getattr(lights_obj, 'Return_Air_Fraction_Function_of_Plenum_Temperature_Coefficient_1', ''),
                    "return_air_fraction_function_of_plenum_temperature_coefficient_2":
                        getattr(lights_obj, 'Return_Air_Fraction_Function_of_Plenum_Temperature_Coefficient_2', ''),
                    "return_air_heat_gain_node_name": getattr(lights_obj, 'Return_Air_Heat_Gain_Node_Name', ''),
                    "exhaust_air_heat_gain_node_name": getattr(lights_obj, 'Exhaust_Air_Heat_Gain_Node_Name', '')
                }
                
                # Calculate design lighting power if possible
                design_power = self._calculate_design_power(
                    lights_info, zones.get(lights_info["zone_or_zonelist_or_space_or_spacelist_name"])
                )
                lights_info["design_power"] = design_power
                
                result["lights_objects"].append(lights_info)
                
                # Update summaries
                calc_method = lights_info["design_level_calculation_method"]
                if calc_method:
                    result["summary"]["by_calculation_method"][calc_method] = \
                        result["summary"]["by_calculation_method"].get(calc_method, 0) + 1
                
                zone_name = lights_info["zone_or_zonelist_or_space_or_spacelist_name"]
                if zone_name:
                    if zone_name not in result["summary"]["by_zone"]:
                        result["summary"]["by_zone"][zone_name] = []
                    result["summary"]["by_zone"][zone_name].append(lights_info["name"])
                
                if design_power is not None:
                    result["summary"]["total_lighting_power"] += design_power
            
            logger.info(f"Found {len(lights_objects)} Lights objects in {idf_path}")
            return result
            
        except Exception as e:
            logger.error(f"Error getting Lights objects: {e}")
            return {
                "success": False,
                "error": str(e),
                "file_path": idf_path
            }
    
    def _calculate_design_power(self, lights_info: Dict[str, Any], 
                               zone_obj: Optional[Any]) -> Optional[float]:
        """Calculate design lighting power based on calculation method and zone data"""
        try:
            calc_method = lights_info["design_level_calculation_method"]
            
            if calc_method == "LightingLevel":
                value = lights_info["lighting_level"]
                if value and value != '':
                    return float(value)
                    
            elif calc_method == "Watts/Area" and zone_obj:
                watts_per_area = lights_info["watts_per_floor_area"]
                if watts_per_area and watts_per_area != '':
                    # Get zone floor area
                    floor_area = getattr(zone_obj, 'Floor_Area', None)
                    if floor_area and floor_area != '' and floor_area != 'autocalculate':
                        return float(watts_per_area) * float(floor_area)
                        
            elif calc_method == "Watts/Person":
                watts_per_person = lights_info["watts_per_person"]
                if watts_per_person and watts_per_person != '':
                    # Would need to get occupancy from People objects to calculate total power
                    # For now, just return the watts per person value as a placeholder
                    return float(watts_per_person)
            
        except (ValueError, TypeError) as e:
            logger.warning(f"Could not calculate design power: {e}")
        
        return None
    
    def modify_lights_objects(self, idf_path: str, modifications: List[Dict[str, Any]],
                             output_path: str) -> Dict[str, Any]:
        """
        Modify Lights objects in the IDF file

        Args:
            idf_path: Path to the input IDF file
            modifications: List of modification specifications
            output_path: Path for the output IDF file

        Returns:
            Dictionary with modification results
        """
        try:
            # Pre-process modifications: Apply business logic validation
            processed_mods = []
            errors = []

            for mod_spec in modifications:
                target = mod_spec.get("target", "all")
                field_updates = mod_spec.get("field_updates", {})

                # Business logic: Validate calculation method changes
                if "Design_Level_Calculation_Method" in field_updates:
                    new_method = field_updates["Design_Level_Calculation_Method"]
                    if new_method not in self.VALID_CALCULATION_METHODS:
                        errors.append(
                            f"Invalid calculation method '{new_method}'. "
                            f"Valid options: {list(self.VALID_CALCULATION_METHODS.keys())}"
                        )
                        continue

                # Convert field_updates dict to list format for IDFModifier
                field_list = [{"field": k, "value": v} for k, v in field_updates.items()]

                processed_mods.append({
                    "target": target,
                    "modifications": field_list
                })

            # Delegate to IDFModifier for mechanics (load, filter, validate, save)
            all_modified_objects = []
            for mod in processed_mods:
                result = self.idf_modifier.modify_objects(
                    idf_path=idf_path,
                    object_type=self.object_type,
                    modifications=mod["modifications"],
                    target=mod["target"],
                    output_path=output_path
                )

                if result.get("success"):
                    all_modified_objects.extend(result.get("modified_objects", []))
                    # Use output from first modification as input for next
                    if result.get("output_file"):
                        idf_path = result["output_file"]
                else:
                    errors.extend(result.get("errors", []))

            # Format result in expected format
            modifications_applied = []
            for obj in all_modified_objects:
                for field in obj.get("modified_fields", []):
                    modifications_applied.append({
                        "object_name": obj["name"],
                        "field": field["field"],
                        "old_value": field["old_value"],
                        "new_value": field["new_value"]
                    })

            final_result = {
                "success": len(modifications_applied) > 0,
                "input_file": idf_path,
                "output_file": output_path if len(modifications_applied) > 0 else None,
                "modifications_requested": len(modifications),
                "modifications_applied": modifications_applied,
                "total_modifications_applied": len(modifications_applied),
                "errors": errors
            }

            logger.info(f"Applied {len(modifications_applied)} modifications to Lights objects")
            return final_result

        except Exception as e:
            logger.error(f"Error modifying Lights objects: {e}")
            return {
                "success": False,
                "error": str(e),
                "input_file": idf_path
            }
    
    def validate_lights_modifications(self, modifications: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validate modification specifications before applying them

        Note: Field name validation is now handled by IDD at modification time.
        This method focuses on business logic validation.

        Args:
            modifications: List of modification specifications

        Returns:
            Validation result dictionary
        """
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": []
        }

        for i, mod_spec in enumerate(modifications):
            # Check required fields
            if "target" not in mod_spec:
                validation_result["errors"].append(f"Modification {i}: Missing 'target' field")
                validation_result["valid"] = False

            if "field_updates" not in mod_spec:
                validation_result["errors"].append(f"Modification {i}: Missing 'field_updates' field")
                validation_result["valid"] = False
            elif not isinstance(mod_spec["field_updates"], dict):
                validation_result["errors"].append(f"Modification {i}: 'field_updates' must be a dictionary")
                validation_result["valid"] = False
            else:
                # Business logic validation
                field_updates = mod_spec["field_updates"]

                # Validate calculation method
                if "Design_Level_Calculation_Method" in field_updates:
                    value = field_updates["Design_Level_Calculation_Method"]
                    if value not in self.VALID_CALCULATION_METHODS:
                        validation_result["errors"].append(
                            f"Modification {i}: Invalid calculation method '{value}'. "
                            f"Valid options: {list(self.VALID_CALCULATION_METHODS.keys())}"
                        )
                        validation_result["valid"] = False

                    # Check for conflicting calculation method and values
                    if value == "LightingLevel" and "Watts_per_Floor_Area" in field_updates:
                        validation_result["warnings"].append(
                            f"Modification {i}: Setting calculation method to 'LightingLevel' "
                            "but also setting 'Watts_per_Floor_Area'"
                        )
                    elif value == "Watts/Area" and "Lighting_Level" in field_updates:
                        validation_result["warnings"].append(
                            f"Modification {i}: Setting calculation method to 'Watts/Area' "
                            "but also setting 'Lighting_Level'"
                        )
                    elif value == "Watts/Person" and ("Lighting_Level" in field_updates or "Watts_per_Floor_Area" in field_updates):
                        validation_result["warnings"].append(
                            f"Modification {i}: Setting calculation method to 'Watts/Person' "
                            "but also setting other power values"
                        )

            # Validate target format
            target = mod_spec.get("target", "")
            if target and not (target == "all" or target.startswith("zone:") or target.startswith("name:")):
                validation_result["errors"].append(
                    f"Modification {i}: Invalid target format '{target}'. "
                    "Use 'all', 'zone:ZoneName', or 'name:LightsName'"
                )
                validation_result["valid"] = False

        return validation_result 
