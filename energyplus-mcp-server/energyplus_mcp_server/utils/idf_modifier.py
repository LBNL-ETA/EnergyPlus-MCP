"""
IDF Modifier - Simple foundation for IDF object modifications with IDD validation.

This module provides a lightweight base class for modifying EnergyPlus IDF files
with automatic validation using the Input Data Dictionary (IDD).

Key Features:
- IDD-based field validation (no hardcoded constraints)
- Target filtering (all, zone:Name, name:Name)
- Standard result formatting
- Simple error handling with IDD context

Design Philosophy: KISS - Keep It Simple and Stupid
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

from eppy.modeleditor import IDF

logger = logging.getLogger(__name__)


class IDDValidationError(Exception):
    """Raised when IDD validation fails."""
    pass


class IDFModifier:
    """Simple foundation for IDF modifications with IDD validation.

    This class provides basic CRUD operations on IDF objects with automatic
    validation against the EnergyPlus IDD schema.
    """

    def modify_objects(
        self,
        idf_path: str,
        object_type: str,
        modifications: List[Dict[str, Any]],
        target: str = "all",
        output_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """Modify IDF objects with IDD validation.

        Args:
            idf_path: Path to input IDF file
            object_type: EnergyPlus object type (e.g., 'Lights', 'People')
            modifications: List of {field: name, value: new_value} dicts
            target: Filter pattern - "all", "zone:ZoneName", "name:ObjectName"
            output_path: Where to save (auto-generated if None)

        Returns:
            Dict with modified_objects, errors, output_file, etc.

        Example:
            modifier = IDFModifier()
            result = modifier.modify_objects(
                idf_path="model.idf",
                object_type="Lights",
                modifications=[{"field": "Watts_per_Floor_Area", "value": 8.0}],
                target="all"
            )
        """
        logger.info(f"Modifying {object_type} objects in {idf_path} with target={target}")

        # Load IDF
        try:
            idf = IDF(idf_path)
        except Exception as e:
            logger.error(f"Failed to load IDF: {e}")
            return {"success": False, "error": f"Failed to load IDF: {e}"}

        # Get objects of this type
        # Eppy uses uppercase with colons (e.g., "OUTPUTCONTROL:TABLE:STYLE")
        object_type_normalized = object_type.upper()
        objects = idf.idfobjects.get(object_type_normalized, [])

        if not objects:
            return {
                "success": False,
                "error": f"No {object_type} objects found in IDF"
            }

        # Filter targets
        target_objects = self._filter_targets(objects, target)

        if not target_objects:
            return {
                "success": False,
                "error": f"No objects match target pattern: {target}"
            }

        # Apply modifications
        result = {
            "success": True,
            "modified_objects": [],
            "errors": [],
            "input_file": idf_path,
            "object_type": object_type,
            "target": target
        }

        for obj in target_objects:
            obj_result = self._modify_single_object(obj, modifications)
            result["modified_objects"].append(obj_result)

            if obj_result.get("errors"):
                result["errors"].extend(obj_result["errors"])

        # Save if any modifications succeeded
        modified_count = sum(1 for o in result["modified_objects"] if o.get("modified_fields"))

        if modified_count > 0:
            if output_path is None:
                output_path = self._generate_output_path(idf_path)

            try:
                idf.save(output_path)
                result["output_file"] = output_path
                result["modified_count"] = modified_count
                logger.info(f"Saved modified IDF to {output_path}")
            except Exception as e:
                logger.error(f"Failed to save IDF: {e}")
                result["success"] = False
                result["errors"].append({"error": f"Failed to save IDF: {e}"})
        else:
            result["success"] = False
            result["error"] = "No modifications applied"

        return result

    def _modify_single_object(
        self,
        obj: Any,
        modifications: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Modify a single IDF object with IDD validation.

        Args:
            obj: Eppy IDF object
            modifications: List of field modifications

        Returns:
            Dict with object name, modified fields, and errors
        """
        obj_result = {
            "name": getattr(obj, "Name", "Unnamed"),
            "modified_fields": [],
            "errors": []
        }

        for mod in modifications:
            field_name = mod.get("field")
            new_value = mod.get("value")

            if not field_name:
                obj_result["errors"].append({"error": "Missing field name in modification"})
                continue

            # Validate field exists (IDD check)
            if field_name not in obj.fieldnames:
                valid_fields = ", ".join(obj.fieldnames[1:10])  # Show first 10
                obj_result["errors"].append({
                    "field": field_name,
                    "error": f"Invalid field '{field_name}'",
                    "hint": f"Valid fields include: {valid_fields}..."
                })
                continue

            # Get old value
            old_value = getattr(obj, field_name, None)

            # Get field info from IDD
            field_info = self.get_field_info(obj, field_name)

            # Apply new value
            try:
                setattr(obj, field_name, new_value)

                # Validate using IDD
                try:
                    obj.checkrange(field_name)

                    # Success - record modification
                    obj_result["modified_fields"].append({
                        "field": field_name,
                        "old_value": old_value,
                        "new_value": new_value,
                        "field_type": field_info.get("type"),
                        "units": field_info.get("units")
                    })

                    logger.debug(f"Modified {field_name}: {old_value} → {new_value}")

                except Exception as range_error:
                    # IDD validation failed - revert
                    setattr(obj, field_name, old_value)

                    constraints = obj.getrange(field_name) if hasattr(obj, 'getrange') else {}

                    error_msg = f"Value {new_value} out of range"
                    if constraints.get('minimum') is not None:
                        error_msg += f", min: {constraints['minimum']}"
                    if constraints.get('maximum') is not None:
                        error_msg += f", max: {constraints['maximum']}"
                    if field_info.get('units'):
                        error_msg += f" ({field_info['units']})"

                    obj_result["errors"].append({
                        "field": field_name,
                        "value": new_value,
                        "error": error_msg,
                        "constraints": constraints
                    })

                    logger.warning(f"IDD validation failed for {field_name}: {range_error}")

            except Exception as e:
                obj_result["errors"].append({
                    "field": field_name,
                    "error": str(e)
                })
                logger.error(f"Error modifying {field_name}: {e}")

        return obj_result

    def get_field_info(self, obj: Any, field_name: str) -> Dict[str, Any]:
        """Get field metadata from IDD.

        Args:
            obj: Eppy IDF object
            field_name: Field name to query

        Returns:
            Dict with type, units, required, constraints, etc.
        """
        try:
            field_idd = obj.getfieldidd(field_name)

            return {
                "name": field_name,
                "type": field_idd.get('type', ['unknown'])[0],
                "units": field_idd.get('units', [''])[0],
                "required": 'required-field' in field_idd,
                "default": field_idd.get('default', [''])[0],
                "autosizable": 'autosizable' in field_idd,
                "autocalculatable": 'autocalculatable' in field_idd,
                "constraints": obj.getrange(field_name) if hasattr(obj, 'getrange') else {}
            }
        except Exception as e:
            logger.warning(f"Failed to get field info for {field_name}: {e}")
            return {"name": field_name, "type": "unknown"}

    def _filter_targets(
        self,
        objects: List[Any],
        target: str
    ) -> List[Any]:
        """Filter objects based on target pattern.

        Args:
            objects: List of IDF objects
            target: Filter pattern
                - "all": All objects
                - "zone:ZoneName": Objects in specific zone
                - "name:ObjectName": Object with specific name

        Returns:
            Filtered list of objects
        """
        if target == "all":
            return objects

        if target.startswith("zone:"):
            zone_name = target.replace("zone:", "").strip()
            filtered = []
            for obj in objects:
                # Try common zone field names
                zone_field = (
                    getattr(obj, "Zone_or_ZoneList_Name", None) or
                    getattr(obj, "Zone_Name", None) or
                    getattr(obj, "Zone_or_ZoneList_or_Space_or_SpaceList_Name", None)
                )
                if zone_field == zone_name:
                    filtered.append(obj)
            return filtered

        if target.startswith("name:"):
            object_name = target.replace("name:", "").strip()
            for obj in objects:
                if getattr(obj, "Name", "") == object_name:
                    return [obj]
            return []

        # Unknown target pattern - return all
        logger.warning(f"Unknown target pattern '{target}', returning all objects")
        return objects

    def add_object(
        self,
        idf_path: str,
        object_type: str,
        fields: Dict[str, Any],
        output_path: Optional[str] = None,
        replace_existing: bool = True
    ) -> Dict[str, Any]:
        """Add a new IDF object with IDD validation.

        Args:
            idf_path: Path to input IDF file
            object_type: EnergyPlus object type (e.g., 'OutputControl:Table:Style')
            fields: Dictionary of field names and values
            output_path: Where to save (auto-generated if None)
            replace_existing: If True and object exists, modify it instead of creating duplicate (default: True)

        Returns:
            Dict with success status, new object info, and errors

        Example:
            modifier = IDFModifier()
            result = modifier.add_object(
                idf_path="model.idf",
                object_type="OutputControl:Table:Style",
                fields={
                    "Column_Separator": "CommaAndHTML",
                    "Unit_Conversion": "JtoKWH"
                }
            )
        """
        logger.info(f"Adding new {object_type} object to {idf_path}")

        # Load IDF
        try:
            idf = IDF(idf_path)
        except Exception as e:
            logger.error(f"Failed to load IDF: {e}")
            return {"success": False, "error": f"Failed to load IDF: {e}"}

        # Normalize object type - try to preserve original case by checking existing objects
        object_type_normalized = object_type.upper()

        # Check if objects of this type already exist (case-insensitive search)
        existing_objects = []
        for key in idf.idfobjects.keys():
            if key.upper() == object_type_normalized:
                existing_objects = idf.idfobjects[key]
                object_type_normalized = key  # Use the existing case
                break

        # Determine if this is a singleton object type
        # Normalize for comparison (remove colons and spaces)
        singleton_types = {
            'SIMULATIONCONTROL', 'BUILDING', 'GLOBALGEOMETRYRULES',
            'SHADOWCALCULATION', 'HEATBALANCEALGORITHM', 'TIMESTEP',
            'CONVERGANCELIMITS', 'PROGRAMCONTROL', 'VERSION',
            'OUTPUTCONTROLTABLESTYLE', 'OUTPUTCONTROLREPORTINGTOLERANCES',
            'OUTPUTCONTROLSIZINGSTYLE', 'OUTPUTDIAGNOSTICS',
            'PERFORMANCEPRECISIONTRADEOFFS', 'LIFECYCLECOSTPARAMETERS'
        }

        is_singleton = object_type_normalized.replace(':', '').replace(' ', '') in singleton_types

        # If object exists and replace_existing is True, modify instead of creating duplicate
        if existing_objects and replace_existing:
            logger.info(f"Found {len(existing_objects)} existing {object_type} object(s). "
                       f"{'Modifying first instance (singleton)' if is_singleton else 'Modifying existing objects'}.")

            # For singleton types, modify the first (and should be only) instance
            if is_singleton:
                existing_obj = existing_objects[0]
                return self._modify_existing_object(
                    idf=idf,
                    obj=existing_obj,
                    object_type=object_type,
                    fields=fields,
                    idf_path=idf_path,
                    output_path=output_path
                )

        # If object exists but replace_existing is False, warn about potential duplicate
        if existing_objects and not replace_existing:
            logger.warning(f"Creating new {object_type} object, but {len(existing_objects)} already exist. "
                          f"This may create duplicates.")

        # Create new object
        try:
            new_obj = idf.newidfobject(object_type_normalized)
        except Exception as e:
            logger.error(f"Failed to create {object_type} object: {e}")
            return {
                "success": False,
                "error": f"Failed to create {object_type} object: {e}. Object type may not exist in IDD."
            }

        # Track what we set
        set_fields = []
        errors = []

        # Apply field values with IDD validation
        for field_name, value in fields.items():
            try:
                # Check if field exists in IDD
                if not hasattr(new_obj, field_name):
                    # Get valid fields from IDD
                    valid_fields = new_obj.fieldnames if hasattr(new_obj, 'fieldnames') else []
                    errors.append({
                        "field": field_name,
                        "error": f"Field '{field_name}' not found in {object_type}",
                        "valid_fields": valid_fields[:10]  # Show first 10 valid fields
                    })
                    continue

                # Set the value
                setattr(new_obj, field_name, value)

                # Validate with IDD
                try:
                    if hasattr(new_obj, 'checkrange'):
                        new_obj.checkrange(field_name)
                except Exception as range_error:
                    # Get IDD constraints for error message
                    field_info = self.get_field_info(new_obj, field_name)
                    errors.append({
                        "field": field_name,
                        "error": f"IDD validation failed: {range_error}",
                        "constraints": field_info.get("constraints", {}),
                        "value_attempted": value
                    })
                    # Revert the change
                    setattr(new_obj, field_name, "")
                    continue

                set_fields.append({
                    "field": field_name,
                    "value": value
                })

            except Exception as e:
                errors.append({
                    "field": field_name,
                    "error": str(e)
                })

        # Save the modified IDF
        if not output_path:
            output_path = self._generate_output_path(idf_path)

        try:
            idf.save(output_path)
            logger.info(f"Saved IDF with new {object_type} to {output_path}")
        except Exception as e:
            logger.error(f"Failed to save IDF: {e}")
            return {"success": False, "error": f"Failed to save IDF: {e}"}

        # Build result
        result = {
            "success": len(set_fields) > 0,
            "input_file": idf_path,
            "output_file": output_path,
            "object_type": object_type,
            "object_created": True,
            "fields_set": set_fields,
            "fields_set_count": len(set_fields),
            "errors": errors
        }

        if errors:
            result["warnings"] = f"{len(errors)} field(s) had errors"

        return result

    def _modify_existing_object(
        self,
        idf: Any,
        obj: Any,
        object_type: str,
        fields: Dict[str, Any],
        idf_path: str,
        output_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """Modify an existing IDF object instead of creating a new one.

        Args:
            idf: Loaded IDF object
            obj: Existing IDF object to modify
            object_type: Object type name
            fields: Fields to update
            idf_path: Input file path
            output_path: Output file path

        Returns:
            Dict with modification results
        """
        logger.info(f"Modifying existing {object_type} object instead of creating duplicate")

        set_fields = []
        errors = []

        # Apply field values with IDD validation
        for field_name, value in fields.items():
            try:
                # Check if field exists in IDD
                if not hasattr(obj, field_name):
                    # Get valid fields from IDD
                    valid_fields = obj.fieldnames if hasattr(obj, 'fieldnames') else []
                    errors.append({
                        "field": field_name,
                        "error": f"Field '{field_name}' not found in {object_type}",
                        "valid_fields": valid_fields[:10]  # Show first 10 valid fields
                    })
                    continue

                # Get old value
                old_value = getattr(obj, field_name, None)

                # Set the value
                setattr(obj, field_name, value)

                # Validate with IDD
                try:
                    if hasattr(obj, 'checkrange'):
                        obj.checkrange(field_name)

                    # Success
                    set_fields.append({
                        "field": field_name,
                        "old_value": old_value,
                        "new_value": value
                    })
                    logger.debug(f"Modified {field_name}: {old_value} → {value}")

                except Exception as range_error:
                    # Get IDD constraints for error message
                    field_info = self.get_field_info(obj, field_name)
                    errors.append({
                        "field": field_name,
                        "error": f"IDD validation failed: {range_error}",
                        "constraints": field_info.get("constraints", {}),
                        "value_attempted": value
                    })
                    # Revert the change
                    setattr(obj, field_name, old_value)
                    continue

            except Exception as e:
                errors.append({
                    "field": field_name,
                    "error": str(e)
                })

        # Save the modified IDF
        if not output_path:
            output_path = self._generate_output_path(idf_path)

        try:
            idf.save(output_path)
            logger.info(f"Saved IDF with modified {object_type} to {output_path}")
        except Exception as e:
            logger.error(f"Failed to save IDF: {e}")
            return {"success": False, "error": f"Failed to save IDF: {e}"}

        # Build result
        result = {
            "success": len(set_fields) > 0,
            "input_file": idf_path,
            "output_file": output_path,
            "object_type": object_type,
            "object_created": False,
            "object_modified": True,
            "existing_object_updated": True,
            "fields_set": set_fields,
            "fields_set_count": len(set_fields),
            "errors": errors
        }

        if errors:
            result["warnings"] = f"{len(errors)} field(s) had errors"

        return result

    def delete_objects(
        self,
        idf_path: str,
        object_type: str,
        target: str = "all",
        output_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """Delete IDF objects matching the target pattern.

        Args:
            idf_path: Path to input IDF file
            object_type: EnergyPlus object type (e.g., 'Lights', 'People')
            target: Filter pattern - "all", "zone:ZoneName", "name:ObjectName"
            output_path: Where to save (auto-generated if None)

        Returns:
            Dict with deleted_objects, errors, output_file, etc.

        Example:
            modifier = IDFModifier()
            result = modifier.delete_objects(
                idf_path="model.idf",
                object_type="Lights",
                target="name:SPACE1-1 Lights"
            )
        """
        logger.info(f"Deleting {object_type} objects in {idf_path} with target={target}")

        # Load IDF
        try:
            idf = IDF(idf_path)
        except Exception as e:
            logger.error(f"Failed to load IDF: {e}")
            return {"success": False, "error": f"Failed to load IDF: {e}"}

        # Get objects of this type
        object_type_normalized = object_type.upper()
        objects = idf.idfobjects.get(object_type_normalized, [])

        if not objects:
            return {
                "success": False,
                "error": f"No {object_type} objects found in IDF"
            }

        # Filter targets
        target_objects = self._filter_targets(objects, target)

        if not target_objects:
            return {
                "success": False,
                "error": f"No objects match target pattern: {target}"
            }

        # Track deleted objects
        deleted_objects = []
        errors = []

        # Delete each target object
        for obj in target_objects:
            try:
                obj_name = getattr(obj, "Name", "Unnamed")

                # Remove the object from IDF
                idf.removeidfobject(obj)

                deleted_objects.append({
                    "name": obj_name,
                    "object_type": object_type
                })

                logger.debug(f"Deleted {object_type}: {obj_name}")

            except Exception as e:
                obj_name = getattr(obj, "Name", "Unnamed")
                errors.append({
                    "name": obj_name,
                    "error": str(e)
                })
                logger.error(f"Error deleting {obj_name}: {e}")

        # Build result
        result = {
            "success": len(deleted_objects) > 0,
            "deleted_objects": deleted_objects,
            "deleted_count": len(deleted_objects),
            "errors": errors,
            "input_file": idf_path,
            "object_type": object_type,
            "target": target
        }

        # Save if any deletions succeeded
        if len(deleted_objects) > 0:
            if output_path is None:
                output_path = self._generate_output_path(idf_path)

            try:
                idf.save(output_path)
                result["output_file"] = output_path
                logger.info(f"Saved modified IDF to {output_path}")
            except Exception as e:
                logger.error(f"Failed to save IDF: {e}")
                result["success"] = False
                result["errors"].append({"error": f"Failed to save IDF: {e}"})
        else:
            result["success"] = False
            result["error"] = "No objects were deleted"

        return result

    def _generate_output_path(self, input_path: str) -> str:
        """Generate timestamped output path.

        Args:
            input_path: Input IDF path

        Returns:
            Output path with timestamp
        """
        path_obj = Path(input_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return str(path_obj.parent / f"{path_obj.stem}_modified_{timestamp}.idf")
