"""Safe, IDF-native planning for thermostat and outdoor-air controls.

This module deliberately does *not* import the schedule implementation.  A
``schedule_adapter`` is supplied by the domain manager so a schedule mutation
can stay responsible for its own object-family support, cloning, and save
mechanics.  The adapter contract is intentionally small:

``inspect_consumers(idf=..., consumer_refs=[...])``
    Returns ``{"profiles": {schedule_name: profile}, "skipped": [...]}``.
    A profile has either ``values`` (a sequence of numeric schedule values) or
    finite ``min_value`` and ``max_value``.  Each consumer ref has
    ``consumer_id``, ``object_type``, ``object_name``, ``field``, ``role`` and
    ``schedule_name``.

``plan_delta(...)`` / ``plan_scale(...)``
    Receive the selected refs, protected unrelated refs, explicit bounds,
    ``clone_on_write``, stable target IDs, source hash, dry-run flag, and
    output path.  They return a serializable plan and may add ``skipped``,
    ``ambiguous``, ``clone_on_write`` or ``warnings``.

``apply_schedule_plan(idf=..., plan=..., output_path=..., expected_model_sha256=...)``
    Applies the schedule plan to the supplied in-memory IDF.  The caller saves
    the resulting IDF.  This separation means an unavailable or unsupported
    schedule representation never causes a partial native-IDF control edit.

The public planners are pure except for asking the adapter to construct its
own plan.  ``execute_control_operation`` owns the optional separate-IDF save
for both schedule and direct-object operations.
"""

from __future__ import annotations

from hashlib import sha256
import math
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol


DOMAIN = "hvac"
MODEL_FORMAT = "idf"
DEFAULT_DEADBAND_C = 1.0
DEFAULT_SETPOINT_BOUNDS_C = (-60.0, 60.0)
DEFAULT_AVAILABILITY_BOUNDS = (0.0, 1.0)

OPERATIONS = (
    "heating_setpoint_delta",
    "cooling_setpoint_delta",
    "availability_schedule_adjustment",
    "outdoor_air_flow_adjustment",
    "economizer_control",
)

_OPERATION_ALIASES = {
    "heating_setpoint_delta": "heating_setpoint_delta",
    "heating_setpoint": "heating_setpoint_delta",
    "cooling_setpoint_delta": "cooling_setpoint_delta",
    "cooling_setpoint": "cooling_setpoint_delta",
    "availability_schedule_adjustment": "availability_schedule_adjustment",
    "availability_adjustment": "availability_schedule_adjustment",
    "outdoor_air_flow_adjustment": "outdoor_air_flow_adjustment",
    "outdoor_air_adjustment": "outdoor_air_flow_adjustment",
    "economizer_control": "economizer_control",
    "economizer": "economizer_control",
}

_SETPOINT_TYPES = {
    "THERMOSTATSETPOINT:SINGLEHEATING": (("heating", "Setpoint_Temperature_Schedule_Name"),),
    "THERMOSTATSETPOINT:SINGLECOOLING": (("cooling", "Setpoint_Temperature_Schedule_Name"),),
    "THERMOSTATSETPOINT:DUALSETPOINT": (
        ("heating", "Heating_Setpoint_Temperature_Schedule_Name"),
        ("cooling", "Cooling_Setpoint_Temperature_Schedule_Name"),
    ),
}

_DSOA_METHOD_FIELDS = {
    "FLOW/PERSON": ("Outdoor_Air_Flow_per_Person",),
    "FLOW/AREA": ("Outdoor_Air_Flow_per_Zone_Floor_Area",),
    "FLOW/ZONE": ("Outdoor_Air_Flow_per_Zone",),
    "AIRCHANGES/HOUR": ("Outdoor_Air_Flow_Air_Changes_per_Hour",),
    "SUM": (
        "Outdoor_Air_Flow_per_Person",
        "Outdoor_Air_Flow_per_Zone_Floor_Area",
        "Outdoor_Air_Flow_per_Zone",
        "Outdoor_Air_Flow_Air_Changes_per_Hour",
    ),
    "MAXIMUM": (
        "Outdoor_Air_Flow_per_Person",
        "Outdoor_Air_Flow_per_Zone_Floor_Area",
        "Outdoor_Air_Flow_per_Zone",
        "Outdoor_Air_Flow_Air_Changes_per_Hour",
    ),
}

_DSOA_FIELD_UNITS = {
    "Outdoor_Air_Flow_per_Person": "m3/s-person",
    "Outdoor_Air_Flow_per_Zone_Floor_Area": "m3/s-m2",
    "Outdoor_Air_Flow_per_Zone": "m3/s",
    "Outdoor_Air_Flow_Air_Changes_per_Hour": "1/hr",
}

_ECONOMIZER_TYPES = {
    "NOECONOMIZER": "NoEconomizer",
    "FIXEDDRYBULB": "FixedDryBulb",
    "FIXEDENTHALPY": "FixedEnthalpy",
    "FIXEDDEWPOINTANDDRYBULB": "FixedDewPointAndDryBulb",
    "DIFFERENTIALDRYBULB": "DifferentialDryBulb",
    "DIFFERENTIALENTHALPY": "DifferentialEnthalpy",
    "ELECTRONICENTHALPY": "ElectronicEnthalpy",
    "DIFFERENTIALDRYBULBANDENTHALPY": "DifferentialDryBulbAndEnthalpy",
}


