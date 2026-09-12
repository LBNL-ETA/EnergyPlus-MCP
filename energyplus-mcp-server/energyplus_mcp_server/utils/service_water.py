"""Inspectable, atomic service-water edits for native IDFs.

This module exposes service-water semantics without treating all hot-water
fields as interchangeable.  Combustion efficiency, fuel, peak demand/flow,
loss coefficients, and parasitic power retain distinct targets and units.
Schedules and connection membership are inspected as relationships and are
never silently edited.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any, Mapping


DOMAIN = "service_water"
MODEL_FORMAT = "idf"
OPERATION = "set_service_water_targets"
FUEL_TYPES = frozenset({
    "Electricity", "NaturalGas", "PropaneGas", "FuelOil#1", "FuelOil#2",
    "Coal", "Diesel", "Gasoline", "OtherFuel1", "OtherFuel2", "Steam",
    "DistrictHeating",
})

_MIXED_PROPERTIES = (
    ("Heater_Thermal_Efficiency", "combustion_efficiency", "fraction"),
    ("Heater_Fuel_Type", "heater_fuel", "fuel"),
    ("On_Cycle_Loss_Coefficient_to_Ambient_Temperature", "loss_coefficient", "W/K"),
    ("Off_Cycle_Loss_Coefficient_to_Ambient_Temperature", "loss_coefficient", "W/K"),
    ("On_Cycle_Parasitic_Fuel_Consumption_Rate", "parasitic_power", "W"),
    ("Off_Cycle_Parasitic_Fuel_Consumption_Rate", "parasitic_power", "W"),
)
_STRATIFIED_PROPERTIES = (
    ("Heater_1_Thermal_Efficiency", "combustion_efficiency", "fraction"),
    ("Heater_2_Thermal_Efficiency", "combustion_efficiency", "fraction"),
    ("Heater_1_Fuel_Type", "heater_fuel", "fuel"),
    ("Heater_2_Fuel_Type", "heater_fuel", "fuel"),
)


def capabilities(idf: Any | None = None) -> dict[str, Any]:
    """Report model-specific service-water support without an edit."""
    result = inspect(idf) if idf is not None else {
        "coverage": "unverified",
        "supported": False,
        "applicable_targets": [],
        "skipped": [],
        "shared_relationships": [],
        "warnings": [],
    }
    return {
        "success": True,
        "domain": DOMAIN,
        "operation": "service_water_capabilities",
        "model_format": MODEL_FORMAT,
        "actions": ["inspect_service_water", OPERATION],
        "supported_families": [
            "WaterUse:Equipment", "WaterUse:Connections", "WaterHeater:Mixed",
            "WaterHeater:Stratified (heater efficiency/fuel fields only)",
        ],
        "limits": _limits(),
        **result,
    }


def inspect(idf: Any) -> dict[str, Any]:
    """Inspect safe service-water targets and all relevant unsupported objects."""
    targets, skipped, relationships, warnings = _analyse(idf)
    coverage = _coverage(targets, skipped)
    return {
        "success": True,
        "domain": DOMAIN,
        "operation": "inspect_service_water",
        "model_format": MODEL_FORMAT,
        "coverage": coverage,
        "supported": coverage == "complete",
        "applicable_targets": [_public_target(target) for target in targets],
        "shared_relationships": relationships,
        "skipped": skipped,
        "ambiguous": [item for item in skipped if item.get("classification") == "ambiguous"],
        "warnings": warnings,
        "limits": _limits(),
    }


def plan_set(idf: Any, assignments: Mapping[str, Any]) -> dict[str, Any]:
    """Plan an all-or-nothing edit for explicit, typed service-water targets."""
    targets, skipped, relationships, warnings = _analyse(idf)
    coverage = _coverage(targets, skipped)
    if coverage != "complete":
        return _plan_response(
            success=False,
            coverage=coverage,
            targets=targets,
            relationships=relationships,
            skipped=skipped,
            warnings=warnings,
            error="service-water edits require complete, unambiguous coverage",
        )
    if not isinstance(assignments, Mapping) or not assignments:
        return _plan_response(
            success=False, coverage="none", targets=targets, relationships=relationships,
            skipped=[], warnings=warnings,
            error="assignments must be a non-empty target_id-to-value mapping",
        )
    target_by_id = {target["target_id"]: target for target in targets}
    unknown = sorted(str(target_id) for target_id in assignments if target_id not in target_by_id)
    if unknown:
        return _plan_response(
            success=False, coverage="none", targets=targets, relationships=relationships,
            skipped=[_skip("service_water", target_id, "unknown target_id", "unsupported") for target_id in unknown],
            warnings=warnings, error="assignments include unknown target IDs",
        )

    changes: list[dict[str, Any]] = []
    validation_skips: list[dict[str, Any]] = []
    requested: list[dict[str, Any]] = []
    for target_id, value in assignments.items():
        target = target_by_id[target_id]
        normalized, error = _validate_value(target, value)
        if error:
            validation_skips.append(_skip(
                target["object_type"], target["object_name"], error, "unsupported", target_id=target_id
            ))
            continue
        requested.append({
            "target_id": target_id,
            "requested_value": value,
            "effective_value": normalized,
            "units": target["units"],
            "semantic": target["semantic"],
        })
        changes.append({
            "object": target["object"],
            "object_type": target["object_type"],
            "object_name": target["object_name"],
            "field": target["field"],
            "before": target["value"],
            "after": normalized,
            "target_id": target_id,
            "units": target["units"],
            "semantic": target["semantic"],
        })
    if validation_skips:
        return _plan_response(
            success=False, coverage="none", targets=targets, relationships=relationships,
            skipped=validation_skips, warnings=warnings,
            error="one or more requested service-water values are invalid",
        )
    return _plan_response(
        success=True, coverage="complete", targets=targets, relationships=relationships,
        skipped=[], warnings=warnings, requested=requested, changes=changes,
    )


def execute(
    idf: Any,
    *,
    input_path: str,
    output_path: str,
    assignments: Mapping[str, Any],
    mode: str = "dry_run",
    expected_model_sha256: str | None = None,
) -> dict[str, Any]:
    """Plan or atomically save a distinct service-water candidate IDF."""
    source, destination, hash_or_error = _paths_and_hash(input_path, output_path)
    if source is None or destination is None:
        return _failure(hash_or_error)
    if expected_model_sha256 is not None and expected_model_sha256 != hash_or_error:
        return _failure("input model changed since inspection; inspect again before editing")
    if mode not in {"dry_run", "apply"}:
        return _failure("mode must be 'dry_run' or 'apply'")
    result = plan_set(idf, assignments)
    result.update({
        "input_file": str(source),
        "output_file": str(destination),
        "input_sha256": hash_or_error,
        "mode": mode,
    })
    if not result["success"]:
        result["changed"] = False
        return result
    if mode == "dry_run":
        return result
    live_changes: list[dict[str, Any]] = []
    try:
        live_changes = _live_changes(idf, result["changes"])
        _apply(live_changes)
        destination.parent.mkdir(parents=True, exist_ok=True)
        idf.save(str(destination))
        result["output_sha256"] = hashlib.sha256(destination.read_bytes()).hexdigest()
    except Exception as error:
        _restore(live_changes)
        result.update({
            "success": False,
            "changed": False,
            "error": f"failed to save service-water candidate: {error}",
        })
    return result


def _analyse(idf: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    targets: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    water_use = {_key(_name(obj)): obj for obj in _objects(idf, "WaterUse:Equipment")}
    connection_relationships, connection_skips = _connections(idf, water_use)
    skipped.extend(connection_skips)
    connected_names = {
        _key(name) for relation in connection_relationships for name in relation["water_use_equipment_names"]
    }

    for name_key, obj in sorted(water_use.items()):
        name = _name(obj)
        if name_key not in connected_names:
            skipped.append(_skip(
                "WaterUse:Equipment", name,
                "WaterUse:Equipment is not referenced by a complete WaterUse:Connections object",
                "ambiguous",
            ))
            continue
        field = "Peak_Flow_Rate"
        value = _number(getattr(obj, field, None))
        if value is None or value < 0:
            skipped.append(_skip("WaterUse:Equipment", name, "Peak_Flow_Rate must be a finite non-negative number", "unsupported"))
            continue
        targets.append(_target(
            obj, "WaterUse:Equipment", name, field, value, "peak_flow_rate", "m3/s",
            schedules=_water_use_schedules(obj),
        ))

    for object_type, properties in (
        ("WaterHeater:Mixed", _MIXED_PROPERTIES),
        ("WaterHeater:Stratified", _STRATIFIED_PROPERTIES),
    ):
        for obj in _objects(idf, object_type):
            name = _name(obj)
            found = 0
            for field, semantic, units in properties:
                if not hasattr(obj, field):
                    continue
                found += 1
                value = getattr(obj, field)
                if semantic == "heater_fuel":
                    if not isinstance(value, str) or not value.strip():
                        skipped.append(_skip(object_type, name, f"{field} must be a nonempty fuel type", "unsupported"))
                        continue
                else:
                    value = _number(value)
                    if value is None or not _value_ok(semantic, value):
                        skipped.append(_skip(object_type, name, f"{field} has an invalid {semantic} value", "unsupported"))
                        continue
                targets.append(_target(obj, object_type, name, field, value, semantic, units))
            if found == 0:
                skipped.append(_skip(object_type, name, "no safe service-water property fields were found", "unsupported"))

    for object_type in (
        "WaterHeater:HeatPump:PumpedCondenser",
        "WaterHeater:HeatPump:WrappedCondenser",
        "WaterHeater:Desuperheater",
    ):
        for obj in _objects(idf, object_type):
            skipped.append(_skip(
                object_type, _name(obj),
                "heat-pump/desuperheater COP and compressor controls are a separate semantic family",
                "unsupported",
            ))

    schedule_relationships = _schedule_relationships(targets)
    relationships = connection_relationships + schedule_relationships
    if not targets and not skipped:
        warnings.append({
            "code": "no_service_water_objects",
            "message": "No supported service-water objects were found.",
        })
    return targets, skipped, relationships, warnings


def _connections(idf: Any, equipment: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    relationships, skipped = [], []
    for connection in _objects(idf, "WaterUse:Connections"):
        name = _name(connection)
        member_names = _connection_members(connection)
        unknown = [member for member in member_names if _key(member) not in equipment]
        if not member_names:
            skipped.append(_skip("WaterUse:Connections", name, "connection has no readable WaterUse:Equipment members", "ambiguous"))
            continue
        if unknown:
            skipped.append(_skip(
                "WaterUse:Connections", name,
                "connection references missing WaterUse:Equipment member(s): " + ", ".join(sorted(unknown)),
                "ambiguous",
            ))
            continue
        relationships.append({
            "relationship": "water_use_connection",
            "connection_name": name,
            "water_use_equipment_names": sorted(member_names),
            "shared": len(member_names) > 1,
            "hot_water_supply_temperature_schedule": _text(connection, "Hot_Water_Supply_Temperature_Schedule_Name"),
        })
    return relationships, skipped


def _connection_members(connection: Any) -> list[str]:
    names = []
    for field, value in vars(connection).items():
        normalized = field.casefold()
        if normalized.startswith("water_use_equipment_") and normalized.endswith("_name") and str(value).strip():
            names.append(str(value).strip())
    if names:
        return names
    fields = list(getattr(connection, "fieldnames", []) or [])
    values = list(getattr(connection, "fieldvalues", []) or [])
    if fields and values:
        for field, value in zip(fields, values):
            normalized = str(field).casefold()
            if normalized.startswith("water_use_equipment_") and normalized.endswith("_name") and str(value).strip():
                names.append(str(value).strip())
    if names:
        return names
    # Eppy can retain extensible fields only in fieldvalues.  The object type
    # and name occupy the first two slots; retain values that look like names.
    values = list(getattr(connection, "fieldvalues", []) or [])
    return [str(value).strip() for value in values[2:] if str(value).strip()]


def _water_use_schedules(obj: Any) -> list[dict[str, str]]:
    schedules = []
    for field in ("Flow_Rate_Fraction_Schedule_Name", "Target_Temperature_Schedule_Name"):
        value = _text(obj, field)
        if value:
            schedules.append({"field": field, "schedule_name": value})
    return schedules


def _schedule_relationships(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[str]] = {}
    for target in targets:
        for item in target.get("schedules", []):
            grouped.setdefault(item["schedule_name"], []).append(target["target_id"])
    return [
        {
            "relationship": "shared_schedule",
            "schedule_name": schedule,
            "target_ids": sorted(target_ids),
            "shared": len(target_ids) > 1,
            "note": "schedule is inspected only and is not modified by service-water target edits",
        }
        for schedule, target_ids in sorted(grouped.items())
    ]


def _target(obj: Any, object_type: str, object_name: str, field: str, value: Any, semantic: str, units: str, *, schedules: list[dict[str, str]] | None = None) -> dict[str, Any]:
    identity = f"{object_type}|{object_name}|{field}"
    digest = hashlib.sha256(identity.encode()).hexdigest()[:16]
    return {
        "target_id": f"service-water:{semantic}:{digest}",
        "object": obj,
        "object_type": object_type,
        "object_name": object_name,
        "field": field,
        "value": value,
        "semantic": semantic,
        "units": units,
        "schedules": schedules or [],
    }


def _public_target(target: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in target.items() if key != "object"}


def _validate_value(target: Mapping[str, Any], value: Any) -> tuple[Any, str | None]:
    semantic = target["semantic"]
    if semantic == "heater_fuel":
        if not isinstance(value, str) or value not in FUEL_TYPES:
            return None, "heater fuel must be one of the EnergyPlus fuel type enum values"
        return value, None
    numeric = _number(value)
    if numeric is None or not _value_ok(semantic, numeric):
        return None, f"{semantic} has an invalid value for units {target['units']}"
    return numeric, None


def _value_ok(semantic: str, value: float) -> bool:
    if semantic == "combustion_efficiency":
        return 0 < value <= 1
    if semantic == "peak_flow_rate":
        return value > 0
    if semantic in {"loss_coefficient", "parasitic_power"}:
        return value >= 0
    return False


def _coverage(targets: list[dict[str, Any]], skipped: list[dict[str, Any]]) -> str:
    if any(item.get("classification") == "ambiguous" for item in skipped):
        return "ambiguous"
    if targets and skipped:
        return "partial"
    if targets:
        return "complete"
    return "none"


def _plan_response(*, success: bool, coverage: str, targets: list[dict[str, Any]], relationships: list[dict[str, Any]], skipped: list[dict[str, Any]], warnings: list[dict[str, Any]], error: str | None = None, requested: list[dict[str, Any]] | None = None, changes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    changes = changes or []
    before = _public_changes(changes, phase="before")
    after = _public_changes(changes, phase="after")
    result = {
        "success": success,
        "domain": DOMAIN,
        "operation": OPERATION,
        "model_format": MODEL_FORMAT,
        "coverage": coverage,
        "supported": coverage == "complete",
        "applicable_targets": [_public_target(target) for target in targets],
        "requested": requested or [],
        "shared_relationships": relationships,
        "skipped": skipped,
        "ambiguous": [item for item in skipped if item.get("classification") == "ambiguous"],
        "warnings": warnings,
        "limits": _limits(),
        "before": before,
        "after": after,
        "changes": _public_changes(changes),
        "changed": any(item["before"] != item["after"] for item in changes),
    }
    if error:
        result["error"] = error
    return result


def _public_changes(changes: list[dict[str, Any]], phase: str | None = None) -> list[dict[str, Any]]:
    result = []
    for change in changes:
        entry = {key: value for key, value in change.items() if key != "object"}
        if phase == "before":
            entry.pop("after", None)
        elif phase == "after":
            entry.pop("before", None)
        result.append(entry)
    return result


def _live_changes(idf: Any, public_changes: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Reattach an already-validated public plan to current live IDF objects."""
    targets, skipped, _relationships, _warnings = _analyse(idf)
    if _coverage(targets, skipped) != "complete":
        raise ValueError("service-water coverage changed after planning; inspect again before editing")
    target_by_id = {target["target_id"]: target for target in targets}
    live_changes = []
    for change in public_changes:
        target = target_by_id.get(change["target_id"])
        if target is None or target["value"] != change["before"]:
            raise ValueError("service-water target changed after planning; inspect again before editing")
        live_changes.append({**change, "object": target["object"]})
    return live_changes


