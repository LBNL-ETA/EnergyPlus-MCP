"""Non-mutating native-IDF HVAC semantic-parameter planning.

The planner deliberately has no dependency on :mod:`eppy`: it reads eppy IDF
objects supplied by the caller, but leaves range checking, assignment, and
saving to the parameter-operation caller.  Keeping the inspection step pure
lets the caller reject incomplete whole-model changes before an IDF is modified.
"""

from __future__ import annotations

import math
from typing import Any


PARAMETERS: tuple[str, ...] = ("COP", "HE", "FAN")


_COP_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Coil:Cooling:DX:SingleSpeed", ("Gross_Rated_Cooling_COP",)),
    (
        "Coil:Cooling:DX:TwoSpeed",
        ("High_Speed_Gross_Rated_Cooling_COP", "Low_Speed_Gross_Rated_Cooling_COP"),
    ),
    ("Chiller:Electric:EIR", ("Reference_COP",)),
)

_HE_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Coil:Heating:Fuel", ("Burner_Efficiency",)),
    ("Boiler:HotWater", ("Nominal_Thermal_Efficiency",)),
    # These align with the existing OpenStudio heating-efficiency measure.
    ("Coil:Heating:Electric", ("Efficiency",)),
    ("Coil:Heating:DX:SingleSpeed", ("Gross_Rated_Heating_COP",)),
)

_FAN_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Fan:ConstantVolume", ("Fan_Total_Efficiency",)),
    ("Fan:VariableVolume", ("Fan_Total_Efficiency",)),
    ("Fan:OnOff", ("Fan_Total_Efficiency",)),
)

_FIELDS_BY_PARAMETER = {
    "COP": _COP_FIELDS,
    "HE": _HE_FIELDS,
    "FAN": _FAN_FIELDS,
}


def plan(idf: Any, parameter: str, percentage: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Plan a whole-model signed-percentage efficiency change without mutation.

    ``percentage`` is relative to each object's current value.  COP fields
    must remain finite and positive.  Fractional heating and fan efficiencies
    must remain in ``(0, 1]``.  A physically invalid requested result raises
    ``ValueError`` instead of being clipped.  Invalid source fields and
    unsupported direct-equipment object types are returned in ``skipped`` so
    the caller can report partial coverage and reject a mutation.

    Each planned entry contains the original eppy object in ``object`` along
    with its EnergyPlus object type, name, field, and numeric before/after
    values.  The two COP fields of a two-speed DX coil are atomic: neither is
    planned if either source field is invalid.
    """
    normalized_parameter = _normalize_parameter(parameter)
    requested_percentage = _normalize_percentage(percentage)
    factor = 1.0 + requested_percentage / 100.0
    if factor <= 0.0:
        raise ValueError("efficiency percentage change must be greater than -100")

    planned: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    objects_by_type = _objects_by_type(idf)

    _append_unsupported_types(objects_by_type, normalized_parameter, skipped)

    for object_type, fields in _FIELDS_BY_PARAMETER[normalized_parameter]:
        is_fraction = normalized_parameter == "FAN" or (
            normalized_parameter == "HE" and object_type != "Coil:Heating:DX:SingleSpeed"
        )
        for obj in objects_by_type.get(_type_key(object_type), []):
            _plan_object(
                planned=planned,
                skipped=skipped,
                obj=obj,
                object_type=object_type,
                fields=fields,
                factor=factor,
                is_fraction=is_fraction,
            )

    return planned, skipped


def _normalize_parameter(parameter: str) -> str:
    if not isinstance(parameter, str):
        raise ValueError(f"parameter must be one of {', '.join(PARAMETERS)}")
    normalized = parameter.strip().upper()
    if normalized not in PARAMETERS:
        raise ValueError(f"unsupported HVAC semantic parameter {parameter!r}; expected one of {', '.join(PARAMETERS)}")
    return normalized


def _normalize_percentage(percentage: float) -> float:
    if isinstance(percentage, bool):
        raise ValueError("efficiency percentage change must be numeric")
    try:
        normalized = float(percentage)
    except (TypeError, ValueError) as error:
        raise ValueError("efficiency percentage change must be numeric") from error
    if not math.isfinite(normalized):
        raise ValueError("efficiency percentage change must be finite")
    return normalized


def _objects_by_type(idf: Any) -> dict[str, list[Any]]:
    """Return eppy object lists indexed by case-insensitive IDF type."""
    idfobjects = getattr(idf, "idfobjects", None)
    if not hasattr(idfobjects, "items"):
        raise ValueError("idf must provide an idfobjects mapping")

    grouped: dict[str, list[Any]] = {}
    for raw_type, objects in idfobjects.items():
        key = _type_key(raw_type)
        try:
            grouped.setdefault(key, []).extend(objects)
        except TypeError as error:
            raise ValueError(f"IDF object list for {raw_type!r} is not iterable") from error
    return grouped


def _type_key(object_type: object) -> str:
    return str(object_type).strip().upper()


def _append_unsupported_types(
    objects_by_type: dict[str, list[Any]], parameter: str, skipped: list[dict[str, Any]]
) -> None:
    """Expose direct tuning targets that the MVP cannot safely transform."""
    supported = {_type_key(object_type) for object_type, _fields in _FIELDS_BY_PARAMETER[parameter]}

    for type_key, objects in objects_by_type.items():
        if type_key in supported or not _is_relevant_unsupported_type(type_key, parameter):
            continue
        for obj in objects:
            skipped.append({
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
        # Water coils are intentionally excluded: their efficiency is governed
        # by the plant boiler rather than the coil itself.
        if object_type == "COIL:HEATING:WATER":
            return False
        return object_type.startswith("COIL:HEATING:") or object_type.startswith("BOILER:")
    if parameter == "FAN":
        # Zone exhaust fan tuning is outside the OpenStudio measure's supply
        # fan scope, so it is neither an edited nor a skipped semantic target.
        return object_type.startswith("FAN:") and object_type != "FAN:ZONEEXHAUST"
    return False


def _plan_object(
    *,
    planned: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    obj: Any,
    object_type: str,
    fields: tuple[str, ...],
    factor: float,
    is_fraction: bool,
) -> None:
    """Append a full valid object group, or one diagnostic skipped record."""
    values: list[tuple[str, float]] = []
    invalid_fields: list[str] = []
    for field in fields:
        value = _positive_finite(getattr(obj, field, None))
        if value is None or (is_fraction and value > 1.0):
            invalid_fields.append(field)
        else:
            values.append((field, value))

    if invalid_fields:
        expected = "a finite value in (0, 1]" if is_fraction else "a finite value greater than zero"
        skipped.append({
            "object_type": object_type,
            "object_name": _object_name(obj),
            "fields": list(fields),
            "reason": f"invalid source field(s) {', '.join(invalid_fields)}; expected {expected}",
        })
        return

    updates = [(field, before, before * factor) for field, before in values]
    for field, _before, after in updates:
        if not math.isfinite(after) or after <= 0.0 or (is_fraction and after > 1.0):
            bounds = "(0, 1]" if is_fraction else "greater than zero"
            raise ValueError(
                f"requested change produces {after!r} for {object_type} {_object_name(obj)!r} "
                f"field {field}; expected a finite value {bounds}"
            )

    for field, before, after in updates:
        planned.append({
            "object": obj,
            "object_type": object_type,
            "object_name": _object_name(obj),
            "field": field,
            "before": before,
            "after": after,
        })


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


def _object_name(obj: Any) -> str:
    name = getattr(obj, "Name", None)
    return str(name) if name not in (None, "") else "Unnamed"
