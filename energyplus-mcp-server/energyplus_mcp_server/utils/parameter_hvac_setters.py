"""Inspection and non-mutating absolute setters for native-IDF HVAC parameters.

This module is intentionally independent of eppy.  It reads the eppy objects
provided by a caller and returns assignments for the manager to range-check and
apply.  Inspection exposes stable target IDs so a caller can set
all targets or make a narrowly scoped bound-repair request without guessing
IDF field names.
"""

from __future__ import annotations

import math
from typing import Any


PARAMETERS: tuple[str, ...] = ("COP", "HE", "FAN")


_SPECS: dict[str, tuple[dict[str, Any], ...]] = {
    "COP": (
        {
            "object_type": "Coil:Cooling:DX:SingleSpeed",
            "field": "Gross_Rated_Cooling_COP",
            "units": "COP",
        },
        {
            "object_type": "Coil:Cooling:DX:TwoSpeed",
            "field": "High_Speed_Gross_Rated_Cooling_COP",
            "units": "COP",
            "auxiliary_field": "Low_Speed_Gross_Rated_Cooling_COP",
        },
        {
            "object_type": "Chiller:Electric:EIR",
            "field": "Reference_COP",
            "units": "COP",
        },
    ),
    "HE": (
        {
            "object_type": "Coil:Heating:Fuel",
            "field": "Burner_Efficiency",
            "units": "fraction",
        },
        {
            "object_type": "Boiler:HotWater",
            "field": "Nominal_Thermal_Efficiency",
            "units": "fraction",
        },
        {
            "object_type": "Coil:Heating:Electric",
            "field": "Efficiency",
            "units": "fraction",
        },
        {
            "object_type": "Coil:Heating:DX:SingleSpeed",
            "field": "Gross_Rated_Heating_COP",
            "units": "COP",
        },
    ),
    "FAN": (
        {
            "object_type": "Fan:ConstantVolume",
            "field": "Fan_Total_Efficiency",
            "units": "fraction",
        },
        {
            "object_type": "Fan:VariableVolume",
            "field": "Fan_Total_Efficiency",
            "units": "fraction",
        },
        {
            "object_type": "Fan:OnOff",
            "field": "Fan_Total_Efficiency",
            "units": "fraction",
        },
    ),
}