class ScheduleControlAdapter(Protocol):
    """The intentionally narrow schedule dependency expected by this module."""

    def inspect_consumers(self, *, idf: Any, consumer_refs: list[dict[str, Any]]) -> Mapping[str, Any]: ...

    def plan_delta(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def plan_scale(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def apply_schedule_plan(self, **kwargs: Any) -> Mapping[str, Any]: ...


def normalize_operation(operation: str) -> str:
    if not isinstance(operation, str):
        raise ValueError("HVAC control operation must be a string")
    normalized = _OPERATION_ALIASES.get(operation.strip().casefold())
    if normalized is None:
        raise ValueError("unsupported HVAC control operation; expected one of " + ", ".join(OPERATIONS))
    return normalized


def inspect_hvac_controls(
    idf: Any,
    *,
    schedule_adapter: ScheduleControlAdapter | None = None,
    deadband_c: float = DEFAULT_DEADBAND_C,
) -> dict[str, Any]:
    """Inspect thermostat, availability, outdoor-air, and economizer controls.

    This is a model-aware read-only view.  It is deliberately useful even when
    a schedule adapter is not installed: direct DSOA/economizer coverage can
    still be reported, while schedule operations are explicitly unavailable.
    """
    _finite(deadband_c, "deadband_c")
    thermostat = _inspect_thermostats(idf)
    availability = _inspect_availability(idf)
    outdoor_air = _inspect_outdoor_air(idf)
    economizer = _inspect_economizers(idf)
    all_schedule_refs = thermostat["consumer_refs"] + availability["consumer_refs"]
    schedule_result = _inspect_schedules(schedule_adapter, idf, all_schedule_refs)
    return {
        "domain": DOMAIN,
        "model_format": MODEL_FORMAT,
        "thermostats": _public_thermostat_inspection(thermostat),
        "availability": _public_schedule_inspection(availability),
        "outdoor_air": _public_outdoor_air_inspection(outdoor_air),
        "economizers": _public_economizer_inspection(economizer),
        "schedule_profiles": schedule_result.get("profiles", {}),
        "schedule_skipped": schedule_result.get("skipped", []),
        "declared_deadband_c": float(deadband_c),
    }


def control_capabilities(
    idf: Any,
    *,
    schedule_adapter: ScheduleControlAdapter | None = None,
    deadband_c: float = DEFAULT_DEADBAND_C,
) -> dict[str, Any]:
    """Return model-specific control gates; ``supported`` is only complete."""
    inspection = inspect_hvac_controls(idf, schedule_adapter=schedule_adapter, deadband_c=deadband_c)
    thermostat = inspection["thermostats"]
    availability = inspection["availability"]
    outdoor_air = inspection["outdoor_air"]
    economizers = inspection["economizers"]
    schedule_adapter_missing = schedule_adapter is None

    def status(targets: list[dict[str, Any]], skipped: list[dict[str, Any]], ambiguous: list[dict[str, Any]], *, adapter: bool = False) -> dict[str, Any]:
        capability_skipped = list(skipped)
        if adapter and schedule_adapter_missing:
            capability_skipped.append({"reason": "no schedule adapter is configured"})
        coverage = _coverage(targets, capability_skipped, ambiguous)
        return {
            "coverage": coverage,
            "supported": coverage == "complete",
            "applicable_target_count": len(targets),
            "skipped": capability_skipped,
            "ambiguous": ambiguous,
        }

    heating = [target for target in thermostat["targets"] if target["role"] == "heating"]
    cooling = [target for target in thermostat["targets"] if target["role"] == "cooling"]
    return {
        "success": True,
        "domain": DOMAIN,
        "model_format": MODEL_FORMAT,
        "operations": {
            "heating_setpoint_delta": {
                **status(heating, thermostat["skipped"], thermostat["ambiguous"], adapter=True),
                "units": "C",
                "value_semantics": "signed Celsius delta applied to heating setpoint schedule values",
                "declared_deadband_c": float(deadband_c),
            },
            "cooling_setpoint_delta": {
                **status(cooling, thermostat["skipped"], thermostat["ambiguous"], adapter=True),
                "units": "C",
                "value_semantics": "signed Celsius delta applied to cooling setpoint schedule values",
                "declared_deadband_c": float(deadband_c),
            },
            "availability_schedule_adjustment": {
                **status(availability["targets"], availability["skipped"], availability["ambiguous"], adapter=True),
                "units": "percent",
                "value_semantics": "signed percentage scaling of availability schedule values",
            },
            "outdoor_air_flow_adjustment": {
                **status(outdoor_air["targets"], outdoor_air["skipped"], outdoor_air["ambiguous"]),
                "units": "percent",
                "value_semantics": "signed percentage scaling of active DesignSpecification:OutdoorAir components without changing method",
            },
            "economizer_control": {
                **status(economizers["targets"], economizers["skipped"], economizers["ambiguous"]),
                "units": "enum",
                "value_semantics": "EnergyPlus Controller:OutdoorAir economizer control selection",
                "allowed_values": list(_ECONOMIZER_TYPES.values()),
            },
        },
    }


def plan_control_operation(
    idf: Any,
    operation: str,
    value: Any,
    *,
    schedule_adapter: ScheduleControlAdapter | None = None,
    scope: str = "building",
    zone_names: Iterable[str] | None = None,
    clone_on_write: bool = True,
    deadband_c: float = DEFAULT_DEADBAND_C,
    setpoint_bounds_c: tuple[float, float] = DEFAULT_SETPOINT_BOUNDS_C,
    expected_model_sha256: str | None = None,
    dry_run: bool = True,
    output_path: str | None = None,
    _internal: bool = False,
) -> dict[str, Any]:
    """Create an auditable, non-mutating control plan.

    ``scope`` is either ``building`` or ``zones``.  A zone-scoped request is
    rejected when a thermostat/DSOA reference also controls a non-selected
    zone; cloning a schedule cannot make that thermostat assignment narrower.
    """
    canonical = normalize_operation(operation)
    deadband = _finite(deadband_c, "deadband_c")
    lower, upper = _validate_bounds(setpoint_bounds_c, "setpoint_bounds_c")
    scope_zones = _normalize_scope(scope, zone_names)
    inspection = {
        "thermostat": _inspect_thermostats(idf),
        "availability": _inspect_availability(idf),
        "outdoor_air": _inspect_outdoor_air(idf),
        "economizer": _inspect_economizers(idf),
    }
    base = _base_plan(canonical, value, expected_model_sha256, dry_run, output_path)
    if canonical in ("heating_setpoint_delta", "cooling_setpoint_delta"):
        role = "heating" if canonical.startswith("heating") else "cooling"
        delta = _finite(value, "setpoint delta")
        targets, skipped, ambiguous = _select_zone_targets(
            inspection["thermostat"], role, scope_zones
        )
        base.update(_plan_setpoint(
            idf, canonical, delta, targets, skipped, ambiguous, inspection["thermostat"],
            schedule_adapter, deadband, lower, upper, clone_on_write,
            expected_model_sha256, dry_run, output_path,
        ))
    elif canonical == "availability_schedule_adjustment":
        percent = _percentage(value, "availability adjustment")
        targets, skipped, ambiguous = _select_zone_targets(
            inspection["availability"], "availability", scope_zones
        )
        base.update(_plan_availability(
            idf, percent, targets, skipped, ambiguous, inspection["availability"],
            schedule_adapter, clone_on_write, expected_model_sha256, dry_run, output_path,
        ))
    elif canonical == "outdoor_air_flow_adjustment":
        percent = _percentage(value, "outdoor-air adjustment")
        targets, skipped, ambiguous = _select_zone_targets(
            inspection["outdoor_air"], "outdoor_air", scope_zones
        )
        base.update(_plan_outdoor_air(percent, targets, skipped, ambiguous, clone_on_write))
    else:
        normalized_value = _normalize_economizer_value(value)
        base.update(_plan_economizer(normalized_value, inspection["economizer"]))
    base["scope"] = "building" if scope_zones is None else "zones"
    if scope_zones is not None:
        base["zone_names"] = sorted(scope_zones)
    base["coverage"] = _coverage(base["applicable_targets"], base["skipped"], base["ambiguous"])
    base["supported"] = base["coverage"] == "complete"
    base["success"] = base["supported"]
    if not _internal:
        base.pop("_private_targets", None)
        base["changes"] = [_without_private(change) for change in base["changes"]]
    return base


def execute_control_operation(
    input_path: str | Path,
    output_path: str | Path | None,
    operation: str,
    value: Any,
    *,
    idf_loader: Callable[[str], Any],
    schedule_adapter: ScheduleControlAdapter | None = None,
    scope: str = "building",
    zone_names: Iterable[str] | None = None,
    clone_on_write: bool = True,
    deadband_c: float = DEFAULT_DEADBAND_C,
    setpoint_bounds_c: tuple[float, float] = DEFAULT_SETPOINT_BOUNDS_C,
    expected_model_sha256: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Plan and, only when complete, save a distinct candidate IDF.

    ``idf_loader`` is normally ``eppy.modeleditor.IDF``.  The strict output
    check prevents accidental source overwrite.  No schedule/direct changes
    are applied when coverage is partial, none, or ambiguous.
    """
    source = Path(input_path).expanduser().resolve()
    source_hash = sha256(source.read_bytes()).hexdigest()
    target = Path(output_path).expanduser().resolve() if output_path else None
    if not dry_run:
        if target is None:
            raise ValueError("output_path is required for apply mode")
        if source == target or (target.exists() and source.samefile(target)):
            raise ValueError("output_path must differ from the explicit input model")
    if expected_model_sha256 is not None and source_hash != expected_model_sha256:
        raise ValueError("Input model changed since inspection; inspect again before editing")
    idf = idf_loader(str(source))
    plan = plan_control_operation(
        idf, operation, value, schedule_adapter=schedule_adapter, scope=scope,
        zone_names=zone_names, clone_on_write=clone_on_write, deadband_c=deadband_c,
        setpoint_bounds_c=setpoint_bounds_c, expected_model_sha256=expected_model_sha256,
        dry_run=dry_run, output_path=str(target) if target else None, _internal=True,
    )
    plan.update({
        "input_path": str(source), "input_file": str(source), "input_sha256": source_hash,
        "output_path": str(target) if target else None,
        "output_file": str(target) if target else None,
        "mode": "dry_run" if dry_run else "apply",
    })
    if dry_run or not plan["supported"]:
        plan["changed"] = bool(plan["changes"]) if dry_run and plan["supported"] else False
        plan.pop("_private_targets", None)
        plan["changes"] = [_without_private(change) for change in plan["changes"]]
        return plan
    try:
        if plan.get("schedule_plan") is not None:
            _apply_schedule_plan(schedule_adapter, idf, plan["schedule_plan"], str(target), expected_model_sha256)
        else:
            _apply_direct_changes(idf, plan)
        target.parent.mkdir(parents=True, exist_ok=True)
        idf.save(str(target))
    except Exception:
        # The IDF is an in-memory candidate.  Never report a partial save.
        raise
    plan["changed"] = any(change["before"] != change["after"] for change in plan["changes"])
    plan["output_sha256"] = sha256(target.read_bytes()).hexdigest()
    plan.pop("_private_targets", None)
    plan["changes"] = [_without_private(change) for change in plan["changes"]]
    return plan


def _base_plan(operation: str, value: Any, expected_hash: str | None, dry_run: bool, output_path: str | None) -> dict[str, Any]:
    units = "C" if "setpoint" in operation else "percent" if operation != "economizer_control" else "enum"
    semantics = {
        "heating_setpoint_delta": "signed Celsius delta applied to heating setpoint schedule values",
        "cooling_setpoint_delta": "signed Celsius delta applied to cooling setpoint schedule values",
        "availability_schedule_adjustment": "signed percentage scaling of availability schedule values",
        "outdoor_air_flow_adjustment": "signed percentage scaling of active DesignSpecification:OutdoorAir components without changing method",
        "economizer_control": "EnergyPlus Controller:OutdoorAir economizer control selection",
    }[operation]
    return {
        "success": False, "domain": DOMAIN, "operation": operation,
        "model_format": MODEL_FORMAT, "mode": "dry_run" if dry_run else "apply",
        "requested_value": value, "effective_value": value, "units": units,
        "value_semantics": semantics, "expected_model_sha256": expected_hash,
        "output_path": output_path, "applicable_targets": [], "skipped": [],
        "ambiguous": [], "shared_object_relationships": [], "clone_on_write": [],
        "before": [], "after": [], "changes": [], "warnings": [],
        "limitations": [], "changed": False,
    }


def _plan_setpoint(
    idf: Any, operation: str, delta: float, targets: list[dict[str, Any]], skipped: list[dict[str, Any]],
    ambiguous: list[dict[str, Any]], thermostat: dict[str, Any], adapter: ScheduleControlAdapter | None,
    deadband: float, lower: float, upper: float, clone_on_write: bool, expected_hash: str | None,
    dry_run: bool, output_path: str | None,
) -> dict[str, Any]:
    result = _common_plan_targets(targets, skipped, ambiguous, thermostat)
    result["effective_value"] = delta
    result["declared_deadband_c"] = deadband
    result["bounds"] = {"minimum_c": lower, "maximum_c": upper}
    role = "heating" if operation.startswith("heating") else "cooling"
    if adapter is None:
        result["skipped"].append({"reason": "no schedule adapter is configured"})
        return result
    profiles = _inspect_schedules(adapter, idf, thermostat["consumer_refs"])
    result["skipped"].extend(profiles["skipped"])
    profile_map = profiles["profiles"]
    by_thermostat = _thermostat_pairs(thermostat["targets"])
    for target in targets:
        partner = by_thermostat.get(target["thermostat_id"], {}).get("cooling" if role == "heating" else "heating")
        if partner is None:
            continue
        changed_profile = profile_map.get(target["schedule_name"])
        other_profile = profile_map.get(partner["schedule_name"])
        if changed_profile is None or other_profile is None:
            result["ambiguous"].append({
                "target_id": target["target_id"], "reason": "cannot verify heating-cooling deadband because a referenced schedule profile is unavailable",
            })
            continue
        separation = _separation_after_delta(
            changed_profile if role == "heating" else other_profile,
            other_profile if role == "heating" else changed_profile,
            delta if role == "heating" else 0.0,
            0.0 if role == "heating" else delta,
        )
        if separation is None:
            result["ambiguous"].append({"target_id": target["target_id"], "reason": "schedule profile lacks finite values for deadband verification"})
        elif separation < deadband:
            result["ambiguous"].append({
                "target_id": target["target_id"], "reason": f"requested delta would violate declared heating-cooling deadband of {deadband:g} C",
                "minimum_resulting_deadband_c": separation,
            })
    if result["ambiguous"]:
        return result
    refs = [target["consumer_ref"] for target in targets]
    protected = _protected_refs(thermostat["consumer_refs"], refs)
    schedule_plan = _adapter_plan(
        adapter, "plan_delta", idf=idf, consumer_refs=refs, protected_consumer_refs=protected,
        delta_c=delta, bounds={"minimum": lower, "maximum": upper}, clone_on_write=clone_on_write,
        target_ids=[target["target_id"] for target in targets], expected_model_sha256=expected_hash,
        dry_run=dry_run, output_path=output_path,
    )
    _merge_adapter_plan(result, schedule_plan)
    result["schedule_plan"] = schedule_plan
    return result


def _plan_availability(
    idf: Any, percent: float, targets: list[dict[str, Any]], skipped: list[dict[str, Any]],
    ambiguous: list[dict[str, Any]], availability: dict[str, Any], adapter: ScheduleControlAdapter | None,
    clone_on_write: bool, expected_hash: str | None, dry_run: bool, output_path: str | None,
) -> dict[str, Any]:
    result = _common_plan_targets(targets, skipped, ambiguous, availability)
    factor = 1.0 + percent / 100.0
    result["effective_value"] = percent
    result["scale_factor"] = factor
    result["bounds"] = {"minimum": DEFAULT_AVAILABILITY_BOUNDS[0], "maximum": DEFAULT_AVAILABILITY_BOUNDS[1]}
    if adapter is None:
        result["skipped"].append({"reason": "no schedule adapter is configured"})
        return result
    refs = [target["consumer_ref"] for target in targets]
    protected = _protected_refs(availability["consumer_refs"], refs)
    schedule_plan = _adapter_plan(
        adapter, "plan_scale", idf=idf, consumer_refs=refs, protected_consumer_refs=protected,
        factor=factor, bounds={"minimum": 0.0, "maximum": 1.0}, clone_on_write=clone_on_write,
        target_ids=[target["target_id"] for target in targets], expected_model_sha256=expected_hash,
        dry_run=dry_run, output_path=output_path,
    )
    _merge_adapter_plan(result, schedule_plan)
    result["schedule_plan"] = schedule_plan
    return result


def _plan_outdoor_air(percent: float, targets: list[dict[str, Any]], skipped: list[dict[str, Any]], ambiguous: list[dict[str, Any]], clone_on_write: bool) -> dict[str, Any]:
    result = _common_plan_targets(targets, skipped, ambiguous, {"shared": []})
    result["_private_targets"] = targets
    factor = 1.0 + percent / 100.0
    result["effective_value"] = percent
    result["scale_factor"] = factor
    if factor < 0:
        result["ambiguous"].append({"reason": "outdoor-air percentage cannot be less than -100"})
        return result
    for target in targets:
        fields = target["active_fields"]
        before_components: list[dict[str, Any]] = []
        after_components: list[dict[str, Any]] = []
        for field in fields:
            before = _finite_or_none(_field_value(target["object"], field))
            if before is None or before < 0:
                result["ambiguous"].append({"target_id": target["target_id"], "field": field, "reason": "active outdoor-air component is not a finite non-negative value"})
                continue
            after = before * factor
            before_components.append({"field": field, "value": before, "units": _DSOA_FIELD_UNITS[field]})
            after_components.append({"field": field, "value": after, "units": _DSOA_FIELD_UNITS[field]})
            result["changes"].append({
                "target_id": target["target_id"], "_object": target["object"], "object_type": "DesignSpecification:OutdoorAir",
                "object_name": target["object_name"], "field": field, "before": before, "after": after,
                "units": _DSOA_FIELD_UNITS[field],
            })
        target["before_components"] = before_components
        target["after_components"] = after_components
        if target["unrelated_consumer_ids"]:
            if not clone_on_write:
                result["ambiguous"].append({"target_id": target["target_id"], "reason": "shared outdoor-air object has unrelated consumers and clone_on_write is false"})
            else:
                result["clone_on_write"].append({
                    "target_id": target["target_id"], "object_type": "DesignSpecification:OutdoorAir", "object_name": target["object_name"],
                    "decision": "clone", "protected_consumer_ids": target["unrelated_consumer_ids"],
                })
    result["before"] = [_before_record(change) for change in result["changes"]]
    result["after"] = [_after_record(change) for change in result["changes"]]
    return result


def _plan_economizer(value: dict[str, Any], economizer: dict[str, Any]) -> dict[str, Any]:
    result = _common_plan_targets(economizer["targets"], economizer["skipped"], economizer["ambiguous"], economizer)
    result["effective_value"] = value
    for target in economizer["targets"]:
        before = target["control_type"]
        after = value["control_type"]
        result["changes"].append({
            "target_id": target["target_id"], "_object": target["object"], "object_type": "Controller:OutdoorAir",
            "object_name": target["object_name"], "field": "Economizer_Control_Type", "before": before,
            "after": after, "units": "enum",
        })
        for incoming, field in (("maximum_limit_dry_bulb_c", "Economizer_Maximum_Limit_DryBulb_Temperature"), ("minimum_limit_dry_bulb_c", "Economizer_Minimum_Limit_DryBulb_Temperature")):
            if incoming not in value:
                continue
            current = _finite_or_none(_field_value(target["object"], field))
            result["changes"].append({
                "target_id": target["target_id"], "_object": target["object"], "object_type": "Controller:OutdoorAir",
                "object_name": target["object_name"], "field": field, "before": current,
                "after": value[incoming], "units": "C",
            })
    result["before"] = [_before_record(change) for change in result["changes"]]
    result["after"] = [_after_record(change) for change in result["changes"]]
    return result


def _common_plan_targets(targets: list[dict[str, Any]], skipped: list[dict[str, Any]], ambiguous: list[dict[str, Any]], inspection: dict[str, Any]) -> dict[str, Any]:
    return {
        "applicable_targets": [_public_target(target) for target in targets],
        "skipped": list(skipped), "ambiguous": list(ambiguous),
        "shared_object_relationships": list(inspection.get("shared", [])),
        "clone_on_write": [], "before": [], "after": [], "changes": [], "warnings": [],
        "limitations": [],
    }


def _inspect_thermostats(idf: Any) -> dict[str, Any]:
    zones = _zone_index(idf)
    zone_lists = _zone_lists(idf)
    setpoints = _name_index(idf, tuple(_SETPOINT_TYPES))
    targets: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    for occurrence, thermostat in enumerate(_objects(idf, "ZoneControl:Thermostat"), start=1):
        name = _object_name(thermostat)
        thermostat_id = _stable_id("THERMOSTAT", "ZoneControl:Thermostat", name, occurrence)
        assigned = _expand_zone_reference(_field_value(thermostat, "Zone_or_ZoneList_Name"), zones, zone_lists)
        if not assigned:
            skipped.append({"target_id": thermostat_id, "object_type": "ZoneControl:Thermostat", "object_name": name, "reason": "thermostat has no resolvable Zone or ZoneList assignment"})
            continue
        controls = _thermostat_controls(thermostat)
        if len(controls) != 1:
            ambiguous.append({"target_id": thermostat_id, "object_type": "ZoneControl:Thermostat", "object_name": name, "reason": "thermostat must have exactly one control object; multi-control structures are not safely inferred"})
            continue
        control_type, control_name = controls[0]
        field_specs = _SETPOINT_TYPES.get(_type_key(control_type))
        if field_specs is None:
            skipped.append({"target_id": thermostat_id, "object_type": "ZoneControl:Thermostat", "object_name": name, "reason": f"unsupported thermostat setpoint object type {control_type!r}"})
            continue
        setpoint = setpoints.get((_type_key(control_type), _name_key(control_name)))
        if setpoint is None:
            ambiguous.append({"target_id": thermostat_id, "object_type": "ZoneControl:Thermostat", "object_name": name, "reason": f"referenced {control_type} {control_name!r} was not found"})
            continue
        for role, field in field_specs:
            schedule_name = str(_field_value(setpoint, field) or "").strip()
            target_id = _stable_id(role.upper() + "_SETPOINT", "ZoneControl:Thermostat", name, occurrence)
            if not schedule_name:
                skipped.append({"target_id": target_id, "object_type": _type_key(control_type), "object_name": _object_name(setpoint), "field": field, "reason": f"{role} setpoint schedule is blank"})
                continue
            consumer = {
                "consumer_id": target_id, "object_type": control_type, "object_name": _object_name(setpoint),
                "field": field, "role": role + "_setpoint", "schedule_name": schedule_name,
                "zones": sorted(assigned), "thermostat_id": thermostat_id,
            }
            targets.append({
                "target_id": target_id, "thermostat_id": thermostat_id, "role": role,
                "thermostat_name": name, "zones": sorted(assigned), "schedule_name": schedule_name,
                "setpoint_object_type": control_type, "setpoint_object_name": _object_name(setpoint),
                "consumer_ref": consumer,
            })
    refs = [target["consumer_ref"] for target in targets]
    return {"targets": targets, "skipped": skipped, "ambiguous": ambiguous, "consumer_refs": refs, "shared": _shared_schedule_relationships(refs)}


def _inspect_availability(idf: Any) -> dict[str, Any]:
    targets: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for object_type, obj, occurrence in _all_objects(idf):
        if not _is_hvac_object(object_type):
            continue
        for field in _field_names(obj):
            if _type_key(field) != "AVAILABILITY_SCHEDULE_NAME":
                continue
            schedule_name = str(_field_value(obj, field) or "").strip()
            target_id = _stable_id("AVAILABILITY", object_type, _object_name(obj), occurrence, field)
            if not schedule_name:
                continue
            consumer = {
                "consumer_id": target_id, "object_type": object_type, "object_name": _object_name(obj),
                "field": field, "role": "availability", "schedule_name": schedule_name, "zones": [],
            }
            targets.append({
                "target_id": target_id, "role": "availability", "object_type": object_type,
                "object_name": _object_name(obj), "field": field, "schedule_name": schedule_name,
                "zones": [], "consumer_ref": consumer,
            })
    refs = [target["consumer_ref"] for target in targets]
    return {"targets": targets, "skipped": skipped, "ambiguous": [], "consumer_refs": refs, "shared": _shared_schedule_relationships(refs)}


def _inspect_outdoor_air(idf: Any) -> dict[str, Any]:
    zones = _zone_index(idf)
    zone_lists = _zone_lists(idf)
    consumers_by_dsoa = _dsoa_consumers(idf, zones, zone_lists)
    targets: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    for occurrence, obj in enumerate(_objects(idf, "DesignSpecification:OutdoorAir"), start=1):
        name = _object_name(obj)
        target_id = _stable_id("OUTDOOR_AIR", "DesignSpecification:OutdoorAir", name, occurrence)
        method = _type_key(_field_value(obj, "Outdoor_Air_Method"))
        fields = _DSOA_METHOD_FIELDS.get(method)
        if fields is None:
            skipped.append({"target_id": target_id, "object_type": "DesignSpecification:OutdoorAir", "object_name": name, "reason": f"unsupported Outdoor Air Method {_field_value(obj, 'Outdoor_Air_Method')!r}"})
            continue
        consumers = consumers_by_dsoa.get(_name_key(name), [])
        if not consumers:
            skipped.append({"target_id": target_id, "object_type": "DesignSpecification:OutdoorAir", "object_name": name, "reason": "outdoor-air object is not referenced by a Zone, Space, or Sizing:Zone"})
            continue
        active_fields: list[str] = []
        for field in fields:
            numeric = _finite_or_none(_field_value(obj, field))
            if numeric is None:
                ambiguous.append({"target_id": target_id, "field": field, "reason": "active outdoor-air component is not numeric"})
            elif numeric < 0:
                ambiguous.append({"target_id": target_id, "field": field, "reason": "active outdoor-air component is negative"})
            elif method in ("SUM", "MAXIMUM") and math.isclose(numeric, 0.0, abs_tol=1e-12):
                # A zero component remains a semantic zero; do not turn it on.
                continue
            else:
                active_fields.append(field)
        if not active_fields:
            skipped.append({"target_id": target_id, "object_type": "DesignSpecification:OutdoorAir", "object_name": name, "reason": "no nonzero active outdoor-air component can be adjusted"})
            continue
        consumer_ids = [consumer["consumer_id"] for consumer in consumers]
        target = {
            "target_id": target_id, "object": obj, "object_type": "DesignSpecification:OutdoorAir", "object_name": name,
            "method": _field_value(obj, "Outdoor_Air_Method"), "active_fields": active_fields,
            "consumers": consumers, "zones": sorted({zone for consumer in consumers for zone in consumer["zones"]}),
            "unrelated_consumer_ids": [],
        }
        targets.append(target)
        if len(consumer_ids) > 1:
            target["shared_relationship"] = {"target_id": target_id, "object_type": "DesignSpecification:OutdoorAir", "object_name": name, "consumer_ids": consumer_ids}
    return {
        "targets": targets, "skipped": skipped, "ambiguous": ambiguous, "consumer_refs": [],
        "shared": [target["shared_relationship"] for target in targets if "shared_relationship" in target],
    }


def _inspect_economizers(idf: Any) -> dict[str, Any]:
    targets: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    systems = _name_index(idf, ("AirLoopHVAC:OutdoorAirSystem",))
    controller_links: dict[str, list[str]] = {}
    for (_kind, _name), system in systems.items():
        linked = str(_field_value(system, "Controller_List_Name") or "").strip()
        # Older IDFs route Controller:OutdoorAir through an AirLoopHVAC controller list;
        # retain the direct-system name as evidence but do not fabricate that linkage.
        if linked:
            controller_links.setdefault(_name_key(linked), []).append(_object_name(system))
    for occurrence, controller in enumerate(_objects(idf, "Controller:OutdoorAir"), start=1):
        name = _object_name(controller)
        target_id = _stable_id("ECONOMIZER", "Controller:OutdoorAir", name, occurrence)
        control = str(_field_value(controller, "Economizer_Control_Type") or "").strip()
        normalized = _ECONOMIZER_TYPES.get(_type_key(control))
        if normalized is None:
            ambiguous.append({"target_id": target_id, "object_type": "Controller:OutdoorAir", "object_name": name, "reason": f"unrecognized economizer control type {control!r}"})
            continue
        targets.append({
            "target_id": target_id, "object": controller, "object_type": "Controller:OutdoorAir", "object_name": name,
            "control_type": normalized, "linked_systems": controller_links.get(_name_key(name), []),
        })
    for object_type, obj, occurrence in _all_objects(idf):
        if _type_key(object_type).startswith("CONTROLLER:") and _type_key(object_type) not in {
            "CONTROLLER:OUTDOORAIR",
            "CONTROLLER:MECHANICALVENTILATION",
            # Water-coil controllers regulate a coil, not the outdoor-air
            # economizer.  They are outside this operation's relevance set.
            "CONTROLLER:WATERCOIL",
        }:
            skipped.append({"target_id": _stable_id("ECONOMIZER", object_type, _object_name(obj), occurrence), "object_type": object_type, "object_name": _object_name(obj), "reason": "unsupported controller family for economizer control"})
    return {"targets": targets, "skipped": skipped, "ambiguous": ambiguous, "consumer_refs": [], "shared": []}


def _select_zone_targets(inspection: dict[str, Any], role: str, requested_zones: set[str] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    targets = [dict(target) for target in inspection["targets"] if target.get("role") == role or role == "outdoor_air"]
    skipped = list(inspection["skipped"])
    ambiguous = list(inspection["ambiguous"])
    if requested_zones is None:
        if role == "outdoor_air":
            for target in targets:
                target["unrelated_consumer_ids"] = []
        return targets, skipped, ambiguous
    selected: list[dict[str, Any]] = []
    found_zones: set[str] = set()
    for target in targets:
        target_zones = {_name_key(zone) for zone in target.get("zones", [])}
        overlap = target_zones & requested_zones
        if not overlap:
            continue
        found_zones |= overlap
        if role == "outdoor_air":
            selected_consumers: list[dict[str, Any]] = []
            mixed_consumers: list[dict[str, Any]] = []
            for consumer in target["consumers"]:
                consumer_zones = {_name_key(zone) for zone in consumer["zones"]}
                if not consumer_zones & requested_zones:
                    continue
                if consumer_zones - requested_zones:
                    mixed_consumers.append(consumer)
                else:
                    selected_consumers.append(consumer)
            if mixed_consumers:
                ambiguous.append({"target_id": target["target_id"], "reason": "a selected outdoor-air consumer itself spans selected and non-selected zones; safe rewiring would require splitting that consumer"})
                continue
            if not selected_consumers:
                continue
            selected_ids = {consumer["consumer_id"] for consumer in selected_consumers}
            target["selected_consumer_ids"] = sorted(selected_ids)
            target["unrelated_consumer_ids"] = [
                consumer["consumer_id"] for consumer in target["consumers"]
                if consumer["consumer_id"] not in selected_ids
            ]
            selected.append(target)
            continue
        if target_zones - requested_zones:
            ambiguous.append({"target_id": target["target_id"], "reason": "target also controls non-selected zones; splitting thermostat/DSOA scope is not implemented"})
            continue
        selected.append(target)
    for zone in sorted(requested_zones - found_zones):
        skipped.append({"zone_name": zone, "reason": "requested zone has no applicable control target"})
    return selected, skipped, ambiguous


def _thermostat_pairs(targets: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for target in targets:
        result.setdefault(target["thermostat_id"], {})[target["role"]] = target
    return result


def _separation_after_delta(heating: Mapping[str, Any], cooling: Mapping[str, Any], heating_delta: float, cooling_delta: float) -> float | None:
    h_values = _profile_values(heating)
    c_values = _profile_values(cooling)
    if h_values is not None and c_values is not None and len(h_values) == len(c_values):
        return min(c + cooling_delta - (h + heating_delta) for h, c in zip(h_values, c_values))
    h_max = _profile_bound(heating, "max")
    c_min = _profile_bound(cooling, "min")
    if h_max is None or c_min is None:
        return None
    return c_min + cooling_delta - (h_max + heating_delta)


def _inspect_schedules(adapter: ScheduleControlAdapter | None, idf: Any, refs: list[dict[str, Any]]) -> dict[str, Any]:
    if adapter is None:
        return {"profiles": {}, "skipped": []}
    method = getattr(adapter, "inspect_consumers", None)
    if not callable(method):
        return {"profiles": {}, "skipped": [{"reason": "schedule adapter does not implement inspect_consumers"}]}
    result = method(idf=idf, consumer_refs=refs)
    if not isinstance(result, Mapping):
        return {"profiles": {}, "skipped": [{"reason": "schedule adapter returned an invalid inspection result"}]}
    profiles = result.get("profiles", {})
    return {"profiles": profiles if isinstance(profiles, Mapping) else {}, "skipped": list(result.get("skipped", []))}


def _adapter_plan(adapter: ScheduleControlAdapter, method_name: str, **kwargs: Any) -> dict[str, Any]:
    method = getattr(adapter, method_name, None)
    if not callable(method):
        return {"skipped": [{"reason": f"schedule adapter does not implement {method_name}"}]}
    result = method(**kwargs)
    if not isinstance(result, Mapping):
        return {"skipped": [{"reason": f"schedule adapter {method_name} returned an invalid plan"}]}
    return dict(result)


def _merge_adapter_plan(result: dict[str, Any], schedule_plan: Mapping[str, Any]) -> None:
    result["skipped"].extend(schedule_plan.get("skipped", []))
    result["ambiguous"].extend(schedule_plan.get("ambiguous", []))
    result["warnings"].extend(schedule_plan.get("warnings", []))
    result["clone_on_write"].extend(schedule_plan.get("clone_on_write", []))
    result["shared_object_relationships"].extend(schedule_plan.get("shared_object_relationships", []))
    for change in schedule_plan.get("changes", []):
        if isinstance(change, Mapping):
            public = dict(change)
            result["changes"].append(public)
            result["before"].append({key: val for key, val in public.items() if key != "after"})
            result["after"].append({key: val for key, val in public.items() if key != "before"})


def _apply_schedule_plan(adapter: ScheduleControlAdapter | None, idf: Any, schedule_plan: Mapping[str, Any], output_path: str, expected_hash: str | None) -> None:
    if adapter is None:
        raise ValueError("no schedule adapter is configured")
    method = getattr(adapter, "apply_schedule_plan", None)
    if not callable(method):
        raise ValueError("schedule adapter does not implement apply_schedule_plan")
    result = method(idf=idf, plan=dict(schedule_plan), output_path=output_path, expected_model_sha256=expected_hash)
    if isinstance(result, Mapping) and result.get("success") is False:
        raise ValueError(str(result.get("error", "schedule adapter failed to apply plan")))


def _apply_direct_changes(idf: Any, plan: Mapping[str, Any]) -> None:
    clone_by_target: dict[str, Any] = {}
    for decision in plan.get("clone_on_write", []):
        if decision.get("decision") != "clone":
            continue
        target = next((candidate for candidate in plan["applicable_targets"] if candidate["target_id"] == decision["target_id"]), None)
        if target is None:
            raise ValueError("clone plan has no matching applicable target")
        source_obj = _private_object_for_target(plan, target["target_id"])
        if source_obj is None:
            raise ValueError("clone plan is missing its source outdoor-air object")
        clone = _clone_dsoa(idf, source_obj, target["object_name"], target["target_id"])
        clone_by_target[target["target_id"]] = clone
        for consumer in _private_consumers_for_target(plan, target["target_id"]):
            if consumer["consumer_id"] in decision["protected_consumer_ids"]:
                continue
            setattr(consumer["object"], consumer["field"], _object_name(clone))
    for change in plan.get("changes", []):
        obj = clone_by_target.get(change["target_id"], change.get("_object"))
        if obj is None:
            raise ValueError("direct control change is missing its IDF object")
        setattr(obj, change["field"], change["after"])


def _clone_dsoa(idf: Any, source: Any, source_name: str, target_id: str) -> Any:
    creator = getattr(idf, "newidfobject", None)
    if not callable(creator):
        raise ValueError("IDF implementation cannot clone shared DesignSpecification:OutdoorAir objects")
    suffix = target_id.rsplit(":", 1)[-1]
    clone = creator("DesignSpecification:OutdoorAir")
    for field in _field_names(source):
        if _type_key(field) in {"KEY", "NAME"}:
            continue
        try:
            setattr(clone, field, _field_value(source, field))
        except (AttributeError, TypeError):
            continue
    clone.Name = f"{source_name} __hvac_control_{suffix}"
    return clone


def _private_object_for_target(plan: Mapping[str, Any], target_id: str) -> Any | None:
    for target in plan.get("_private_targets", []):
        if target["target_id"] == target_id:
            return target.get("object")
    return None


def _private_consumers_for_target(plan: Mapping[str, Any], target_id: str) -> list[dict[str, Any]]:
    for target in plan.get("_private_targets", []):
        if target["target_id"] == target_id:
            return target.get("consumers", [])
    return []


def _dsoa_consumers(idf: Any, zones: Mapping[str, str], zone_lists: Mapping[str, list[str]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for object_type, obj, occurrence in _all_objects(idf):
        field = _dsoa_reference_field(obj)
        if field is None:
            continue
        name = str(_field_value(obj, field) or "").strip()
        if not name:
            continue
        zone_reference = _first_value(obj, ("Zone_or_ZoneList_Name", "Zone_Name"))
        assigned = _expand_zone_reference(zone_reference, zones, zone_lists)
        if _type_key(object_type) == "ZONE":
            assigned = {_object_name(obj)}
        consumer = {
            "consumer_id": _stable_id("DSOA_CONSUMER", object_type, _object_name(obj), occurrence, field),
            "object": obj, "object_type": object_type, "object_name": _object_name(obj),
            "field": field, "zones": sorted(assigned),
        }
        result.setdefault(_name_key(name), []).append(consumer)
    return result


def _dsoa_reference_field(obj: Any) -> str | None:
    for field in _field_names(obj):
        if _type_key(field) == "DESIGN_SPECIFICATION_OUTDOOR_AIR_OBJECT_NAME":
            return field
    return None


def _thermostat_controls(obj: Any) -> list[tuple[str, str]]:
    controls: list[tuple[str, str]] = []
    for index in range(1, 10):
        control_type = str(_field_value(obj, f"Control_{index}_Object_Type") or "").strip()
        control_name = str(_field_value(obj, f"Control_{index}_Name") or "").strip()
        if control_type or control_name:
            controls.append((control_type, control_name))
    return controls


def _zone_index(idf: Any) -> dict[str, str]:
    return {_name_key(_object_name(zone)): _object_name(zone) for zone in _objects(idf, "Zone")}


def _zone_lists(idf: Any) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for obj in _objects(idf, "ZoneList"):
        zones: list[str] = []
        for field in _field_names(obj):
            if _type_key(field).startswith("ZONE_") and _type_key(field).endswith("_NAME"):
                value = str(_field_value(obj, field) or "").strip()
                if value:
                    zones.append(value)
        result[_name_key(_object_name(obj))] = zones
    return result


def _expand_zone_reference(value: Any, zones: Mapping[str, str], zone_lists: Mapping[str, list[str]]) -> set[str]:
    key = _name_key(value)
    if not key:
        return set()
    if key in zones:
        return {zones[key]}
    listed = zone_lists.get(key)
    if listed is None:
        return set()
    return {zones[_name_key(zone)] for zone in listed if _name_key(zone) in zones}


def _name_index(idf: Any, types: tuple[str, ...]) -> dict[tuple[str, str], Any]:
    return {
        (_type_key(object_type), _name_key(_object_name(obj))): obj
        for object_type in types for obj in _objects(idf, object_type)
    }


def _objects(idf: Any, object_type: str) -> list[Any]:
    idfobjects = getattr(idf, "idfobjects", None)
    if not hasattr(idfobjects, "items"):
        raise ValueError("idf must provide an idfobjects mapping")
    requested = _type_key(object_type)
    result: list[Any] = []
    for raw_type, objects in idfobjects.items():
        if _type_key(raw_type) != requested:
            continue
        result.extend(objects)
    return result


def _all_objects(idf: Any) -> Iterable[tuple[str, Any, int]]:
    idfobjects = getattr(idf, "idfobjects", None)
    if not hasattr(idfobjects, "items"):
        raise ValueError("idf must provide an idfobjects mapping")
    for object_type, objects in idfobjects.items():
        for occurrence, obj in enumerate(objects, start=1):
            yield str(object_type), obj, occurrence


def _field_names(obj: Any) -> list[str]:
    fields = getattr(obj, "fieldnames", None)
    if fields:
        return [str(field) for field in fields]
    values = getattr(obj, "__dict__", {})
    return [str(field) for field in values if not str(field).startswith("_")]


def _field_value(obj: Any, field: str) -> Any:
    if hasattr(obj, field):
        return getattr(obj, field)
    requested = _type_key(field)
    for candidate in _field_names(obj):
        if _type_key(candidate) == requested:
            return getattr(obj, candidate)
    return None


def _first_value(obj: Any, fields: Iterable[str]) -> Any:
    for field in fields:
        value = _field_value(obj, field)
        if value not in (None, ""):
            return value
    return None


def _is_hvac_object(object_type: str) -> bool:
    normalized = _type_key(object_type)
    return normalized.startswith(("AIRLOOPHVAC", "ZONEHVAC", "FAN:", "COIL:", "BOILER:", "CHILLER:", "PLANTLOOP", "AVAILABILITYMANAGER"))


def _shared_schedule_relationships(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_schedule: dict[str, list[str]] = {}
    for ref in refs:
        by_schedule.setdefault(_name_key(ref["schedule_name"]), []).append(ref["consumer_id"])
    return [
        {"schedule_name": key, "consumer_ids": ids}
        for key, ids in sorted(by_schedule.items()) if len(ids) > 1
    ]


def _protected_refs(all_refs: list[dict[str, Any]], selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected_ids = {ref["consumer_id"] for ref in selected}
    selected_schedules = {_name_key(ref["schedule_name"]) for ref in selected}
    return [
        ref for ref in all_refs
        if _name_key(ref["schedule_name"]) in selected_schedules and ref["consumer_id"] not in selected_ids
    ]


def _normalize_economizer_value(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, Mapping) else {"control_type": value}
    if set(raw) - {"control_type", "maximum_limit_dry_bulb_c", "minimum_limit_dry_bulb_c"}:
        raise ValueError("economizer value supports only control_type and dry-bulb limits in C")
    control = _ECONOMIZER_TYPES.get(_type_key(raw.get("control_type")))
    if control is None:
        raise ValueError("unsupported economizer control type; expected one of " + ", ".join(_ECONOMIZER_TYPES.values()))
    result: dict[str, Any] = {"control_type": control}
    for key in ("maximum_limit_dry_bulb_c", "minimum_limit_dry_bulb_c"):
        if key in raw:
            result[key] = _finite(raw[key], key)
    if ("maximum_limit_dry_bulb_c" in result and "minimum_limit_dry_bulb_c" in result and result["maximum_limit_dry_bulb_c"] < result["minimum_limit_dry_bulb_c"]):
        raise ValueError("economizer maximum dry-bulb limit must be at least the minimum limit")
    return result


def _normalize_scope(scope: str, zone_names: Iterable[str] | None) -> set[str] | None:
    if scope not in {"building", "zones"}:
        raise ValueError("scope must be 'building' or 'zones'")
    if scope == "building":
        if zone_names is not None:
            raise ValueError("zone_names is only valid when scope='zones'")
        return None
    if zone_names is None:
        raise ValueError("zone_names is required when scope='zones'")
    normalized = {_name_key(zone) for zone in zone_names if _name_key(zone)}
    if not normalized:
        raise ValueError("zone_names must contain at least one nonempty zone name")
    return normalized


def _percentage(value: Any, label: str) -> float:
    numeric = _finite(value, label)
    if numeric < -100.0:
        raise ValueError(f"{label} must be at least -100 percent")
    return numeric


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a finite number") from error
    if not math.isfinite(numeric):
        raise ValueError(f"{label} must be a finite number")
    return numeric


def _finite_or_none(value: Any) -> float | None:
    try:
        return _finite(value, "value")
    except ValueError:
        return None


def _validate_bounds(bounds: tuple[float, float], label: str) -> tuple[float, float]:
    if not isinstance(bounds, tuple) or len(bounds) != 2:
        raise ValueError(f"{label} must be a two-item tuple")
    lower, upper = (_finite(bounds[0], label), _finite(bounds[1], label))
    if lower >= upper:
        raise ValueError(f"{label} minimum must be lower than maximum")
    return lower, upper


def _profile_values(profile: Mapping[str, Any]) -> list[float] | None:
    values = profile.get("values")
    if not isinstance(values, (list, tuple)) or not values:
        return None
    result = [_finite_or_none(value) for value in values]
    return None if any(value is None for value in result) else [float(value) for value in result if value is not None]


def _profile_bound(profile: Mapping[str, Any], kind: str) -> float | None:
    values = _profile_values(profile)
    if values is not None:
        return min(values) if kind == "min" else max(values)
    return _finite_or_none(profile.get("min_value" if kind == "min" else "max_value"))


def _coverage(targets: list[dict[str, Any]], skipped: list[dict[str, Any]], ambiguous: list[dict[str, Any]]) -> str:
    if ambiguous:
        return "partial" if targets else "ambiguous"
    if skipped:
        return "partial" if targets else "none"
    return "complete" if targets else "none"


def _stable_id(prefix: str, object_type: str, object_name: str, occurrence: int, field: str | None = None) -> str:
    parts = [prefix, _type_key(object_type), object_name, str(occurrence)]
    if field:
        parts.append(field)
    return ":".join(parts)


def _public_target(target: Mapping[str, Any]) -> dict[str, Any]:
    hidden = {"object", "consumer_ref", "consumers", "unrelated_consumer_ids"}
    return {key: value for key, value in target.items() if key not in hidden and not key.startswith("_")}


def _without_private(mapping: Mapping[str, Any], *hidden: str) -> dict[str, Any]:
    return {key: value for key, value in mapping.items() if key not in hidden and not key.startswith("_")}


def _before_record(change: Mapping[str, Any]) -> dict[str, Any]:
    result = _without_private(change, "after")
    result["value"] = result.pop("before")
    return result


def _after_record(change: Mapping[str, Any]) -> dict[str, Any]:
    result = _without_private(change, "before")
    result["value"] = result.pop("after")
    return result


def _object_name(obj: Any) -> str:
    value = _field_value(obj, "Name")
    return str(value) if value not in (None, "") else "Unnamed"


def _type_key(value: Any) -> str:
    return str(value or "").strip().upper().replace(" ", "")


def _name_key(value: Any) -> str:
    return str(value or "").strip().casefold()


def _public_thermostat_inspection(value: Mapping[str, Any]) -> dict[str, Any]:
    return {"targets": [_public_target(target) for target in value["targets"]], "skipped": value["skipped"], "ambiguous": value["ambiguous"], "shared_object_relationships": value["shared"]}


def _public_schedule_inspection(value: Mapping[str, Any]) -> dict[str, Any]:
    return _public_thermostat_inspection(value)


def _public_outdoor_air_inspection(value: Mapping[str, Any]) -> dict[str, Any]:
    return _public_thermostat_inspection(value)


def _public_economizer_inspection(value: Mapping[str, Any]) -> dict[str, Any]:
    return _public_thermostat_inspection(value)
