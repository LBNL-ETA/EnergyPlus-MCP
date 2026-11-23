"""
Electric Equipment utility module for EnergyPlus MCP Server.
Handles inspection and modification of ElectricEquipment objects in EnergyPlus models.

EnergyPlus Model Context Protocol Server (EnergyPlus-MCP)
Copyright (c) 2025, The Regents of the University of California,
through Lawrence Berkeley National Laboratory (subject to receipt of
any required approvals from the U.S. Dept. of Energy). All rights reserved.

See License.txt in the parent directory for license details.
"""

import logging
from typing import Dict, List, Any, Optional
from eppy.modeleditor import IDF

logger = logging.getLogger(__name__)


class ElectricEquipmentManager:
    """Manager for EnergyPlus ElectricEquipment objects"""
    
    # Valid calculation methods for Design Level
    VALID_CALCULATION_METHODS = {
        "EquipmentLevel": "Equipment level (W)",
        "Watts/Area": "Power density (W/m2)", 
        "Watts/Person": "Power per person (W/person)"
    }
    
    # Common electric equipment power densities (W/m2) - from ASHRAE 90.1
    COMMON_EQUIPMENT_DENSITIES = {
        "Office": 12.0,
        "Classroom": 6.4,
        "Conference Room": 6.4,
        "Corridor": 3.2,
        "Lobby": 6.4,
        "Restroom": 3.2,
        "Storage": 3.2,
        "Kitchen": 25.0,
        "Data Center": 215.0
    }
    
    def __init__(self):
        """Initialize the ElectricEquipment manager"""
        pass
    
    def get_electric_equipment_objects(self, idf_path: str) -> Dict[str, Any]:
        """
        Get all ElectricEquipment objects from the IDF file with detailed information
        
        Args:
            idf_path: Path to the IDF file
            
        Returns:
            Dictionary with electric equipment objects information
        """
        try:
            idf = IDF(idf_path)
            equipment_objects = idf.idfobjects.get("ElectricEquipment", [])
            
            result = {
                "success": True,
                "file_path": idf_path,
                "total_electric_equipment_objects": len(equipment_objects),
                "electric_equipment_objects": [],
                "summary": {
                    "by_calculation_method": {},
                    "by_zone": {},
                    "total_equipment_power": 0.0
                }
            }
            
            # Get all zones for reference
            zones = {zone.Name: zone for zone in idf.idfobjects.get("Zone", [])}
            
            for equipment_obj in equipment_objects:
                equipment_info = {
                    "name": getattr(equipment_obj, 'Name', 'Unknown'),
                    "zone_or_zonelist_or_space_or_spacelist_name": getattr(equipment_obj, 'Zone_or_ZoneList_or_Space_or_SpaceList_Name', 'Unknown'),
                    "schedule_name": getattr(equipment_obj, 'Schedule_Name', 'Unknown'),
                    "design_level_calculation_method": getattr(equipment_obj, 'Design_Level_Calculation_Method', 'Unknown'),
                    "design_level": getattr(equipment_obj, 'Design_Level', ''),
                    "watts_per_floor_area": getattr(equipment_obj, 'Watts_per_Floor_Area', ''),
                    "watts_per_person": getattr(equipment_obj, 'Watts_per_Person', ''),
                    "fraction_latent": getattr(equipment_obj, 'Fraction_Latent', ''),
                    "fraction_radiant": getattr(equipment_obj, 'Fraction_Radiant', ''),
                    "fraction_lost": getattr(equipment_obj, 'Fraction_Lost', ''),
                    "end_use_subcategory": getattr(equipment_obj, 'EndUse_Subcategory', '')
                }
                
                # Calculate design equipment power if possible
                design_power = self._calculate_design_power(
                    equipment_info, zones.get(equipment_info["zone_or_zonelist_or_space_or_spacelist_name"])
                )
                equipment_info["design_power"] = design_power
                
                result["electric_equipment_objects"].append(equipment_info)
                
                # Update summaries
                calc_method = equipment_info["design_level_calculation_method"]
                if calc_method:
                    result["summary"]["by_calculation_method"][calc_method] = \
                        result["summary"]["by_calculation_method"].get(calc_method, 0) + 1
                
                zone_name = equipment_info["zone_or_zonelist_or_space_or_spacelist_name"]
                if zone_name:
                    if zone_name not in result["summary"]["by_zone"]:
                        result["summary"]["by_zone"][zone_name] = []
                    result["summary"]["by_zone"][zone_name].append(equipment_info["name"])
                
                if design_power is not None:
                    result["summary"]["total_equipment_power"] += design_power
            
            logger.info(f"Found {len(equipment_objects)} ElectricEquipment objects in {idf_path}")
            return result
            
        except Exception as e:
            logger.error(f"Error getting ElectricEquipment objects: {e}")
            return {
                "success": False,
                "error": str(e),
                "file_path": idf_path
            }
    
    def _calculate_design_power(self, equipment_info: Dict[str, Any], 
                               zone_obj: Optional[Any]) -> Optional[float]:
        """Calculate design equipment power based on calculation method and zone data"""
        try:
            calc_method = equipment_info["design_level_calculation_method"]
            
            if calc_method == "EquipmentLevel":
                value = equipment_info["design_level"]
                if value and value != '':
                    return float(value)
                    
            elif calc_method == "Watts/Area" and zone_obj:
                watts_per_area = equipment_info["watts_per_floor_area"]
                if watts_per_area and watts_per_area != '':
                    # Get zone floor area
                    floor_area = getattr(zone_obj, 'Floor_Area', None)
                    if floor_area and floor_area != '' and floor_area != 'autocalculate':
                        return float(watts_per_area) * float(floor_area)
                        
            elif calc_method == "Watts/Person":
                watts_per_person = equipment_info["watts_per_person"]
                if watts_per_person and watts_per_person != '':
                    # Would need to get occupancy from People objects to calculate total power
                    # For now, just return the watts per person value as a placeholder
                    return float(watts_per_person)
            
        except (ValueError, TypeError) as e:
            logger.warning(f"Could not calculate design power: {e}")
        
        return None
    
    def modify_electric_equipment_objects(self, idf_path: str, modifications: List[Dict[str, Any]], 
                                         output_path: str) -> Dict[str, Any]:
        """
        Modify ElectricEquipment objects in the IDF file
        
        Args:
            idf_path: Path to the input IDF file
            modifications: List of modification specifications
            output_path: Path for the output IDF file
            
        Returns:
            Dictionary with modification results
        """
        try:
            idf = IDF(idf_path)
            equipment_objects = idf.idfobjects.get("ElectricEquipment", [])
            
            result = {
                "success": True,
                "input_file": idf_path,
                "output_file": output_path,
                "modifications_requested": len(modifications),
                "modifications_applied": [],
                "errors": []
            }
            
            for mod_spec in modifications:
                try:
                    # Apply modification based on target
                    target = mod_spec.get("target", "all")
                    field_updates = mod_spec.get("field_updates", {})
                    
                    if target == "all":
                        # Apply to all ElectricEquipment objects
                        for equipment_obj in equipment_objects:
                            self._apply_equipment_modifications(
                                equipment_obj, field_updates, result
                            )
                    elif target.startswith("zone:"):
                        # Apply to ElectricEquipment objects in specific zone
                        zone_name = target.replace("zone:", "").strip()
                        for equipment_obj in equipment_objects:
                            if getattr(equipment_obj, 'Zone_or_ZoneList_or_Space_or_SpaceList_Name', '') == zone_name:
                                self._apply_equipment_modifications(
                                    equipment_obj, field_updates, result
                                )
                    elif target.startswith("name:"):
                        # Apply to specific ElectricEquipment object by name
                        equipment_name = target.replace("name:", "").strip()
                        for equipment_obj in equipment_objects:
                            if getattr(equipment_obj, 'Name', '') == equipment_name:
                                self._apply_equipment_modifications(
                                    equipment_obj, field_updates, result
                                )
                                break
                    else:
                        result["errors"].append(f"Invalid target specification: {target}")
                        
                except Exception as e:
                    result["errors"].append(f"Error processing modification: {str(e)}")
            
            # Save the modified IDF
            idf.save(output_path)
            result["total_modifications_applied"] = len(result["modifications_applied"])
            
            logger.info(f"Applied {len(result['modifications_applied'])} modifications to ElectricEquipment objects")
            return result
            
        except Exception as e:
            logger.error(f"Error modifying ElectricEquipment objects: {e}")
            return {
                "success": False,
                "error": str(e),
                "input_file": idf_path
            }
    
    def _apply_equipment_modifications(self, equipment_obj: Any, field_updates: Dict[str, Any], 
                                      result: Dict[str, Any]) -> None:
        """Apply field updates to an ElectricEquipment object"""
        # Valid ElectricEquipment object fields based on IDD
        valid_fields = {
            "Schedule_Name",
            "Design_Level_Calculation_Method", 
            "Design_Level",
            "Watts_per_Floor_Area",
            "Watts_per_Person",
            "Fraction_Latent",
            "Fraction_Radiant",
            "Fraction_Lost",
            "EndUse_Subcategory"
        }
        
        # Fraction fields that must be between 0.0 and 1.0
        fraction_fields = {
            "Fraction_Latent",
            "Fraction_Radiant", 
            "Fraction_Lost"
        }
        
        # Numeric fields that must be >= 0
        positive_numeric_fields = {
            "Design_Level",
            "Watts_per_Floor_Area",
            "Watts_per_Person"
        }
        
        equipment_name = getattr(equipment_obj, 'Name', 'Unknown')
        
        for field_name, new_value in field_updates.items():
            if field_name not in valid_fields:
                result["errors"].append(f"Invalid field '{field_name}' for ElectricEquipment object '{equipment_name}'")
                continue
            
            try:
                # Validate calculation method change
                if field_name == "Design_Level_Calculation_Method":
                    if new_value not in self.VALID_CALCULATION_METHODS:
                        result["errors"].append(
                            f"Invalid calculation method '{new_value}' for '{equipment_name}'. "
                            f"Valid options: {list(self.VALID_CALCULATION_METHODS.keys())}"
                        )
                        continue
                
                # Validate fraction fields (0.0 to 1.0)
                if field_name in fraction_fields:
                    try:
                        float_value = float(new_value)
                        if not (0.0 <= float_value <= 1.0):
                            result["errors"].append(
                                f"Field '{field_name}' for '{equipment_name}' must be between 0.0 and 1.0, got {new_value}"
                            )
                            continue
                    except (ValueError, TypeError):
                        result["errors"].append(
                            f"Field '{field_name}' for '{equipment_name}' must be a number, got {new_value}"
                        )
                        continue
                
                # Validate positive numeric fields
                if field_name in positive_numeric_fields:
                    try:
                        float_value = float(new_value)
                        if float_value < 0.0:
                            result["errors"].append(
                                f"Field '{field_name}' for '{equipment_name}' must be >= 0.0, got {new_value}"
                            )
                            continue
                    except (ValueError, TypeError):
                        result["errors"].append(
                            f"Field '{field_name}' for '{equipment_name}' must be a number, got {new_value}"
                        )
                        continue
                
                old_value = getattr(equipment_obj, field_name, "")
                setattr(equipment_obj, field_name, new_value)
                
                result["modifications_applied"].append({
                    "object_name": equipment_name,
                    "field": field_name,
                    "old_value": old_value,
                    "new_value": new_value
                })
                
                logger.debug(f"Updated {equipment_name}.{field_name}: {old_value} -> {new_value}")
                
            except Exception as e:
                result["errors"].append(
                    f"Error setting {field_name} to {new_value} for '{equipment_name}': {str(e)}"
                )
    
    def validate_electric_equipment_modifications(self, modifications: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validate modification specifications before applying them
        
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
        
        # Valid field names based on IDD
        valid_fields = {
            "Schedule_Name",
            "Design_Level_Calculation_Method", 
            "Design_Level",
            "Watts_per_Floor_Area",
            "Watts_per_Person",
            "Fraction_Latent",
            "Fraction_Radiant",
            "Fraction_Lost",
            "EndUse_Subcategory"
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
                # Validate individual field updates
                field_updates = mod_spec["field_updates"]
                for field_name, value in field_updates.items():
                    if field_name not in valid_fields:
                        validation_result["errors"].append(
                            f"Modification {i}: Invalid field name '{field_name}'. "
                            f"Valid fields: {sorted(valid_fields)}"
                        )
                        validation_result["valid"] = False
                    
                    # Check for conflicting calculation method and values
                    if field_name == "Design_Level_Calculation_Method":
                        if value == "EquipmentLevel" and "Watts_per_Floor_Area" in field_updates:
                            validation_result["warnings"].append(
                                f"Modification {i}: Setting calculation method to 'EquipmentLevel' "
                                "but also setting 'Watts_per_Floor_Area'"
                            )
                        elif value == "Watts/Area" and "Design_Level" in field_updates:
                            validation_result["warnings"].append(
                                f"Modification {i}: Setting calculation method to 'Watts/Area' "
                                "but also setting 'Design_Level'"
                            )
                        elif value == "Watts/Person" and ("Design_Level" in field_updates or "Watts_per_Floor_Area" in field_updates):
                            validation_result["warnings"].append(
                                f"Modification {i}: Setting calculation method to 'Watts/Person' "
                                "but also setting other power values"
                            )
            
            # Validate target format
            target = mod_spec.get("target", "")
            if target and not (target == "all" or target.startswith("zone:") or target.startswith("name:")):
                validation_result["errors"].append(
                    f"Modification {i}: Invalid target format '{target}'. "
                    "Use 'all', 'zone:ZoneName', or 'name:ElectricEquipmentName'"
                )
                validation_result["valid"] = False
        
        return validation_result