def inspect(idf: Any, parameter: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Inspect absolute-set targets and any unsupported or invalid candidates.

    The returned targets deliberately contain no eppy object references.  Each
    target has a stable ``target_id``, primary ``value`` and canonical
    ``units`` (``COP`` or ``fraction``), plus object type/name metadata.  A
    two-speed DX cooling coil is a single high-speed COP target.  Its low-speed
    COP is exposed in ``auxiliary_fields`` and must preserve its high/low ratio
    when set.
    """
    targets, skipped = _scan(idf, _normalize_parameter(parameter))
    return [_public_target(target) for target in targets], skipped


def plan_set(
    idf: Any,
    parameter: str,
    value: float,
    target_ids: list[str] | tuple[str, ...] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Plan an absolute set for all targets or an explicit complete subset.

    ``target_ids=None`` selects every valid target for the parameter.  A
    supplied subset is useful for an explicit bound repair, but an
    unknown or duplicate target ID is rejected.  A mixed HE selection of COP
    and fraction targets is also rejected: the generic bounds use
    incompatible numerical domains, so a caller must select one unit family at
    a time.  Any skipped records remain in the result for the caller's
    whole-model coverage gate.
    """
    normalized_parameter = _normalize_parameter(parameter)
    targets, skipped = _scan(idf, normalized_parameter)
    selected = _select_targets(targets, target_ids)

    if not selected:
        raise ValueError(f"no valid {normalized_parameter} targets were found")

    units = {target["units"] for target in selected}
    if len(units) != 1:
        raise ValueError(
            "selected HE targets mix COP and fraction units; select one unit family using target_ids"
        )
    requested_value = _normalize_set_value(value, units.pop())

    planned: list[dict[str, Any]] = []
    for target in selected:
        planned.append({
            "object": target["_object"],
            "object_type": target["object_type"],
            "object_name": target["object_name"],
            "field": target["field"],
            "before": target["value"],
            "after": requested_value,
        })
        for auxiliary in target.get("_auxiliaries", []):
            ratio = auxiliary["value"] / target["value"]
            after = requested_value * ratio
            if not math.isfinite(after) or after <= 0.0:
                raise ValueError(
                    f"requested COP cannot preserve {auxiliary['field']} for target {target['target_id']}"
                )
            planned.append({
                "object": target["_object"],
                "object_type": target["object_type"],
                "object_name": target["object_name"],
                "field": auxiliary["field"],
                "before": auxiliary["value"],
                "after": after,
            })

    return planned, skipped


def _scan(idf: Any, parameter: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    objects_by_type = _objects_by_type(idf)
    targets: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    _append_unsupported_types(objects_by_type, parameter, skipped)
    for spec in _SPECS[parameter]:
        object_type = spec["object_type"]
        objects = objects_by_type.get(_type_key(object_type), [])
        for occurrence, obj in enumerate(objects, start=1):
            target_id = _target_id(parameter, object_type, _object_name(obj), occurrence)
            primary = _positive_finite(_field_value(obj, spec["field"]))
            is_fraction = spec["units"] == "fraction"
            if primary is None or (is_fraction and primary > 1.0):
                skipped.append(_invalid_source_skip(target_id, object_type, obj, [spec["field"]], spec["units"]))
                continue

            auxiliaries: list[dict[str, Any]] = []
            auxiliary_field = spec.get("auxiliary_field")
            if auxiliary_field:
                auxiliary = _positive_finite(_field_value(obj, auxiliary_field))
                if auxiliary is None:
                    skipped.append(
                        _invalid_source_skip(
                            target_id,
                            object_type,
                            obj,
                            [spec["field"], auxiliary_field],
                            "COP",
                        )
                    )
                    continue
                auxiliaries.append({
                    "field": auxiliary_field,
                    "value": auxiliary,
                    "units": "COP",
                    "preserve_ratio": True,
                })

            targets.append({
                "target_id": target_id,
                "value": primary,
                "units": spec["units"],
                "object_type": object_type,
                "object_name": _object_name(obj),
                "field": spec["field"],
                "auxiliary_fields": auxiliaries,
                "_object": obj,
                "_auxiliaries": auxiliaries,
            })

    return targets, skipped


def _public_target(target: dict[str, Any]) -> dict[str, Any]:
    result = {
        "target_id": target["target_id"],
        "value": target["value"],
        "units": target["units"],
        "object_type": target["object_type"],
        "object_name": target["object_name"],
        "field": target["field"],
    }
    if target["auxiliary_fields"]:
        result["auxiliary_fields"] = target["auxiliary_fields"]
        result["low_to_high_ratio"] = target["auxiliary_fields"][0]["value"] / target["value"]
    return result


def _select_targets(
    targets: list[dict[str, Any]], target_ids: list[str] | tuple[str, ...] | None
) -> list[dict[str, Any]]:
    by_id = {target["target_id"]: target for target in targets}
    if target_ids is None:
        return targets
    if isinstance(target_ids, str):
        raise ValueError("target_ids must be a list or tuple of target IDs")

    try:
        requested = list(target_ids)
    except TypeError as error:
        raise ValueError("target_ids must be a list or tuple of target IDs") from error
    if not requested:
        raise ValueError("target_ids cannot be empty; omit it to select all targets")
    if any(not isinstance(target_id, str) for target_id in requested):
        raise ValueError("target_ids must contain only strings")
    if len(set(requested)) != len(requested):
        raise ValueError("target_ids must not contain duplicates")

    unknown = [target_id for target_id in requested if target_id not in by_id]
    if unknown:
        raise ValueError(f"unknown or unavailable semantic target IDs: {', '.join(unknown)}")
    return [by_id[target_id] for target_id in requested]


def _normalize_parameter(parameter: str) -> str:
    if not isinstance(parameter, str):
        raise ValueError(f"parameter must be one of {', '.join(PARAMETERS)}")
    normalized = parameter.strip().upper()
    if normalized not in PARAMETERS:
        raise ValueError(f"unsupported HVAC semantic parameter {parameter!r}; expected one of {', '.join(PARAMETERS)}")
    return normalized


def _normalize_set_value(value: float, units: str) -> float:
    if isinstance(value, bool):
        raise ValueError("absolute HVAC semantic value must be numeric")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("absolute HVAC semantic value must be numeric") from error
    if not math.isfinite(numeric) or numeric <= 0.0:
        raise ValueError("absolute HVAC semantic value must be finite and greater than zero")
    if units == "fraction" and numeric > 1.0:
        raise ValueError("fractional HVAC efficiency must be in (0, 1]")
    return numeric


def _objects_by_type(idf: Any) -> dict[str, list[Any]]:
    idfobjects = getattr(idf, "idfobjects", None)
    if not hasattr(idfobjects, "items"):
        raise ValueError("idf must provide an idfobjects mapping")

    grouped: dict[str, list[Any]] = {}
    for raw_type, objects in idfobjects.items():
        try:
            grouped.setdefault(_type_key(raw_type), []).extend(objects)
        except TypeError as error:
            raise ValueError(f"IDF object list for {raw_type!r} is not iterable") from error
    return grouped


def _append_unsupported_types(
    objects_by_type: dict[str, list[Any]], parameter: str, skipped: list[dict[str, Any]]
) -> None:
    supported = {_type_key(spec["object_type"]) for spec in _SPECS[parameter]}
    for type_key, objects in objects_by_type.items():
        if type_key in supported or not _is_relevant_unsupported_type(type_key, parameter):
            continue
        for occurrence, obj in enumerate(objects, start=1):
            skipped.append({
                "target_id": _target_id(parameter, type_key, _object_name(obj), occurrence),
                "object_type": type_key,
                "object_name": _object_name(obj),
                "reason": f"unsupported direct {parameter} tuning object type in the native-IDF MVP",
            })


def _is_relevant_unsupported_type(object_type: str, parameter: str) -> bool:
    if parameter == "COP":
        return (
            object_type.startswith("COIL:COOLING:DX:")
            or object_type.startswith("COIL:COOLING:WATERTOAIRHEATPUMP:")
            or object_type.startswith("CHILLER:")
            or object_type.startswith("AIRCONDITIONER:VARIABLEREFRIGERANTFLOW")
        )
    if parameter == "HE":
        # Heating water coil output is controlled by its plant boiler, not a
        # direct coil efficiency field, so it is not an HE tuning target.
        if object_type == "COIL:HEATING:WATER":
            return False
        return object_type.startswith("COIL:HEATING:") or object_type.startswith("BOILER:")
    if parameter == "FAN":
        # The companion OpenStudio measure covers supply fans only.  Zone
        # exhaust fan tuning remains deliberately outside this parameter scope.
        return object_type.startswith("FAN:") and object_type != "FAN:ZONEEXHAUST"
    return False


def _invalid_source_skip(
    target_id: str, object_type: str, obj: Any, fields: list[str], units: str
) -> dict[str, Any]:
    expected = "a finite value in (0, 1]" if units == "fraction" else "a finite value greater than zero"
    return {
        "target_id": target_id,
        "object_type": object_type,
        "object_name": _object_name(obj),
        "fields": fields,
        "reason": f"invalid source field(s); expected {expected}",
    }


def _field_value(obj: Any, field: str) -> Any:
    try:
        return getattr(obj, field)
    except (AttributeError, KeyError, IndexError):
        return None


def _positive_finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or numeric <= 0.0:
        return None
    return numeric


def _target_id(parameter: str, object_type: object, object_name: str, occurrence: int) -> str:
    return f"{parameter}:{_type_key(object_type)}:{object_name}:{occurrence}"


def _type_key(object_type: object) -> str:
    return str(object_type).strip().upper()


def _object_name(obj: Any) -> str:
    name = _field_value(obj, "Name")
    return str(name) if name not in (None, "") else "Unnamed"
