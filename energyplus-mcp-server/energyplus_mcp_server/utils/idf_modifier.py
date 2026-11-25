"""
IDF Modifier - Simple foundation for IDF object modifications with IDD validation.

This module provides a lightweight base class for modifying EnergyPlus IDF files
with automatic validation using the Input Data Dictionary (IDD).

Key Features:
- IDD-based field validation (no hardcoded constraints): field names, numeric
  ranges, allowed choice values, and references to other objects
- Target filtering (all, zone:Name, name:Name), case-insensitive like
  EnergyPlus names; any other target is refused rather than matching everything
- All-or-nothing: when any requested change is invalid, nothing is saved
- Deletes and renames refuse to break references unless forced
- dry_run reports the planned change without writing
"""

import difflib
import fnmatch
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from eppy.modeleditor import IDF

from .idd_rules import IDDIndex

logger = logging.getLogger(__name__)

_FIND_MAX_LIMIT = 100


class IDDValidationError(Exception):
    """Raised when IDD validation fails."""
    pass


class TargetError(ValueError):
    """An unrecognised target pattern; nothing is changed."""


TARGET_HELP = 'target must be "all", "name:<object name>" or "zone:<zone name>"'
ZONE_FIELDS = (
    "Zone_or_ZoneList_Name",
    "Zone_Name",
    "Zone_or_ZoneList_or_Space_or_SpaceList_Name",
    "Zone_or_Space_Name",
)
SINGLETON_TYPES = {
    'SIMULATIONCONTROL', 'BUILDING', 'GLOBALGEOMETRYRULES',
    'SHADOWCALCULATION', 'HEATBALANCEALGORITHM', 'TIMESTEP',
    'CONVERGANCELIMITS', 'PROGRAMCONTROL', 'VERSION',
    'OUTPUTCONTROLTABLESTYLE', 'OUTPUTCONTROLREPORTINGTOLERANCES',
    'OUTPUTCONTROLSIZINGSTYLE', 'OUTPUTDIAGNOSTICS',
    'PERFORMANCEPRECISIONTRADEOFFS', 'LIFECYCLECOSTPARAMETERS'
}
_USERS_SHOWN = 20


def _fold(value: Any) -> str:
    return str(value).strip().casefold()


