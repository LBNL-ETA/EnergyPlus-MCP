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
from pathlib import Path

from energyplus_mcp_server.utils.idf_modifier import IDFModifier
from energyplus_mcp_server.utils.path_utils import resolve_idf_path, work_dir

logger = logging.getLogger(__name__)


def _same_file(first: str, second: str) -> bool:
    try:
        return Path(first).expanduser().resolve() == Path(second).expanduser().resolve()
    except OSError:
        return False


def _is_within(path: str, folder: str) -> bool:
    try:
        Path(path).expanduser().resolve().relative_to(Path(folder).expanduser().resolve())
        return True
    except (ValueError, OSError):
        return False


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    """Register the generic IDF modification tool"""
    logger.info("tools.idf_modification.register starting")

    @mcp.tool()
    async def idf_modification(
        action: Literal["find", "modify", "add", "delete", "capabilities"],
        idf_path: Optional[str] = None,
        object_type: Optional[str] = None,
        fields: Optional[Dict[str, Any]] = None,
        target: str = "all",
        output_path: Optional[str] = None,
        references: Optional[str] = None,
        name_contains: Optional[str] = None,
        limit: Optional[int] = None,
        force: bool = False,
        mode: Literal["apply", "dry_run"] = "apply",
    ) -> str:
        """
        Generic IDF modification tool for direct object modifications.

        This tool provides low-level access to modify or add any EnergyPlus object type
        when you know the exact field names. It performs IDD validation automatically.

        Actions:
        - find: Read-only lookup. Objects of `object_type` (exact or wildcard such
          as "SetpointManager:*"), objects with any field equal to `references`
          (a node, schedule, construction, or other name; case-insensitive), or
          both; narrow with `name_contains`. When the name sits in a *NodeList,
          objects that use that list are returned too, marked "via". Each match
          has role "defines" (the object named that) or "references". Returns
          the eppy field names that modify accepts. Never writes a file.
        - modify: Modify existing IDF objects with specified field values
        - add: Add a new IDF object with specified field values
        - delete: Delete IDF objects matching the target pattern
        - capabilities: Show available actions and parameters

        Safety rules for modify/add/delete:
        - All or nothing: if any requested change is invalid, nothing is saved
          and every problem is listed in errors.
        - Checked against the IDD: field names (case-insensitive), numeric
          ranges, allowed choice values, and references to other objects (a
          Schedule_Name must name a schedule that exists). add refuses a
          duplicate name.
        - delete refuses to remove an object other objects still use, and
          renaming such an object is refused; the reply lists the users.
          force=True accepts missing references and broken uses (reported as
          warnings); it never accepts invalid fields, values or duplicates.
        - target must be "all", "name:<name>" or "zone:<zone>"; names and zones
          match case-insensitively; anything else is refused.
        - An original model is never overwritten: output_path may equal
          idf_path only for a working copy in models/derived/ (where
          file_utils copy puts copies).
        - mode="dry_run" checks everything and reports the planned changes
          without writing.

        Parameters:
        - idf_path: Path to the IDF file
        - object_type: EnergyPlus object type (e.g., "OutputControl:Table:Style", "Lights", "Zone")
        - fields: Dictionary of field names and values to modify
        - target: Target filter - "all", "name:ObjectName", or "zone:ZoneName" (default: "all")
        - references: (find) Name to look for in any field
        - name_contains: (find) Case-insensitive substring of the object Name
        - limit: (find) Objects returned, 1-100 (default 20); total_matches counts all
        - output_path: Optional output path (if not specified, writes a timestamped copy
          to work/models/derived/). Paths inside sample_files/ or the EnergyPlus
          installation are rejected; those inputs are read-only. May equal
          idf_path only for a working copy in models/derived/.
        - force: Accept references to missing objects, and deletes/renames that
          break references (default False)
        - mode: "apply" (default) or "dry_run" to validate without writing

        Examples:
        0. Which setpoint managers set a node (directly or through a NodeList)?
           {
             "action": "find",
             "idf_path": "model.idf",
             "object_type": "SetpointManager:*",
             "references": "CW Supply Outlet Node"
           }

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

        Before adding an object type you have not modelled, follow
        get_skill("learn-from-examples"): example_library returns objects from
        EnergyPlus's example models with the field names this tool accepts.
        """
        try:
            if action == "capabilities":
                return json.dumps({
                    "tool": "idf_modification",
                    "description": "Generic domain-agnostic IDF modification with IDD validation",
                    "actions": [
                        {
                            "name": "find",
                            "required": ["idf_path", "object_type or references"],
                            "optional": ["name_contains", "limit"],
                            "description": "Read-only lookup by type (wildcards allowed) and/or a referenced name; never writes"
                        },
                        {
                            "name": "modify",
                            "required": ["idf_path", "object_type", "fields"],
                            "optional": ["target", "output_path", "force", "mode"],
                            "description": "Modify existing IDF objects with IDD validation; all or nothing"
                        },
                        {
                            "name": "add",
                            "required": ["idf_path", "object_type", "fields"],
                            "optional": ["output_path", "force", "mode"],
                            "description": "Add a new IDF object with IDD validation; duplicate names refused"
                        },
                        {
                            "name": "delete",
                            "required": ["idf_path", "object_type"],
                            "optional": ["target", "output_path", "force", "mode"],
                            "description": "Delete IDF objects matching target pattern; refused while other objects use them"
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

            if not object_type and not (action == "find" and references):
                return json.dumps({"error": "Missing required parameter: object_type"}, indent=2)

            # Accept the same bare or relative names as the other tools, e.g. a
            # model copied into work/models/derived.
            idf_path = resolve_idf_path(config, idf_path)
            dry_run = mode == "dry_run"
            if (action in {"modify", "add", "delete"} and output_path
                    and _same_file(output_path, idf_path)
                    and not _is_within(idf_path, work_dir(config, "derived"))):
                return json.dumps({
                    "success": False, "saved": False,
                    "error": "output_path is the source model, which is never overwritten. Choose a new "
                             "output_path, omit it, or copy the model first (file_utils copy puts the "
                             "copy in models/derived/, where it can be edited in place).",
                }, indent=2)

            if action == "find":
                result = IDFModifier().find_objects(
                    idf_path=idf_path,
                    object_type=object_type,
                    references=references,
                    name_contains=name_contains,
                    limit=limit or 20,
                )
                result["tool"] = "idf_modification"
                result["action"] = "find"
                return json.dumps(result, indent=2, default=str)

            if action == "modify":
                # Validate fields for modify action
                if not fields:
                    return json.dumps({"error": "Missing required parameter: fields"}, indent=2)
                # Use IDFModifier for the actual modification
                modifier = IDFModifier(output_dir=work_dir(config, "derived"))

                # Convert fields dict to list format for IDFModifier
                modifications = [{"field": k, "value": v} for k, v in fields.items()]

                # Perform modification with IDD validation
                result = modifier.modify_objects(
                    idf_path=idf_path,
                    object_type=object_type,
                    modifications=modifications,
                    target=target,
                    output_path=output_path,
                    force=force,
                    dry_run=dry_run,
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
                modifier = IDFModifier(output_dir=work_dir(config, "derived"))

                # Perform object creation with IDD validation
                result = modifier.add_object(
                    idf_path=idf_path,
                    object_type=object_type,
                    fields=fields,
                    output_path=output_path,
                    force=force,
                    dry_run=dry_run,
                )

                # Add tool metadata to result
                result["tool"] = "idf_modification"
                result["modification_type"] = "add"

                return json.dumps(result, indent=2)

            if action == "delete":
                # Use IDFModifier to delete objects
                modifier = IDFModifier(output_dir=work_dir(config, "derived"))

                # Perform deletion
                result = modifier.delete_objects(
                    idf_path=idf_path,
                    object_type=object_type,
                    target=target,
                    output_path=output_path,
                    force=force,
                    dry_run=dry_run,
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
