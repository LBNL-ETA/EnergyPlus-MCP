"""
Generic IDF modification tool - domain-agnostic direct modifications.

This tool provides low-level access to modify any IDF object when the user
knows the exact object type and field names. It performs IDD validation but
no business logic validation.

Use this for:
- Direct modifications when field names are known (e.g., OutputControl:Table:Style)
- Singleton object modifications
- Any object type not covered by domain managers

For semantic operations (e.g., "reduce lighting power density"), use domain managers instead.
"""

from typing import Any, Dict, Optional, Literal, List
import json
import logging

from energyplus_mcp_server.utils.idf_modifier import IDFModifier

logger = logging.getLogger(__name__)


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    """Register the generic IDF modification tool"""
    logger.info("tools.idf_modification.register starting")

    @mcp.tool()
    async def idf_modification(
        action: Literal["modify", "add", "delete", "capabilities"],
        idf_path: Optional[str] = None,
        object_type: Optional[str] = None,
        fields: Optional[Dict[str, Any]] = None,
        target: str = "all",
        output_path: Optional[str] = None,
    ) -> str:
        """
        Generic IDF modification tool for direct object modifications.

        This tool provides low-level access to modify or add any EnergyPlus object type
        when you know the exact field names. It performs IDD validation automatically.

        Actions:
        - modify: Modify existing IDF objects with specified field values
        - add: Add a new IDF object with specified field values
        - delete: Delete IDF objects matching the target pattern
        - capabilities: Show available actions and parameters

        Parameters:
        - idf_path: Path to the IDF file
        - object_type: EnergyPlus object type (e.g., "OutputControl:Table:Style", "Lights", "Zone")
        - fields: Dictionary of field names and values to modify
        - target: Target filter - "all", "name:ObjectName", or "zone:ZoneName" (default: "all")
        - output_path: Optional output path (if not specified, creates modified copy)

        Examples:
        1. Add OutputControl:Table:Style (if doesn't exist):
           {
             "action": "add",
             "idf_path": "model.idf",
             "object_type": "OutputControl:Table:Style",
             "fields": {
               "Column_Separator": "CommaAndHTML",
               "Unit_Conversion": "JtoKWH"
             }
           }

        2. Modify OutputControl:Table:Style (if exists):
           {
             "action": "modify",
             "idf_path": "model.idf",
             "object_type": "OutputControl:Table:Style",
             "fields": {
               "Column_Separator": "CommaAndHTML",
               "Unit_Conversion": "InchPound"
             }
           }

        3. Modify specific Lights object:
           {
             "action": "modify",
             "idf_path": "model.idf",
             "object_type": "Lights",
             "target": "name:SPACE1-1 Lights",
             "fields": {
               "Watts_per_Floor_Area": 10.0,
               "Fraction_Radiant": 0.4
             }
           }

        4. Modify all lights in a zone:
           {
             "action": "modify",
             "idf_path": "model.idf",
             "object_type": "Lights",
             "target": "zone:SPACE1-1",
             "fields": {
               "Watts_per_Floor_Area": 8.0
             }
           }

        5. Delete a specific object:
           {
             "action": "delete",
             "idf_path": "model.idf",
             "object_type": "Lights",
             "target": "name:SPACE1-1 Lights"
           }

        6. Delete all objects of a type in a zone:
           {
             "action": "delete",
             "idf_path": "model.idf",
             "object_type": "ElectricEquipment",
             "target": "zone:SPACE1-1"
           }

        Note: For semantic operations like "reduce lighting power density",
        use domain-specific managers (e.g., lights_manager) instead.
        """
        try:
            if action == "capabilities":
                return json.dumps({
                    "tool": "idf_modification",
                    "description": "Generic domain-agnostic IDF modification with IDD validation",
                    "actions": [
                        {
                            "name": "modify",
                            "required": ["idf_path", "object_type", "fields"],
                            "optional": ["target", "output_path"],
                            "description": "Modify existing IDF objects with IDD validation"
                        },
                        {
                            "name": "add",
                            "required": ["idf_path", "object_type", "fields"],
                            "optional": ["output_path"],
                            "description": "Add a new IDF object with IDD validation"
                        },
                        {
                            "name": "delete",
                            "required": ["idf_path", "object_type"],
                            "optional": ["target", "output_path"],
                            "description": "Delete IDF objects matching target pattern"
                        }
                    ],
                    "target_formats": [
                        "all - Apply to all objects of this type",
                        "name:ObjectName - Apply to specific object by name",
                        "zone:ZoneName - Apply to objects in specific zone (if applicable)"
                    ],
                    "validation": "Automatic IDD validation (field names, ranges, types)",
                    "use_cases": [
                        "Singleton object modifications (OutputControl:Table:Style, SimulationControl, etc.)",
                        "Direct field modifications when exact field names are known",
                        "Bulk modifications across multiple objects"
                    ],
                    "alternatives": {
                        "lights_manager": "For semantic lighting operations",
                        "people_manager": "For semantic occupancy operations",
                        "outputs_manager": "For Output:Variable and Output:Meter management"
                    }
                }, indent=2)

            # Validate required parameters
            if not idf_path:
                return json.dumps({"error": "Missing required parameter: idf_path"}, indent=2)

            if not object_type:
                return json.dumps({"error": "Missing required parameter: object_type"}, indent=2)

            if action == "modify":
                # Validate fields for modify action
                if not fields:
                    return json.dumps({"error": "Missing required parameter: fields"}, indent=2)
                # Use IDFModifier for the actual modification
                modifier = IDFModifier()

                # Convert fields dict to list format for IDFModifier
                modifications = [{"field": k, "value": v} for k, v in fields.items()]

                # Perform modification with IDD validation
                result = modifier.modify_objects(
                    idf_path=idf_path,
                    object_type=object_type,
                    modifications=modifications,
                    target=target,
                    output_path=output_path
                )

                # Add tool metadata to result
                result["tool"] = "idf_modification"
                result["modification_type"] = "direct"

                return json.dumps(result, indent=2)

            if action == "add":
                # Validate fields for add action
                if not fields:
                    return json.dumps({"error": "Missing required parameter: fields"}, indent=2)

                # Use IDFModifier to add a new object
                modifier = IDFModifier()

                # Perform object creation with IDD validation
                result = modifier.add_object(
                    idf_path=idf_path,
                    object_type=object_type,
                    fields=fields,
                    output_path=output_path
                )

                # Add tool metadata to result
                result["tool"] = "idf_modification"
                result["modification_type"] = "add"

                return json.dumps(result, indent=2)

            if action == "delete":
                # Use IDFModifier to delete objects
                modifier = IDFModifier()

                # Perform deletion
                result = modifier.delete_objects(
                    idf_path=idf_path,
                    object_type=object_type,
                    target=target,
                    output_path=output_path
                )

                # Add tool metadata to result
                result["tool"] = "idf_modification"
                result["modification_type"] = "delete"

                return json.dumps(result, indent=2)

            return json.dumps({"error": f"Unsupported action: {action}"}, indent=2)

        except FileNotFoundError as e:
            logger.warning(f"IDF modification file not found: {str(e)}")
            return json.dumps({"error": f"File not found: {str(e)}"}, indent=2)
        except Exception as e:
            logger.error(f"idf_modification error: {str(e)}")
            return json.dumps({"error": f"Error in idf_modification: {str(e)}"}, indent=2)
