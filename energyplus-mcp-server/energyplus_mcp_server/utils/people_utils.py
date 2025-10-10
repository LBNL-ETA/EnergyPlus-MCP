"""
People object utility module for EnergyPlus MCP Server.
Handles inspection and modification of People objects in EnergyPlus models.

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


class PeopleManager:
    """Manager for EnergyPlus People objects"""
    
    # Valid calculation methods for Number of People
    VALID_CALCULATION_METHODS = {
        "People": "Direct number of people",
        "People/Area": "People per floor area (people/m2)", 
        "Area/Person": "Floor area per person (m2/person)"
    }
    
    # Common activity levels (W/person) - from ASHRAE
    COMMON_ACTIVITY_LEVELS = {
        "Seated, quiet": 108,
        "Seated, light work": 126,
        "Standing, relaxed": 126,
        "Standing, light work": 207,
        "Walking": 207,
        "Light bench work": 234
    }
    
    def __init__(self):
        """Initialize the People manager"""
        pass
    
    def get_people_objects(self, idf_path: str) -> Dict[str, Any]:
        """
        Get all People objects from the IDF file with detailed information
        
        Args:
            idf_path: Path to the IDF file
            
        Returns:
            Dictionary with people objects information
        """
        try:
            idf = IDF(idf_path)
            people_objects = idf.idfobjects.get("People", [])
            
            result = {
                "success": True,
                "file_path": idf_path,
                "total_people_objects": len(people_objects),
                "people_objects": [],
                "summary": {
                    "by_calculation_method": {},
                    "by_zone": {},
                    "total_design_occupancy": 0.0
                }
            }
            
            # Get all zones for reference
            zones = {zone.Name: zone for zone in idf.idfobjects.get("Zone", [])}
            
            for people_obj in people_objects:
                people_info = {
                    "name": getattr(people_obj, 'Name', 'Unknown'),
                    "zone_or_zonelist": getattr(people_obj, 'Zone_or_ZoneList_Name', 'Unknown'),
                    "schedule": getattr(people_obj, 'Number_of_People_Schedule_Name', 'Unknown'),
                    "calculation_method": getattr(people_obj, 'Number_of_People_Calculation_Method', 'Unknown'),
                    "number_of_people": getattr(people_obj, 'Number_of_People', ''),
                    "people_per_area": getattr(people_obj, 'People_per_Floor_Area', ''),
                    "area_per_person": getattr(people_obj, 'Floor_Area_per_Person', ''),
                    "fraction_radiant": getattr(people_obj, 'Fraction_Radiant', ''),
                    "sensible_heat_fraction": getattr(people_obj, 'Sensible_Heat_Fraction', ''),
                    "activity_schedule": getattr(people_obj, 'Activity_Level_Schedule_Name', ''),
                    "co2_generation_rate": getattr(people_obj, 'Carbon_Dioxide_Generation_Rate', ''),
                    "clothing_insulation_schedule": getattr(people_obj, 'Clothing_Insulation_Schedule_Name', ''),
                    "air_velocity_schedule": getattr(people_obj, 'Air_Velocity_Schedule_Name', ''),
                    "work_efficiency_schedule": getattr(people_obj, 'Work_Efficiency_Schedule_Name', ''),
                    "thermal_comfort_model_1": getattr(people_obj, 'Thermal_Comfort_Model_1_Type', ''),
                    "thermal_comfort_model_2": getattr(people_obj, 'Thermal_Comfort_Model_2_Type', '')
                }
                
                # Calculate design occupancy if possible
                design_occupancy = self._calculate_design_occupancy(
                    people_info, zones.get(people_info["zone_or_zonelist"])
                )
                people_info["design_occupancy"] = design_occupancy
                
                result["people_objects"].append(people_info)
                
                # Update summaries
                calc_method = people_info["calculation_method"]
                if calc_method:
                    result["summary"]["by_calculation_method"][calc_method] = \
                        result["summary"]["by_calculation_method"].get(calc_method, 0) + 1
                
                zone_name = people_info["zone_or_zonelist"]
                if zone_name:
                    if zone_name not in result["summary"]["by_zone"]:
                        result["summary"]["by_zone"][zone_name] = []
                    result["summary"]["by_zone"][zone_name].append(people_info["name"])
                
                if design_occupancy is not None:
                    result["summary"]["total_design_occupancy"] += design_occupancy
            
            logger.info(f"Found {len(people_objects)} People objects in {idf_path}")
            return result
            
        except Exception as e:
            logger.error(f"Error getting People objects: {e}")
            return {
                "success": False,
                "error": str(e),
                "file_path": idf_path
            }
    
    def _calculate_design_occupancy(self, people_info: Dict[str, Any], 
                                   zone_obj: Optional[Any]) -> Optional[float]:
        """Calculate design occupancy based on calculation method and zone data"""
        try:
            calc_method = people_info["calculation_method"]
            
            if calc_method == "People":
                value = people_info["number_of_people"]
                if value and value != '':
                    return float(value)
                    
            elif calc_method == "People/Area" and zone_obj:
                people_per_area = people_info["people_per_area"]
                if people_per_area and people_per_area != '':
                    # Get zone floor area
                    floor_area = getattr(zone_obj, 'Floor_Area', None)
                    if floor_area and floor_area != '' and floor_area != 'autocalculate':
                        return float(people_per_area) * float(floor_area)
                        
            elif calc_method == "Area/Person" and zone_obj:
                area_per_person = people_info["area_per_person"]
                if area_per_person and area_per_person != '' and float(area_per_person) > 0:
                    # Get zone floor area
                    floor_area = getattr(zone_obj, 'Floor_Area', None)
                    if floor_area and floor_area != '' and floor_area != 'autocalculate':
                        return float(floor_area) / float(area_per_person)
            
        except (ValueError, TypeError) as e:
            logger.warning(f"Could not calculate design occupancy: {e}")
        
        return None
    
    def modify_people_objects(self, idf_path: str, modifications: List[Dict[str, Any]], 
                            output_path: str) -> Dict[str, Any]:
        """
        Modify People objects in the IDF file
        
        Args:
            idf_path: Path to the input IDF file
            modifications: List of modification specifications
            output_path: Path for the output IDF file
            
        Returns:
            Dictionary with modification results
        """
        try:
            idf = IDF(idf_path)
            people_objects = idf.idfobjects.get("People", [])
            
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
                        # Apply to all People objects
                        for people_obj in people_objects:
                            self._apply_people_modifications(
                                people_obj, field_updates, result
                            )
                    elif target.startswith("zone:"):
                        # Apply to People objects in specific zone
                        zone_name = target.replace("zone:", "").strip()
                        for people_obj in people_objects:
                            if getattr(people_obj, 'Zone_or_ZoneList_Name', '') == zone_name:
                                self._apply_people_modifications(
                                    people_obj, field_updates, result
                                )
                    elif target.startswith("name:"):
                        # Apply to specific People object by name
                        people_name = target.replace("name:", "").strip()
                        for people_obj in people_objects:
                            if getattr(people_obj, 'Name', '') == people_name:
                                self._apply_people_modifications(
                                    people_obj, field_updates, result
                                )
                                break
                    else:
                        result["errors"].append(f"Invalid target specification: {target}")
                        
                except Exception as e:
                    result["errors"].append(f"Error processing modification: {str(e)}")
            
            # Save the modified IDF
            idf.save(output_path)
            result["total_modifications_applied"] = len(result["modifications_applied"])
            
            logger.info(f"Applied {len(result['modifications_applied'])} modifications to People objects")
            return result
            
        except Exception as e:
            logger.error(f"Error modifying People objects: {e}")
            return {
                "success": False,
                "error": str(e),
                "input_file": idf_path
            }
    
    def _apply_people_modifications(self, people_obj: Any, field_updates: Dict[str, Any], 
                                   result: Dict[str, Any]) -> None:
        """Apply field updates to a People object"""
        # Valid People object fields
        valid_fields = {
            "Number_of_People_Schedule_Name",
            "Number_of_People_Calculation_Method", 
            "Number_of_People",
            "People_per_Floor_Area",
            "Floor_Area_per_Person",
            "Fraction_Radiant",
            "Sensible_Heat_Fraction",
            "Activity_Level_Schedule_Name",
            "Carbon_Dioxide_Generation_Rate",
            "Enable_ASHRAE_55_Comfort_Warnings",
            "Mean_Radiant_Temperature_Calculation_Type",
            "Surface_Name_or_Angle_Factor_List_Name",
            "Work_Efficiency_Schedule_Name",
            "Clothing_Insulation_Schedule_Name",
            "Air_Velocity_Schedule_Name",
            "Thermal_Comfort_Model_1_Type",
            "Thermal_Comfort_Model_2_Type"
        }
        
        people_name = getattr(people_obj, 'Name', 'Unknown')
        
        for field_name, new_value in field_updates.items():
            if field_name not in valid_fields:
                result["errors"].append(f"Invalid field '{field_name}' for People object '{people_name}'")
                continue
            
            try:
                # Validate calculation method change
                if field_name == "Number_of_People_Calculation_Method":
                    if new_value not in self.VALID_CALCULATION_METHODS:
                        result["errors"].append(
                            f"Invalid calculation method '{new_value}' for '{people_name}'"
                        )
                        continue
                
                old_value = getattr(people_obj, field_name, "")
                setattr(people_obj, field_name, new_value)
                
                result["modifications_applied"].append({
                    "object_name": people_name,
                    "field": field_name,
                    "old_value": old_value,
                    "new_value": new_value
                })
                
                logger.debug(f"Updated {people_name}.{field_name}: {old_value} -> {new_value}")
                
            except Exception as e:
                result["errors"].append(
                    f"Error setting {field_name} to {new_value} for '{people_name}': {str(e)}"
                )
    
    def validate_people_modifications(self, modifications: List[Dict[str, Any]]) -> Dict[str, Any]:
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
            
            # Validate target format
            target = mod_spec.get("target", "")
            if target and not (target == "all" or target.startswith("zone:") or target.startswith("name:")):
                validation_result["errors"].append(
                    f"Modification {i}: Invalid target format '{target}'. "
                    "Use 'all', 'zone:ZoneName', or 'name:PeopleName'"
                )
                validation_result["valid"] = False
        
        return validation_result