def _apply(changes: list[dict[str, Any]]) -> None:
    applied = []
    try:
        for change in changes:
            setattr(change["object"], change["field"], change["after"])
            applied.append(change)
    except Exception:
        _restore(applied)
        raise


def _restore(changes: list[dict[str, Any]]) -> None:
    for change in reversed(changes):
        setattr(change["object"], change["field"], change["before"])


def _paths_and_hash(input_path: str, output_path: str) -> tuple[Path | None, Path | None, str]:
    source = Path(input_path).expanduser()
    destination = Path(output_path).expanduser()
    if not source.is_file():
        return None, None, f"input_path must be an existing IDF: {source}"
    if source.resolve() == destination.resolve():
        return None, None, "output_path must differ from input_path"
    return source.resolve(), destination.resolve(), hashlib.sha256(source.read_bytes()).hexdigest()


def _objects(idf: Any, object_type: str) -> list[Any]:
    return list(getattr(idf, "idfobjects", {}).get(object_type, []))


def _name(obj: Any) -> str:
    return str(getattr(obj, "Name", "")).strip() or "<unnamed>"


def _key(value: str) -> str:
    return value.strip().casefold()


def _text(obj: Any, field: str) -> str:
    return str(getattr(obj, field, "")).strip()


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _skip(object_type: str, object_name: str, reason: str, classification: str, **extra: Any) -> dict[str, Any]:
    return {
        "object_type": object_type,
        "object_name": object_name,
        "reason": reason,
        "classification": classification,
        **extra,
    }


def _limits() -> dict[str, Any]:
    return {
        "combustion_efficiency": {"minimum_exclusive": 0, "maximum": 1, "units": "fraction"},
        "peak_flow_rate": {"minimum_exclusive": 0, "units": "m3/s"},
        "loss_coefficient": {"minimum": 0, "units": "W/K"},
        "parasitic_power": {"minimum": 0, "units": "W"},
        "heater_fuel": {"enum": sorted(FUEL_TYPES)},
    }


def _failure(message: str) -> dict[str, Any]:
    return {
        "success": False,
        "domain": DOMAIN,
        "operation": OPERATION,
        "model_format": MODEL_FORMAT,
        "coverage": "none",
        "supported": False,
        "changed": False,
        "error": message,
    }