class IDFModifier:
    """Basic CRUD operations on IDF objects with validation against the IDD.

    Every write is all-or-nothing: if any requested change is invalid, the
    model is not saved and the reply lists every problem. ``force=True``
    accepts references to objects that do not exist and deletes or renames
    objects that others still use (reported as warnings). It never accepts
    an unknown field, an out-of-range number, an invalid choice, or a
    duplicate name. ``dry_run=True`` checks and reports without writing.
    """

    def __init__(self, output_dir: Optional[str] = None):
        """``output_dir`` receives auto-named outputs; None keeps them beside the input."""
        self.output_dir = output_dir

    # -- shared helpers --------------------------------------------------------------------

    @staticmethod
    def parse_target(target: Optional[str]) -> Tuple[str, str]:
        """("all", "") | ("name", value) | ("zone", value); raises TargetError otherwise."""
        text = (target or "all").strip()
        if text.casefold() == "all":
            return "all", ""
        kind, separator, value = text.partition(":")
        kind, value = kind.strip().casefold(), value.strip()
        if separator and kind in ("name", "zone") and value:
            return kind, value
        raise TargetError(f"Unrecognised target {target!r}: {TARGET_HELP}. Nothing was changed.")

    def _filter_targets(self, objects: List[Any], target: str) -> List[Any]:
        """Objects matching ``target`` (case-insensitive, like EnergyPlus names)."""
        kind, value = self.parse_target(target)
        if kind == "all":
            return list(objects)
        wanted = _fold(value)
        if kind == "name":
            return [obj for obj in objects if _fold(getattr(obj, "Name", "") or "") == wanted]
        matched = []
        for obj in objects:
            for field in ZONE_FIELDS:
                if field in obj.fieldnames and _fold(getattr(obj, field, "") or "") == wanted:
                    matched.append(obj)
                    break
        return matched

    @staticmethod
    def _field_name(obj: Any, name: Any) -> Optional[str]:
        """The object's field matching ``name``, ignoring case."""
        if name in obj.fieldnames:
            return name
        folded = {field.casefold(): field for field in obj.fieldnames}
        return folded.get(str(name).casefold())

    @staticmethod
    def _type_key(idf: Any, object_type: str) -> Optional[str]:
        upper = object_type.strip().upper()
        return upper if upper in idf.idfobjects else None

    def _apply_fields(
        self,
        index: IDDIndex,
        obj: Any,
        fields: List[Tuple[Any, Any]],
        force: bool,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Set fields on ``obj`` with every IDD check; (changes, errors, warnings)."""
        changes: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        name = str(getattr(obj, "Name", "") or "") if "Name" in obj.fieldnames else ""
        for requested, new_value in fields:
            if not requested:
                errors.append({"object": name, "error": "Missing field name in modification"})
                continue
            field = self._field_name(obj, requested)
            if field is None:
                errors.append({
                    "object": name, "field": requested,
                    "error": f"Invalid field '{requested}' for {obj.key}",
                    "hint": f"Valid fields include: {', '.join(obj.fieldnames[1:10])}...",
                })
                continue
            old_value = getattr(obj, field, None)
            field_idd = index.field_idd(obj.key, obj.fieldnames.index(field))
            # Renaming an object others refer to would leave their references dangling.
            if field_idd.get("reference") and old_value not in (None, "") and _fold(old_value) != _fold(new_value):
                users = index.users_of(obj)
                if users:
                    entry = {
                        "object": name, "field": field,
                        "error": f"Renaming {obj.key} '{old_value}' would break {len(users)} reference(s)",
                        "used_by": users[:_USERS_SHOWN], "used_by_count": len(users),
                    }
                    if not force:
                        errors.append(entry)
                        continue
                    warnings.append(entry)
            try:
                setattr(obj, field, new_value)
            except Exception as error:
                errors.append({"object": name, "field": field, "error": str(error)})
                continue
            try:
                obj.checkrange(field)
            except Exception:
                setattr(obj, field, old_value)
                info = self.get_field_info(obj, field)
                constraints = info.get("constraints") or {}
                message = f"Value {new_value} out of range"
                if constraints.get("minimum") is not None:
                    message += f", min: {constraints['minimum']}"
                if constraints.get("maximum") is not None:
                    message += f", max: {constraints['maximum']}"
                if info.get("units"):
                    message += f" ({info['units']})"
                errors.append({"object": name, "field": field, "value": new_value,
                               "error": message, "constraints": constraints})
                continue
            choice_error, reference_problem = index.value_issue(obj, field, new_value)
            if choice_error:
                setattr(obj, field, old_value)
                errors.append({"object": name, "field": field, "value": new_value, "error": choice_error})
                continue
            if reference_problem:
                if not force:
                    setattr(obj, field, old_value)
                    errors.append({"object": name, "field": field, "value": new_value,
                                   "error": reference_problem + " (pass force=True to accept it)"})
                    continue
                warnings.append({"object": name, "field": field, "warning": reference_problem})
            info = self.get_field_info(obj, field)
            changes.append({
                "field": field,
                "old_value": old_value,
                "new_value": new_value,
                "field_type": info.get("type"),
                "units": info.get("units"),
            })
        return changes, errors, warnings

    def _finish(
        self,
        idf: Any,
        result: Dict[str, Any],
        idf_path: str,
        output_path: Optional[str],
        dry_run: bool,
        changed: bool,
    ) -> Dict[str, Any]:
        """Apply the all-or-nothing rule, then save unless this is a dry run."""
        result["mode"] = "dry_run" if dry_run else "apply"
        if result["errors"]:
            result["success"] = False
            result["saved"] = False
            result["error"] = (
                f"Nothing was saved: {len(result['errors'])} problem(s) listed in errors. "
                "Fix them and call again."
            )
            return result
        if not changed:
            result["success"] = False
            result["saved"] = False
            result["error"] = "No changes to apply"
            return result
        if dry_run:
            result["success"] = True
            result["saved"] = False
            result["note"] = "Dry run: every change passed validation; nothing was written."
            return result
        if output_path is None:
            output_path = self._generate_output_path(idf_path)
        try:
            idf.save(output_path)
        except Exception as error:
            logger.error(f"Failed to save IDF: {error}")
            result.update({"success": False, "saved": False, "error": f"Failed to save IDF: {error}"})
            return result
        result.update({"success": True, "saved": True, "output_file": output_path})
        logger.info(f"Saved modified IDF to {output_path}")
        return result

    @staticmethod
    def _load(idf_path: str) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
        try:
            return IDF(idf_path), None
        except Exception as error:
            logger.error(f"Failed to load IDF: {error}")
            return None, {"success": False, "error": f"Failed to load IDF: {error}"}

    # -- modify ----------------------------------------------------------------------------

    def modify_objects(
        self,
        idf_path: str,
        object_type: str,
        modifications: List[Dict[str, Any]],
        target: str = "all",
        output_path: Optional[str] = None,
        force: bool = False,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Modify the objects of ``object_type`` that match ``target``.

        Args:
            idf_path: Path to input IDF file
            object_type: EnergyPlus object type (e.g., 'Lights', 'People')
            modifications: List of {field: name, value: new_value} dicts
            target: "all", "zone:ZoneName" or "name:ObjectName" (case-insensitive)
            output_path: Where to save (auto-generated if None)
            force: Accept references to missing objects and renames that break references
            dry_run: Validate and report without saving
        """
        logger.info(f"Modifying {object_type} objects in {idf_path} with target={target}")
        try:
            self.parse_target(target)
        except TargetError as error:
            return {"success": False, "saved": False, "error": str(error)}
        idf, failure = self._load(idf_path)
        if failure:
            return failure
        type_key = self._type_key(idf, object_type)
        objects = idf.idfobjects.get(type_key, []) if type_key else []
        if not objects:
            return {"success": False, "saved": False, "error": f"No {object_type} objects found in IDF"}
        target_objects = self._filter_targets(objects, target)
        if not target_objects:
            return {"success": False, "saved": False, "error": f"No objects match target pattern: {target}"}

        index = IDDIndex(idf)
        fields = [(mod.get("field"), mod.get("value")) for mod in modifications]
        result: Dict[str, Any] = {
            "success": False, "modified_objects": [], "errors": [], "warnings": [],
            "input_file": idf_path, "object_type": object_type, "target": target,
            "matched_count": len(target_objects),
        }
        for obj in target_objects:
            changes, errors, warnings = self._apply_fields(index, obj, fields, force)
            result["modified_objects"].append({
                "name": getattr(obj, "Name", "Unnamed"), "modified_fields": changes, "errors": errors,
            })
            result["errors"].extend(errors)
            result["warnings"].extend(warnings)
        modified_count = sum(1 for o in result["modified_objects"] if o["modified_fields"])
        result["modified_count"] = modified_count
        return self._finish(idf, result, idf_path, output_path, dry_run, modified_count > 0)

    def _modify_single_object(self, obj: Any, modifications: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Backwards-compatible single-object modification (validates against the IDD)."""
        index = IDDIndex(obj.theidf) if getattr(obj, "theidf", None) is not None else None
        fields = [(mod.get("field"), mod.get("value")) for mod in modifications]
        if index is None:
            return {"name": getattr(obj, "Name", "Unnamed"), "modified_fields": [],
                    "errors": [{"error": "object is not attached to a model"}]}
        changes, errors, _ = self._apply_fields(index, obj, fields, force=False)
        return {"name": getattr(obj, "Name", "Unnamed"), "modified_fields": changes, "errors": errors}

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

    def find_objects(
        self,
        idf_path: str,
        object_type: Optional[str] = None,
        references: Optional[str] = None,
        name_contains: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """Read-only lookup of objects in a model; the file is never written.

        Args:
            idf_path: Path to the IDF file
            object_type: Exact type ("Lights") or wildcard ("SetpointManager:*");
                case-insensitive. Optional when ``references`` is given.
            references: A name (node, schedule, construction, ...) to find in any
                field, compared case-insensitively. Objects listing it through a
                ``*NodeList`` are also returned, marked ``via``. Each match
                has ``role``: "defines" (its Name is the value) or "references".
            name_contains: Case-insensitive substring of the object's Name.
            limit: Objects returned (1-100); ``total_matches`` counts all.

        Returns:
            Dict with total_matches, type_counts, and objects using the eppy
            field names that ``modify`` accepts.
        """
        if not object_type and not references:
            return {"success": False, "error": "find needs object_type, references, or both"}
        limit = max(1, min(int(limit or 20), _FIND_MAX_LIMIT))

        try:
            idf = IDF(idf_path)
        except Exception as e:
            logger.error(f"Failed to load IDF: {e}")
            return {"success": False, "error": f"Failed to load IDF: {e}"}

        all_types = list(idf.idfobjects.keys())  # upper-case IDD class names
        if object_type:
            pattern = object_type.strip().upper()
            if any(ch in pattern for ch in "*?["):
                types = [t for t in all_types if fnmatch.fnmatchcase(t, pattern)]
            elif pattern in idf.idfobjects:
                types = [pattern]
            else:
                close = difflib.get_close_matches(pattern, all_types, n=5, cutoff=0.6)
                canonical = self._canonical_type_names(idf)
                return {
                    "success": False,
                    "error": f"'{object_type}' is not an object type in the IDD"
                    + (f"; did you mean {[canonical.get(c, c) for c in close]}?" if close else ""),
                }
        else:
            types = all_types

        wanted = references.strip().upper() if references else None
        needle = name_contains.strip().upper() if name_contains else None

        def fields_matching(obj: Any, value: str) -> List[str]:
            return [
                field for field, field_value in zip(obj.fieldnames[1:], obj.fieldvalues[1:])
                if field_value not in ("", None) and str(field_value).strip().upper() == value
            ]

        # Node lists that contain the node, found across all types so that a
        # type filter such as "SetpointManager:*" still sees list members.
        lists: List[str] = []
        if wanted:
            for type_key in all_types:
                if not type_key.endswith("NODELIST"):
                    continue
                for obj in idf.idfobjects.get(type_key, []):
                    name = str(getattr(obj, "Name", "") or "")
                    if name and fields_matching(obj, wanted):
                        lists.append(name)

        matches: List[Dict[str, Any]] = []
        for type_key in types:
            for obj in idf.idfobjects.get(type_key, []):
                name = str(getattr(obj, "Name", "") or "") if "Name" in obj.fieldnames else ""
                if needle and needle not in name.upper():
                    continue
                matched = fields_matching(obj, wanted) if wanted else []
                if wanted and not matched:
                    continue
                matches.append({"object": obj, "matched_fields": matched})

        # One hop through node lists: an object that names a list containing
        # the node also acts on the node (e.g. SetpointManager:MixedAir).
        if lists:
            seen = {id(m["object"]) for m in matches}
            for list_name in lists:
                for type_key in types:
                    for obj in idf.idfobjects.get(type_key, []):
                        if id(obj) in seen:
                            continue
                        if needle and needle not in str(getattr(obj, "Name", "") or "").upper():
                            continue
                        matched = fields_matching(obj, list_name.upper())
                        if matched:
                            matches.append({"object": obj, "matched_fields": matched, "via": list_name})
                            seen.add(id(obj))

        type_counts: Dict[str, int] = {}
        for match in matches:
            type_counts[match["object"].key] = type_counts.get(match["object"].key, 0) + 1

        objects = []
        for match in matches[:limit]:
            obj = match["object"]
            fields = {
                field: value
                for field, value in zip(obj.fieldnames[1:], obj.fieldvalues[1:])
                if value not in ("", None)
            }
            item: Dict[str, Any] = {"type": obj.key, "name": fields.get("Name", ""), "fields": fields}
            if match["matched_fields"]:
                item["matched_fields"] = match["matched_fields"]
                # The object named X "defines" X; any other matching field uses it.
                item["role"] = "defines" if match["matched_fields"] == ["Name"] else "references"
            if match.get("via"):
                item["via"] = match["via"]
            objects.append(item)

        result: Dict[str, Any] = {
            "success": True,
            "idf_path": idf_path,
            "query": {
                k: v for k, v in (
                    ("object_type", object_type), ("references", references),
                    ("name_contains", name_contains),
                ) if v
            },
            "total_matches": len(matches),
            "returned": len(objects),
            "truncated": len(matches) > len(objects),
            "type_counts": type_counts,
            "objects": objects,
        }
        if not matches:
            result["note"] = "No objects match. The file was read but not changed."
        return result

    @staticmethod
    def _canonical_type_names(idf: Any) -> Dict[str, str]:
        """{UPPER class name: IDD spelling}, e.g. SETPOINTMANAGER:COLDEST -> SetpointManager:Coldest."""
        names: Dict[str, str] = {}
        for upper, info in zip(idf.model.dtls, idf.idd_info):
            if info and isinstance(info[0], dict) and info[0].get("idfobj"):
                names[upper] = info[0]["idfobj"]
        return names

    def add_object(
        self,
        idf_path: str,
        object_type: str,
        fields: Dict[str, Any],
        output_path: Optional[str] = None,
        replace_existing: bool = True,
        force: bool = False,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Add a new object, or update the existing one for singleton types.

        Args:
            idf_path: Path to input IDF file
            object_type: EnergyPlus object type (e.g., 'OutputControl:Table:Style')
            fields: Dictionary of field names and values
            output_path: Where to save (auto-generated if None)
            replace_existing: For singleton types, update the existing object (default True)
            force: Accept references to objects that do not exist
            dry_run: Validate and report without saving

        A name already used by another object of the same type is refused.
        """
        logger.info(f"Adding new {object_type} object to {idf_path}")
        idf, failure = self._load(idf_path)
        if failure:
            return failure
        type_key = object_type.strip().upper()
        existing = idf.idfobjects.get(type_key, []) if type_key in idf.idfobjects else []
        is_singleton = type_key.replace(":", "").replace(" ", "") in SINGLETON_TYPES
        index = IDDIndex(idf)
        items = list(fields.items())

        if existing and replace_existing and is_singleton:
            obj = existing[0]
            changes, errors, warnings = self._apply_fields(index, obj, items, force)
            result: Dict[str, Any] = {
                "success": False, "input_file": idf_path, "object_type": object_type,
                "object_created": False, "object_modified": True, "existing_object_updated": True,
                "fields_set": changes, "fields_set_count": len(changes),
                "errors": errors, "warnings": warnings,
            }
            return self._finish(idf, result, idf_path, output_path, dry_run, bool(changes))

        try:
            new_obj = idf.newidfobject(type_key)
        except Exception as error:
            logger.error(f"Failed to create {object_type} object: {error}")
            return {"success": False, "saved": False,
                    "error": f"Failed to create {object_type} object: {error}. Object type may not exist in IDD."}

        errors: List[Dict[str, Any]] = []
        name_field = next((key for key, _ in items if self._field_name(new_obj, key) == "Name"), None)
        if name_field is not None and "Name" in new_obj.fieldnames:
            wanted = _fold(fields[name_field])
            if wanted and any(_fold(getattr(o, "Name", "") or "") == wanted for o in existing if o is not new_obj):
                errors.append({
                    "field": "Name", "value": fields[name_field],
                    "error": f"A {object_type} named '{fields[name_field]}' already exists; EnergyPlus requires unique names",
                })
        changes, field_errors, warnings = self._apply_fields(index, new_obj, items, force)
        errors.extend(field_errors)
        result = {
            "success": False, "input_file": idf_path, "object_type": object_type,
            "object_created": True,
            "fields_set": [{"field": c["field"], "value": c["new_value"]} for c in changes],
            "fields_set_count": len(changes), "errors": errors, "warnings": warnings,
        }
        return self._finish(idf, result, idf_path, output_path, dry_run, True)

    def delete_objects(
        self,
        idf_path: str,
        object_type: str,
        target: str = "all",
        output_path: Optional[str] = None,
        force: bool = False,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Delete the objects of ``object_type`` that match ``target``.

        An object that other objects still refer to (per the IDD's reference
        declarations) is not deleted; the reply lists who uses it. ``force``
        deletes anyway and reports the references that now dangle.
        """
        logger.info(f"Deleting {object_type} objects in {idf_path} with target={target}")
        try:
            self.parse_target(target)
        except TargetError as error:
            return {"success": False, "saved": False, "error": str(error)}
        idf, failure = self._load(idf_path)
        if failure:
            return failure
        type_key = self._type_key(idf, object_type)
        objects = idf.idfobjects.get(type_key, []) if type_key else []
        if not objects:
            return {"success": False, "saved": False, "error": f"No {object_type} objects found in IDF"}
        target_objects = self._filter_targets(objects, target)
        if not target_objects:
            return {"success": False, "saved": False, "error": f"No objects match target pattern: {target}"}

        index = IDDIndex(idf)
        deleting = {id(obj) for obj in target_objects}
        result: Dict[str, Any] = {
            "success": False, "deleted_objects": [], "errors": [], "warnings": [],
            "input_file": idf_path, "object_type": object_type, "target": target,
        }
        for obj in target_objects:
            name = getattr(obj, "Name", "Unnamed")
            users = index.users_of(obj, exclude=deleting)
            if users:
                entry = {
                    "name": name,
                    "error": f"{len(users)} object(s) still refer to {obj.key} '{name}'",
                    "used_by": users[:_USERS_SHOWN], "used_by_count": len(users),
                }
                if not force:
                    entry["hint"] = "Point them at another object first, or pass force=True to delete anyway."
                    result["errors"].append(entry)
                    continue
                result["warnings"].append(entry)
            result["deleted_objects"].append({"name": name, "object_type": object_type})
        if not result["errors"]:
            for obj in target_objects:
                idf.removeidfobject(obj)
        result["deleted_count"] = len(result["deleted_objects"]) if not result["errors"] else 0
        return self._finish(idf, result, idf_path, output_path, dry_run, bool(result["deleted_objects"]))

    def _generate_output_path(self, input_path: str) -> str:
        """Generate timestamped output path.

        Args:
            input_path: Input IDF path

        Returns:
            Output path with timestamp
        """
        path_obj = Path(input_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        directory = Path(self.output_dir) if self.output_dir else path_obj.parent
        directory.mkdir(parents=True, exist_ok=True)
        return str(directory / f"{path_obj.stem}_modified_{timestamp}.idf")
