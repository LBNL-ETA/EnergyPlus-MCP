"""Safe, graph-aware inspection and editing primitives for IDF schedules.

This module deliberately does not reuse :mod:`utils.schedules` for mutation.
That older module is useful for permissive display parsing, but it substitutes
values for malformed fields and converts between schedule forms.  An editing
operation here preserves the source schedule object family and only changes
numeric value fields whose meaning is explicit in the IDD.

The public integration seam is ``ScheduleEditor.edit``.  It is deliberately
dependency-injectable: pass an ``idf_loader`` (and, optionally, a
``path_resolver``) when a host has already configured eppy or has its own IDF
storage abstraction.  The host-facing contract is:

``edit(input_file, consumer_references, operation, value, output_file=None,
target_ids=None, bounds=None, clone_on_write=True,
expected_model_sha256=None, mode="dry_run")``.

``consumer_references`` contains explicit direct consumers returned by
``ScheduleGraph.inspect`` (``consumer_id``, ``object_type``, ``object_name``,
``field``, ``role``, and ``schedule_name``).  ``operation`` is ``scale``,
``delta``, or ``shift_or_extend``.  ``scale`` accepts a finite multiplier;
``delta`` accepts a finite schedule-value increment; ``shift_or_extend``
accepts a mapping containing integral ``shift_hours`` and/or
``extend_hours`` (with optional ``occupied_threshold`` and ``extension_side``).
Only complete plans can be saved.  ``Schedule:File`` is reported as unsupported
and is never changed, including its external file.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field as dataclass_field
from hashlib import sha256
import copy
import math
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Optional, Sequence


SCHEDULE_KINDS = {
    "SCHEDULE:CONSTANT": "Schedule:Constant",
    "SCHEDULE:COMPACT": "Schedule:Compact",
    "SCHEDULE:FILE": "Schedule:File",
    "SCHEDULE:DAY:HOURLY": "Schedule:Day:Hourly",
    "SCHEDULE:DAY:INTERVAL": "Schedule:Day:Interval",
    "SCHEDULE:DAY:LIST": "Schedule:Day:List",
    "SCHEDULE:WEEK:DAILY": "Schedule:Week:Daily",
    "SCHEDULE:WEEK:COMPACT": "Schedule:Week:Compact",
    "SCHEDULE:YEAR": "Schedule:Year",
}

EDITABLE_KINDS = {
    "Schedule:Constant",
    "Schedule:Compact",
    "Schedule:Day:Hourly",
    "Schedule:Day:Interval",
    "Schedule:Day:List",
}

_TIME_RE = re.compile(r"^(?:[01]?\d|2[0-4]):[0-5]\d$")


def _canonical_key(value: str) -> str:
    """Normalize Eppy mapping keys without losing the public IDD spelling."""
    return str(value).replace("_", ":").replace(" ", "").upper()


def _as_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _consumer_reference_identity(key: str, value: Any) -> str:
    """Normalize one stable consumer-reference identity component.

    EnergyPlus object and field names are case-insensitive, whereas Eppy keeps
    the spelling from the active IDD in its object mapping.  HVAC inspection
    produces canonical ``ThermostatSetpoint:*`` names, which must therefore
    match an Eppy raw key such as ``THERMOSTATSETPOINT:DUALSETPOINT``.  Keep
    names otherwise intact: collapsing internal whitespace in a user-assigned
    object or schedule name could accidentally select a different consumer.
    """
    text = _as_text(value)
    if key == "object_type":
        return _canonical_key(text)
    if key == "field":
        return "".join(
            character for character in text.casefold() if character not in " _:-"
        )
    return text.casefold()


def _as_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _hash_id(prefix: str, *parts: str) -> str:
    normalized = "|".join(part.casefold() for part in parts)
    return f"{prefix}:{sha256(normalized.encode('utf-8')).hexdigest()[:16]}"


def _field_names(obj: Any) -> list[str]:
    """Return Eppy field attribute names in IDD order where possible."""
    names = list(getattr(obj, "fieldnames", []) or [])
    if not names:
        names = [name for name in vars(obj) if not name.startswith("_")]
    result: list[str] = []
    for name in names:
        text = str(name)
        if text.casefold() in {"key", "idfobject"}:
            continue
        if text not in result:
            result.append(text)
    return result


def _get(obj: Any, field: str, default: Any = None) -> Any:
    try:
        return getattr(obj, field)
    except (AttributeError, KeyError):
        return default


def _set(obj: Any, field: str, value: Any) -> None:
    setattr(obj, field, value)


def _object_name(obj: Any) -> str:
    return _as_text(_get(obj, "Name", "")) or "<unnamed>"


def _is_schedule_reference_field(field: str) -> bool:
    normalized = field.casefold().replace("_", "")
    if normalized in {"name", "scheduletypelimitsname"}:
        return False
    return "schedule" in normalized and "name" in normalized


def _role(object_type: str, field: str) -> str:
    """Return a stable, intentionally small semantic role vocabulary."""
    kind = object_type.casefold().replace("_", "")
    field_kind = field.casefold().replace("_", "")
    if kind == "lights":
        return "lighting"
    if kind == "electricequipment":
        return "electric_equipment"
    if kind == "people":
        return "occupancy"
    if "availability" in field_kind:
        return "hvac_availability"
    if "thermostat" in kind or "setpoint" in field_kind:
        return "thermostat_setpoint"
    return "schedule_consumer"


def _field_values(obj: Any, names: Sequence[str]) -> list[Any]:
    return [_get(obj, name) for name in names]


@dataclass(frozen=True)
class ScheduleEntry:
    """A schedule object with a stable ID independent of Eppy object identity."""

    target_id: str
    object_type: str
    raw_key: str
    name: str
    obj: Any = dataclass_field(compare=False, repr=False)
    reference_fields: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Consumer:
    """A direct, editable model reference to a top-level schedule."""

    consumer_id: str
    object_type: str
    object_name: str
    field: str
    role: str
    schedule_name: str
    schedule_id: str
    obj: Any = dataclass_field(compare=False, repr=False)

    def public(self) -> dict[str, str]:
        return {
            "consumer_id": self.consumer_id,
            "object_type": self.object_type,
            "object_name": self.object_name,
            "field": self.field,
            "role": self.role,
            "schedule_name": self.schedule_name,
            "schedule_id": self.schedule_id,
        }


@dataclass
class _Plan:
    branches: list[dict[str, Any]]
    applicable_targets: list[dict[str, Any]]
    changes: list[dict[str, Any]]
    skipped: list[dict[str, Any]]
    ambiguous: list[dict[str, Any]]
    shared_objects: list[dict[str, Any]]
    requested: dict[str, Any]
    effective: dict[str, Any]
    warnings: list[str]
    limitations: list[str]

    @property
    def coverage(self) -> str:
        if self.ambiguous:
            return "ambiguous"
        if self.changes and self.skipped:
            return "partial"
        if self.changes:
            return "complete"
        return "none"


class ScheduleGraph:
    """Reference graph for IDF schedules and their direct model consumers.

    The graph recognizes the schedule object families commonly present in the
    SF models.  Schedule identity is by object type plus case-insensitive
    schedule name, mirroring EnergyPlus name lookup while retaining original
    spelling for evidence.
    """

    def __init__(self, idf: Any):
        self.idf = idf
        self.entries: dict[str, ScheduleEntry] = {}
        self._by_name: dict[str, ScheduleEntry] = {}
        self.children: dict[str, list[str]] = defaultdict(list)
        self.parents: dict[str, list[str]] = defaultdict(list)
        self.consumers: dict[str, Consumer] = {}
        self.direct_consumers: dict[str, list[str]] = defaultdict(list)
        self._build()

    @staticmethod
    def stable_target_id(object_type: str, name: str) -> str:
        return _hash_id("schedule", object_type, name)

    def _build(self) -> None:
        objects = getattr(self.idf, "idfobjects", {}) or {}
        for raw_key, records in objects.items():
            object_type = SCHEDULE_KINDS.get(_canonical_key(raw_key))
            if not object_type:
                continue
            for obj in records or []:
                name = _object_name(obj)
                if name == "<unnamed>":
                    continue
                target_id = self.stable_target_id(object_type, name)
                refs = tuple(
                    (field, _as_text(_get(obj, field)))
                    for field in _field_names(obj)
                    if _is_schedule_reference_field(field) and _as_text(_get(obj, field))
                )
                entry = ScheduleEntry(target_id, object_type, str(raw_key), name, obj, refs)
                self.entries[target_id] = entry
                # EnergyPlus schedule names are unique across the schedule namespace.
                self._by_name[name.casefold()] = entry

        for entry in self.entries.values():
            for _field, name in entry.reference_fields:
                child = self._by_name.get(name.casefold())
                if child:
                    self.children[entry.target_id].append(child.target_id)
                    self.parents[child.target_id].append(entry.target_id)

        for raw_key, records in objects.items():
            if _canonical_key(raw_key) in SCHEDULE_KINDS:
                continue
            object_type = str(raw_key)
            for obj in records or []:
                object_name = _object_name(obj)
                for field in _field_names(obj):
                    if not _is_schedule_reference_field(field):
                        continue
                    schedule_name = _as_text(_get(obj, field))
                    target = self._by_name.get(schedule_name.casefold())
                    if not target:
                        continue
                    consumer_id = _hash_id(
                        "consumer", object_type, object_name, field, schedule_name
                    )
                    consumer = Consumer(
                        consumer_id=consumer_id,
                        object_type=object_type,
                        object_name=object_name,
                        field=field,
                        role=_role(object_type, field),
                        schedule_name=schedule_name,
                        schedule_id=target.target_id,
                        obj=obj,
                    )
                    self.consumers[consumer_id] = consumer
                    self.direct_consumers[target.target_id].append(consumer_id)

        for values in self.children.values():
            values.sort()
        for values in self.parents.values():
            values.sort()
        for values in self.direct_consumers.values():
            values.sort()

    def entry_for_name(self, schedule_name: str) -> Optional[ScheduleEntry]:
        return self._by_name.get(str(schedule_name).casefold())

    def descendants(self, target_id: str) -> list[str]:
        """Depth-first schedule closure, including ``target_id`` once."""
        result: list[str] = []
        seen: set[str] = set()

        def walk(node: str) -> None:
            if node in seen:
                return
            seen.add(node)
            result.append(node)
            for child in self.children.get(node, []):
                walk(child)

        walk(target_id)
        return result

    def leaves(self, target_id: str) -> list[str]:
        return [node for node in self.descendants(target_id) if not self.children.get(node)]

    def consumers_for_leaf(self, leaf_id: str) -> list[Consumer]:
        """Find direct model consumers whose root schedule reaches ``leaf_id``."""
        result: list[Consumer] = []
        for root_id, consumer_ids in self.direct_consumers.items():
            if leaf_id not in self.descendants(root_id):
                continue
            result.extend(self.consumers[consumer_id] for consumer_id in consumer_ids)
        return sorted(result, key=lambda item: item.consumer_id)

    def normalized_profile(self, entry: ScheduleEntry) -> dict[str, Any]:
        """Return a non-lossy normalized view; never invent missing values."""
        names = _field_names(entry.obj)
        fields = _field_values(entry.obj, names)
        base = {
            "schedule_id": entry.target_id,
            "schedule_name": entry.name,
            "object_type": entry.object_type,
            "schedule_type_limits": _as_text(_get(entry.obj, "Schedule_Type_Limits_Name")),
        }
        if entry.object_type == "Schedule:Constant":
            value = _as_number(_get(entry.obj, "Hourly_Value"))
            return {**base, "kind": "constant", "segments": ([{"until": "24:00", "value": value}] if value is not None else []), "valid": value is not None}
        if entry.object_type == "Schedule:Day:Hourly":
            segments = []
            for hour in range(1, 25):
                field = f"Hour_{hour}_Value"
                value = _as_number(_get(entry.obj, field))
                if value is not None:
                    segments.append({"until": f"{hour:02d}:00", "value": value})
            return {**base, "kind": "day_hourly", "segments": segments, "valid": len(segments) == 24}
        if entry.object_type == "Schedule:Day:Interval":
            segments = []
            for field, raw in zip(names, fields):
                if not field.casefold().startswith("time_"):
                    continue
                suffix = field.split("_")[-1]
                value = _as_number(_get(entry.obj, f"Value_Until_Time_{suffix}"))
                until = _as_text(raw).replace("Until:", "").strip()
                if value is not None and _TIME_RE.match(until):
                    segments.append({"until": until, "value": value})
            return {**base, "kind": "day_interval", "segments": segments, "valid": bool(segments)}
        if entry.object_type == "Schedule:Day:List":
            minutes = _as_number(_get(entry.obj, "Minutes_per_Item"))
            if minutes is None:
                minutes = _as_number(_get(entry.obj, "Minutes_Per_Item"))
            minutes_int = int(minutes) if minutes and minutes.is_integer() else None
            segments = []
            for field in names:
                if not field.casefold().startswith("value_"):
                    continue
                value = _as_number(_get(entry.obj, field))
                if value is not None:
                    segments.append({"value": value})
            return {**base, "kind": "day_list", "minutes_per_item": minutes_int, "segments": segments, "valid": bool(minutes_int and 1440 % minutes_int == 0 and len(segments) == 1440 // minutes_int)}
        if entry.object_type == "Schedule:Compact":
            segments = []
            for index in range(1, len(names)):
                previous = _as_text(fields[index - 1])
                value = _as_number(fields[index])
                if previous.casefold().startswith("until:") and value is not None:
                    segments.append({"until": previous.split(":", 1)[1].strip(), "value": value})
            return {**base, "kind": "compact", "segments": segments, "valid": bool(segments)}
        if entry.object_type == "Schedule:File":
            return {**base, "kind": "file", "valid": False, "reason": "Schedule:File is external and not editable"}
        return {
            **base,
            "kind": "structural",
            "references": [
                {"field": field, "schedule_name": name, "schedule_id": self.entry_for_name(name).target_id if self.entry_for_name(name) else None}
                for field, name in entry.reference_fields
            ],
            "valid": bool(entry.reference_fields),
        }

    def inspect(self, scope: str = "all") -> dict[str, Any]:
        allowed = {
            "all", "lighting", "electric_equipment", "hvac_availability",
            "thermostat_setpoint", "occupancy", "schedule_consumer",
        }
        if scope not in allowed:
            raise ValueError(f"unsupported schedule scope: {scope}")
        selected_consumers = [
            item for item in self.consumers.values()
            if scope == "all" or item.role == scope
        ]
        roots = {item.schedule_id for item in selected_consumers}
        schedule_ids = set(self.entries) if scope == "all" else set()
        for root in roots:
            schedule_ids.update(self.descendants(root))
        schedules = []
        for schedule_id in sorted(schedule_ids):
            entry = self.entries[schedule_id]
            schedules.append({
                **self.normalized_profile(entry),
                "direct_consumers": [
                    self.consumers[consumer_id].public()
                    for consumer_id in self.direct_consumers.get(schedule_id, [])
                ],
                "referenced_by_schedule_ids": self.parents.get(schedule_id, []),
            })
        return {
            "success": True,
            "domain": "schedules",
            "operation": "inspect",
            "model_format": "idf",
            "scope": scope,
            "schedules": schedules,
            "consumers": [item.public() for item in sorted(selected_consumers, key=lambda item: item.consumer_id)],
            "coverage": "complete" if schedules else "none",
            "supported": bool(schedules),
            "skipped": [],
            "ambiguous": [],
            "warnings": [],
            "limitations": [
                "Schedule:File is displayed but never edited.",
                "Structural schedules preserve their weekday/weekend/holiday and annual references; their terminal day schedules carry numeric edits.",
            ],
        }


def _schedule_type_limits(idf: Any, schedule_name: str) -> tuple[Optional[float], Optional[float], str]:
    objects = getattr(idf, "idfobjects", {}) or {}
    limits = None
    for raw_key, records in objects.items():
        if _canonical_key(raw_key) in {"SCHEDULETYPELIMITS", "SCHEDULE:TYPE:LIMITS"}:
            limits = records or []
            break
    if not schedule_name or not limits:
        return None, None, "schedule_value"
    for obj in limits:
        if _object_name(obj).casefold() != schedule_name.casefold():
            continue
        lower = _as_number(_get(obj, "Lower_Limit_Value"))
        upper = _as_number(_get(obj, "Upper_Limit_Value"))
        units = _as_text(_get(obj, "Unit_Type")) or "schedule_value"
        return lower, upper, units
    return None, None, "schedule_value"


def _value_fields(entry: ScheduleEntry) -> tuple[list[str], Optional[str]]:
    """Return safe numeric schedule-value fields and a reason when unsupported."""
    obj = entry.obj
    names = _field_names(obj)
    if entry.object_type == "Schedule:Constant":
        valid = _as_number(_get(obj, "Hourly_Value")) is not None
        return (["Hourly_Value"] if valid else []), (None if valid else "Hourly_Value is not a finite number")
    if entry.object_type == "Schedule:Day:Hourly":
        fields = [f"Hour_{hour}_Value" for hour in range(1, 25)]
        invalid = [field for field in fields if _as_number(_get(obj, field)) is None]
        return (fields if not invalid else []), (None if not invalid else f"invalid hourly values: {', '.join(invalid)}")
    if entry.object_type == "Schedule:Day:Interval":
        fields = [field for field in names if field.casefold().startswith("value_until_time_") and _as_text(_get(obj, field))]
        invalid = [field for field in fields if _as_number(_get(obj, field)) is None]
        return (fields if fields and not invalid else []), (None if fields and not invalid else "no complete numeric interval values")
    if entry.object_type == "Schedule:Day:List":
        fields = [field for field in names if field.casefold().startswith("value_") and _as_text(_get(obj, field))]
        invalid = [field for field in fields if _as_number(_get(obj, field)) is None]
        return (fields if fields and not invalid else []), (None if fields and not invalid else "no complete numeric list values")
    if entry.object_type == "Schedule:Compact":
        values = _field_values(obj, names)
        fields = []
        for index in range(1, len(names)):
            if _as_text(values[index - 1]).casefold().startswith("until:") and _as_number(values[index]) is not None:
                fields.append(names[index])
        return (fields if fields else []), (None if fields else "no numeric value following an Until: directive")
    if entry.object_type == "Schedule:File":
        return [], "Schedule:File is unsupported; external files are never mutated"
    return [], f"{entry.object_type} is structural; edit one of its terminal day schedules"


def _merge_bounds(
    entry: ScheduleEntry, idf: Any, supplied: Optional[Mapping[str, Any]]
) -> tuple[Optional[float], Optional[float], str, Optional[str]]:
    lower, upper, units = _schedule_type_limits(
        idf, _as_text(_get(entry.obj, "Schedule_Type_Limits_Name"))
    )
    if supplied is None:
        return lower, upper, units, None
    if not isinstance(supplied, Mapping):
        return lower, upper, units, "bounds must be an object with optional min and max"
    supplied_lower = _as_number(supplied.get("min")) if "min" in supplied else None
    supplied_upper = _as_number(supplied.get("max")) if "max" in supplied else None
    if ("min" in supplied and supplied_lower is None) or ("max" in supplied and supplied_upper is None):
        return lower, upper, units, "bounds min and max must be finite numbers"
    lower = max(value for value in (lower, supplied_lower) if value is not None) if any(value is not None for value in (lower, supplied_lower)) else None
    upper = min(value for value in (upper, supplied_upper) if value is not None) if any(value is not None for value in (upper, supplied_upper)) else None
    if lower is not None and upper is not None and lower > upper:
        return lower, upper, units, "intersected bounds are empty"
    return lower, upper, units, None


def _transform_numeric(
    entry: ScheduleEntry,
    fields: Sequence[str],
    operation: str,
    value: Any,
    bounds: tuple[Optional[float], Optional[float]],
) -> tuple[list[dict[str, Any]], Optional[str], dict[str, Any]]:
    lower, upper = bounds
    if operation not in {"scale", "delta"}:
        return [], "numeric transform requested for unsupported operation", {}
    operand = _as_number(value)
    if operand is None:
        return [], f"{operation} value must be a finite number", {}
    changes = []
    for field in fields:
        before = _as_number(_get(entry.obj, field))
        assert before is not None
        after = before * operand if operation == "scale" else before + operand
        if not math.isfinite(after):
            return [], f"{field} result is not finite", {}
        if lower is not None and after < lower - 1e-10:
            return [], f"{field} result {after} is below lower bound {lower}", {}
        if upper is not None and after > upper + 1e-10:
            return [], f"{field} result {after} is above upper bound {upper}", {}
        changes.append({"field": field, "before": before, "after": after})
    semantics = "multiplier" if operation == "scale" else "additive schedule-value increment"
    return changes, None, {"value": operand, "value_semantics": semantics}


def _slot_count_for_shift(entry: ScheduleEntry, fields: Sequence[str]) -> tuple[Optional[int], Optional[str]]:
    if entry.object_type == "Schedule:Day:Hourly" and len(fields) == 24:
        return 1, None
    if entry.object_type != "Schedule:Day:List":
        return None, "shift_or_extend is supported only for complete Schedule:Day:Hourly or Schedule:Day:List profiles"
    minutes = _as_number(_get(entry.obj, "Minutes_per_Item"))
    if minutes is None:
        minutes = _as_number(_get(entry.obj, "Minutes_Per_Item"))
    if minutes is None or not minutes.is_integer() or minutes <= 0 or 1440 % int(minutes):
        return None, "Schedule:Day:List needs an integral Minutes per Item that divides one day"
    if len(fields) != 1440 // int(minutes):
        return None, "Schedule:Day:List must contain a complete one-day value sequence"
    return int(minutes) // 60 if int(minutes) % 60 == 0 else None, (
        None if int(minutes) % 60 == 0 else "shift_or_extend supports Schedule:Day:List only at whole-hour resolution"
    )


def _occupied_components(values: Sequence[float], threshold: float) -> list[tuple[int, int]]:
    components: list[tuple[int, int]] = []
    start: Optional[int] = None
    for index, item in enumerate(values):
        if item > threshold and start is None:
            start = index
        elif item <= threshold and start is not None:
            components.append((start, index - 1))
            start = None
    if start is not None:
        components.append((start, len(values) - 1))
    return components


def _transform_shift_or_extend(
    entry: ScheduleEntry, fields: Sequence[str], value: Any
) -> tuple[list[dict[str, Any]], Optional[str], dict[str, Any]]:
    if not isinstance(value, Mapping):
        return [], "shift_or_extend value must be an object with shift_hours and/or extend_hours", {}
    slot_hours, error = _slot_count_for_shift(entry, fields)
    if error:
        return [], error, {}
    assert slot_hours is not None
    shift = value.get("shift_hours", 0)
    extend = value.get("extend_hours", 0)
    if isinstance(shift, bool) or isinstance(extend, bool):
        return [], "shift_hours and extend_hours must be integers", {}
    try:
        shift_int, extend_int = int(shift), int(extend)
    except (TypeError, ValueError):
        return [], "shift_hours and extend_hours must be integers", {}
    if shift_int != shift or extend_int != extend or extend_int < 0:
        return [], "shift_hours must be integral and extend_hours must be a non-negative integer", {}
    if not shift_int and not extend_int:
        return [], "shift_or_extend needs a nonzero shift_hours or extend_hours", {}
    if shift_int % slot_hours or extend_int % slot_hours:
        return [], "shift_hours and extend_hours must align to the schedule time resolution", {}
    threshold = _as_number(value.get("occupied_threshold", 0.0))
    if threshold is None:
        return [], "occupied_threshold must be a finite number", {}
    side = value.get("extension_side", "both")
    if side not in {"both", "start", "end"}:
        return [], "extension_side must be one of both, start, or end", {}
    before = [_as_number(_get(entry.obj, field)) for field in fields]
    if any(item is None for item in before):
        return [], "schedule contains a nonnumeric value", {}
    values = [float(item) for item in before if item is not None]
    slots_shift = shift_int // slot_hours
    if slots_shift:
        slots_shift %= len(values)
        values = values[-slots_shift:] + values[:-slots_shift] if slots_shift else values
    if extend_int:
        components = _occupied_components(values, threshold)
        if len(components) != 1 or components[0][0] == 0 or components[0][1] == len(values) - 1:
            return [], "occupied-period extension requires exactly one non-wrapping occupied period", {}
        start, end = components[0]
        slots_extend = extend_int // slot_hours
        if side in {"both", "start"}:
            for index in range(max(0, start - slots_extend), start):
                values[index] = values[start]
        if side in {"both", "end"}:
            for index in range(end + 1, min(len(values), end + 1 + slots_extend)):
                values[index] = values[end]
    changes = [
        {"field": field, "before": float(before[index]), "after": values[index]}
        for index, field in enumerate(fields)
    ]
    return changes, None, {
        "value": {
            "shift_hours": shift_int,
            "extend_hours": extend_int,
            "occupied_threshold": threshold,
            "extension_side": side,
        },
        "value_semantics": "whole-hour shift and/or extension of one unwrapped occupied period",
    }


class ScheduleEditor:
    """Plan and safely apply graph-aware schedule edits to a distinct IDF copy."""

    def __init__(
        self,
        idf_loader: Optional[Callable[[str], Any]] = None,
        path_resolver: Optional[Callable[[str], str]] = None,
    ):
        self.idf_loader = idf_loader or self._default_loader
        self.path_resolver = path_resolver or (lambda path: str(Path(path).expanduser().resolve()))

    @staticmethod
    def _default_loader(path: str) -> Any:
        from eppy.modeleditor import IDF
        return IDF(path)

    def inspect(self, input_file: str, scope: str = "all") -> dict[str, Any]:
        resolved = self.path_resolver(input_file)
        source = Path(resolved)
        if not source.is_file():
            raise FileNotFoundError(f"IDF file not found: {resolved}")
        result = ScheduleGraph(self.idf_loader(str(source))).inspect(scope)
        result.update({
            "input_file": str(source),
            "output_file": None,
            "input_sha256": sha256(source.read_bytes()).hexdigest(),
            "mode": "inspect",
            "changed": False,
            "before": [],
            "after": [],
            "shared_objects": [],
        })
        return result

    def edit(
        self,
        input_file: str,
        consumer_references: Sequence[Mapping[str, Any]],
        operation: str,
        value: Any,
        output_file: Optional[str] = None,
        target_ids: Optional[Sequence[str]] = None,
        bounds: Optional[Mapping[str, Any]] = None,
        clone_on_write: bool = True,
        expected_model_sha256: Optional[str] = None,
        mode: str = "dry_run",
    ) -> dict[str, Any]:
        if mode not in {"dry_run", "apply"}:
            raise ValueError("mode must be dry_run or apply")
        resolved_input = Path(self.path_resolver(input_file)).expanduser().resolve()
        if not resolved_input.is_file():
            raise FileNotFoundError(f"IDF file not found: {resolved_input}")
        source_hash = sha256(resolved_input.read_bytes()).hexdigest()
        base = self._response_base(
            input_file=str(resolved_input), output_file=output_file,
            input_hash=source_hash, operation=operation, mode=mode, value=value,
        )
        if expected_model_sha256 is not None and source_hash != expected_model_sha256:
            return self._failure(base, "expected_model_sha256 does not match the source IDF", coverage="none")
        resolved_output: Optional[Path] = None
        if mode == "apply":
            if not output_file:
                return self._failure(base, "output_file is required for apply mode", coverage="none")
            resolved_output = Path(output_file).expanduser().resolve()
            if resolved_output == resolved_input or (
                resolved_output.exists() and resolved_output.samefile(resolved_input)
            ):
                return self._failure(base, "output_file must be a distinct IDF; source files are never overwritten", coverage="none")
            base["output_file"] = str(resolved_output)

        idf = self.idf_loader(str(resolved_input))
        graph = ScheduleGraph(idf)
        plan = self._plan(
            graph, consumer_references, operation, value, target_ids, bounds, clone_on_write
        )
        response = self._render_plan(base, plan)
        if mode == "dry_run" or plan.coverage != "complete":
            response["success"] = plan.coverage == "complete"
            if mode == "apply" and plan.coverage != "complete":
                response["warnings"].append("No candidate was saved because schedule coverage is not complete.")
            return response

        assert resolved_output is not None
        self._apply(graph, plan)
        resolved_output.parent.mkdir(parents=True, exist_ok=True)
        self._save(idf, resolved_output)
        if sha256(resolved_input.read_bytes()).hexdigest() != source_hash:
            raise RuntimeError("source IDF changed during schedule edit; candidate is not trustworthy")
        response["success"] = True
        response["output_sha256"] = sha256(resolved_output.read_bytes()).hexdigest()
        return response

    @staticmethod
    def _save(idf: Any, output_path: Path) -> None:
        if hasattr(idf, "save"):
            idf.save(str(output_path))
            return
        if hasattr(idf, "saveas"):
            idf.saveas(str(output_path))
            return
        raise TypeError("loaded IDF has no save(path) or saveas(path) method")

    @staticmethod
    def _response_base(
        input_file: str, output_file: Optional[str], input_hash: str,
        operation: str, mode: str, value: Any,
    ) -> dict[str, Any]:
        return {
            "success": False,
            "domain": "schedules",
            "operation": operation,
            "model_format": "idf",
            "input_file": input_file,
            "output_file": output_file,
            "input_sha256": input_hash,
            "mode": mode,
            "changed": False,
            "requested_value": {"value": value, "units": "pending", "value_semantics": "pending"},
            "effective_value": {"value": None, "units": "pending", "value_semantics": "pending"},
            "applicable_targets": [],
            "coverage": "none",
            "supported": False,
            "skipped": [],
            "ambiguous": [],
            "shared_objects": [],
            "before": [],
            "after": [],
            "warnings": [],
            "limitations": [
                "Only complete plans are eligible for apply mode.",
                "Schedule:File and its external data are never mutated.",
            ],
        }

    @staticmethod
    def _failure(base: dict[str, Any], reason: str, coverage: str) -> dict[str, Any]:
        base.update({
            "coverage": coverage,
            "supported": False,
            "skipped": [{"reason": reason}],
        })
        return base

    def _plan(
        self,
        graph: ScheduleGraph,
        consumer_references: Sequence[Mapping[str, Any]],
        operation: str,
        value: Any,
        target_ids: Optional[Sequence[str]],
        bounds: Optional[Mapping[str, Any]],
        clone_on_write: bool,
    ) -> _Plan:
        warnings: list[str] = []
        limitations = [
            "Schedule:Compact values are changed only when they immediately follow an Until: directive; directives and dates are preserved.",
            "shift_or_extend does not alter Schedule:Compact or Schedule:Day:Interval because their occupied-period intent may be ambiguous.",
        ]
        skipped: list[dict[str, Any]] = []
        ambiguous: list[dict[str, Any]] = []
        selected = self._select_consumers(graph, consumer_references, ambiguous)
        if not selected:
            return _Plan([], [], [], skipped, ambiguous or [{"reason": "at least one explicit consumer reference is required"}], [], self._requested(operation, value), {}, warnings, limitations)
        if not isinstance(clone_on_write, bool):
            ambiguous.append({"reason": "clone_on_write must be boolean"})
        selected_by_root: dict[str, list[Consumer]] = defaultdict(list)
        for consumer in selected:
            selected_by_root[consumer.schedule_id].append(consumer)

        requested_targets, target_problem = self._selected_target_ids(graph, selected_by_root, target_ids)
        if target_problem:
            skipped.extend(target_problem)
        applicable_targets = self._target_records(graph, selected_by_root, requested_targets)
        branches: list[dict[str, Any]] = []
        changes: list[dict[str, Any]] = []
        effective: dict[str, Any] = {}
        selected_ids = {consumer.consumer_id for consumer in selected}
        for root_id, root_consumers in sorted(selected_by_root.items()):
            root = graph.entries[root_id]
            leaves = [leaf for leaf in graph.leaves(root_id) if not requested_targets or leaf in requested_targets]
            if not leaves:
                skipped.append({"schedule_id": root_id, "reason": "no selected editable terminal schedule targets"})
                continue
            external_consumers = sorted({
                consumer.consumer_id
                for leaf in leaves
                for consumer in graph.consumers_for_leaf(leaf)
                if consumer.consumer_id not in selected_ids
            })
            needs_clone = bool(external_consumers)
            clone_decision = "not_needed"
            if needs_clone and clone_on_write:
                clone_decision = "clone"
            elif needs_clone:
                clone_decision = "blocked"
            branch = {
                "root_schedule_id": root_id,
                "root_schedule_name": root.name,
                "selected_consumer_ids": sorted(item.consumer_id for item in root_consumers),
                "all_affected_consumers": [item.public() for leaf in leaves for item in graph.consumers_for_leaf(leaf)],
                "clone_on_write": {
                    "requested": clone_on_write,
                    "decision": clone_decision,
                    "unrelated_consumer_ids": external_consumers,
                },
                "leaf_schedule_ids": leaves,
            }
            branches.append(branch)
            if needs_clone and not clone_on_write:
                skipped.append({
                    "schedule_id": root_id,
                    "reason": "selected schedule reaches unrelated consumers; clone_on_write is required",
                    "unrelated_consumer_ids": external_consumers,
                })
                continue
            for leaf_id in leaves:
                entry = graph.entries[leaf_id]
                fields, unsupported = _value_fields(entry)
                if unsupported:
                    skipped.append({"schedule_id": leaf_id, "schedule_name": entry.name, "reason": unsupported})
                    continue
                lower, upper, units, bound_problem = _merge_bounds(entry, graph.idf, bounds)
                if bound_problem:
                    ambiguous.append({"schedule_id": leaf_id, "reason": bound_problem})
                    continue
                if operation in {"scale", "delta"}:
                    field_changes, problem, transform_effective = _transform_numeric(
                        entry, fields, operation, value, (lower, upper)
                    )
                elif operation == "shift_or_extend":
                    field_changes, problem, transform_effective = _transform_shift_or_extend(entry, fields, value)
                else:
                    field_changes, problem, transform_effective = [], "operation must be scale, delta, or shift_or_extend", {}
                if problem:
                    skipped.append({"schedule_id": leaf_id, "schedule_name": entry.name, "reason": problem})
                    continue
                effective = {**transform_effective, "units": units, "bounds": {"min": lower, "max": upper}}
                changes.append({
                    "root_schedule_id": root_id,
                    "schedule_id": leaf_id,
                    "schedule_name": entry.name,
                    "object_type": entry.object_type,
                    "fields": field_changes,
                })

        # A root may reach a leaf by more than one selected direct consumer.  One
        # planned field change is sufficient until clone-on-write gives roots their
        # independent closures; retain deterministic root/leaf evidence.
        deduplicated: dict[tuple[str, str], dict[str, Any]] = {}
        for item in changes:
            deduplicated[(item["root_schedule_id"], item["schedule_id"])] = item
        changes = [deduplicated[key] for key in sorted(deduplicated)]
        return _Plan(
            branches=branches,
            applicable_targets=applicable_targets,
            changes=changes,
            skipped=skipped,
            ambiguous=ambiguous,
            shared_objects=branches,
            requested=self._requested(operation, value),
            effective=effective,
            warnings=warnings,
            limitations=limitations,
        )

    @staticmethod
    def _requested(operation: str, value: Any) -> dict[str, Any]:
        if operation == "scale":
            return {"value": value, "units": "multiplier", "value_semantics": "multiply every explicit schedule value"}
        if operation == "delta":
            return {"value": value, "units": "schedule_value", "value_semantics": "add to every explicit schedule value"}
        if operation == "shift_or_extend":
            return {"value": value, "units": "hours", "value_semantics": "shift and/or extend an occupied period"}
        return {"value": value, "units": "unknown", "value_semantics": "unsupported operation"}

    @staticmethod
    def _select_consumers(
        graph: ScheduleGraph,
        references: Sequence[Mapping[str, Any]],
        ambiguous: list[dict[str, Any]],
    ) -> list[Consumer]:
        if isinstance(references, (str, bytes)) or not isinstance(references, Sequence):
            ambiguous.append({"reason": "consumer_references must be a sequence of explicit consumer objects"})
            return []
        selected: list[Consumer] = []
        seen: set[str] = set()
        for reference in references:
            if not isinstance(reference, Mapping):
                ambiguous.append({"reason": "each consumer reference must be an object"})
                continue
            consumer_id = reference.get("consumer_id")
            consumer = graph.consumers.get(consumer_id) if isinstance(consumer_id, str) else None
            if not consumer:
                ambiguous.append({"consumer_id": consumer_id, "reason": "unknown consumer_id"})
                continue
            mismatches = [
                key for key in ("object_type", "object_name", "field", "role", "schedule_name")
                if key in reference and reference[key] != getattr(consumer, key)
            ]
            if mismatches:
                ambiguous.append({"consumer_id": consumer_id, "reason": f"consumer reference does not match model fields: {', '.join(mismatches)}"})
                continue
            if consumer_id not in seen:
                selected.append(consumer)
                seen.add(consumer_id)
        return sorted(selected, key=lambda item: item.consumer_id)

    @staticmethod
    def _selected_target_ids(
        graph: ScheduleGraph,
        selected_by_root: Mapping[str, Sequence[Consumer]],
        target_ids: Optional[Sequence[str]],
    ) -> tuple[set[str], list[dict[str, Any]]]:
        candidates = {leaf for root in selected_by_root for leaf in graph.leaves(root)}
        if target_ids is None:
            return candidates, []
        if isinstance(target_ids, str) or not isinstance(target_ids, Sequence) or not target_ids:
            return set(), [{"reason": "target_ids must be a non-empty sequence of inspected schedule IDs"}]
        problems: list[dict[str, Any]] = []
        requested: set[str] = set()
        for target_id in target_ids:
            if not isinstance(target_id, str):
                problems.append({"target_id": target_id, "reason": "target_id must be a string"})
            elif target_id not in candidates:
                problems.append({"target_id": target_id, "reason": "target is not a terminal schedule reachable from selected consumers"})
            else:
                requested.add(target_id)
        return requested, problems

    @staticmethod
    def _target_records(
        graph: ScheduleGraph,
        selected_by_root: Mapping[str, Sequence[Consumer]],
        target_ids: set[str],
    ) -> list[dict[str, Any]]:
        result = []
        for target_id in sorted(target_ids):
            entry = graph.entries[target_id]
            lower, upper, units, _ = _merge_bounds(entry, graph.idf, None)
            result.append({
                "target_id": target_id,
                "schedule_name": entry.name,
                "object_type": entry.object_type,
                "units": units,
                "bounds": {"min": lower, "max": upper},
                "consumers": [item.public() for item in graph.consumers_for_leaf(target_id)],
            })
        return result

    @staticmethod
    def _render_plan(base: dict[str, Any], plan: _Plan) -> dict[str, Any]:
        before = []
        after = []
        for change in plan.changes:
            for field_change in change["fields"]:
                identity = {
                    "root_schedule_id": change["root_schedule_id"],
                    "schedule_id": change["schedule_id"],
                    "schedule_name": change["schedule_name"],
                    "object_type": change["object_type"],
                    "field": field_change["field"],
                }
                before.append({**identity, "value": field_change["before"]})
                after.append({**identity, "value": field_change["after"]})
        base.update({
            "requested_value": plan.requested,
            "effective_value": plan.effective or {"value": None, "units": "unknown", "value_semantics": "no applicable values"},
            "applicable_targets": plan.applicable_targets,
            "coverage": plan.coverage,
            "supported": plan.coverage == "complete",
            "changed": any(item["value"] != after[index]["value"] for index, item in enumerate(before)),
            "skipped": plan.skipped,
            "ambiguous": plan.ambiguous,
            "shared_objects": plan.shared_objects,
            "before": before,
            "after": after,
            "warnings": plan.warnings,
            "limitations": base["limitations"] + plan.limitations,
        })
        return base

    def _apply(self, graph: ScheduleGraph, plan: _Plan) -> None:
        clone_maps: dict[str, dict[str, ScheduleEntry]] = {}
        for branch in plan.branches:
            if branch["clone_on_write"]["decision"] != "clone":
                continue
            root_id = branch["root_schedule_id"]
            clones = self._clone_closure(graph, root_id)
            clone_maps[root_id] = clones
            clone_root = clones[root_id]
            for consumer_id in branch["selected_consumer_ids"]:
                consumer = graph.consumers[consumer_id]
                _set(consumer.obj, consumer.field, clone_root.name)
        for change in plan.changes:
            entry = clone_maps.get(change["root_schedule_id"], {}).get(
                change["schedule_id"], graph.entries[change["schedule_id"]]
            )
            for field_change in change["fields"]:
                _set(entry.obj, field_change["field"], field_change["after"])
                actual = _as_number(_get(entry.obj, field_change["field"]))
                if actual is None or not math.isclose(actual, field_change["after"], rel_tol=1e-12, abs_tol=1e-12):
                    raise RuntimeError(f"schedule field verification failed: {entry.name}.{field_change['field']}")

    def _clone_closure(self, graph: ScheduleGraph, root_id: str) -> dict[str, ScheduleEntry]:
        """Clone a schedule branch so unrelated consumers keep the source graph."""
        source_ids = [
            item for item in graph.descendants(root_id)
            if graph.entries[item].object_type != "Schedule:File"
        ]
        used_names = {entry.name.casefold() for entry in graph.entries.values()}
        clones: dict[str, ScheduleEntry] = {}
        for source_id in reversed(source_ids):
            source = graph.entries[source_id]
            clone_name = self._clone_name(source.name, source.target_id, used_names)
            clone_obj = self._copy_object(graph.idf, source, clone_name)
            clones[source_id] = ScheduleEntry(
                target_id=ScheduleGraph.stable_target_id(source.object_type, clone_name),
                object_type=source.object_type,
                raw_key=source.raw_key,
                name=clone_name,
                obj=clone_obj,
                reference_fields=source.reference_fields,
            )
        for source_id, clone in clones.items():
            source = graph.entries[source_id]
            for field, name in source.reference_fields:
                child = graph.entry_for_name(name)
                if child and child.target_id in clones:
                    _set(clone.obj, field, clones[child.target_id].name)
        return clones

    @staticmethod
    def _clone_name(source_name: str, source_id: str, used_names: set[str]) -> str:
        stem = re.sub(r"[^A-Za-z0-9_\-]", "_", source_name) or "schedule"
        suffix = source_id.rsplit(":", 1)[-1][:8]
        candidate = f"{stem}__schedule_edit_{suffix}"
        counter = 2
        while candidate.casefold() in used_names:
            candidate = f"{stem}__schedule_edit_{suffix}_{counter}"
            counter += 1
        used_names.add(candidate.casefold())
        return candidate

    @staticmethod
    def _copy_object(idf: Any, source: ScheduleEntry, clone_name: str) -> Any:
        if not hasattr(idf, "newidfobject"):
            raise TypeError("clone_on_write requires an IDF implementation with newidfobject")
        try:
            target = idf.newidfobject(source.raw_key)
        except Exception:
            target = idf.newidfobject(source.object_type)
        for field in _field_names(source.obj):
            if field.casefold() == "name":
                continue
            try:
                _set(target, field, copy.deepcopy(_get(source.obj, field)))
            except (AttributeError, KeyError):
                # A schema version can omit an empty, deprecated source field.
                # It is safer to leave the IDD default than to synthesize one.
                continue
        _set(target, "Name", clone_name)
        return target


class GraphScheduleControlAdapter:
    """In-memory adapter used by generic HVAC-control operations.

    HVAC inspection has its own stable target IDs because a thermostat target
    is a zone-control concept, while this module identifies the concrete IDF
    consumer and terminal schedule objects.  The adapter deliberately resolves
    those records by their complete object/name/field/schedule identity, then
    delegates planning and clone-on-write to :class:`ScheduleEditor`.
    """

    def inspect_consumers(
        self, *, idf: Any, consumer_refs: list[dict[str, Any]]
    ) -> dict[str, Any]:
        graph = ScheduleGraph(idf)
        references, skipped = self._resolve_references(graph, consumer_refs)
        profiles: dict[str, dict[str, Any]] = {}
        for reference in references:
            root = graph.entry_for_name(reference["schedule_name"])
            if root is None:
                continue
            values: list[float] = []
            for leaf_id in graph.leaves(root.target_id):
                profile = graph.normalized_profile(graph.entries[leaf_id])
                for segment in profile.get("segments", []):
                    numeric = _as_number(segment.get("value"))
                    if numeric is not None:
                        values.append(numeric)
            if not values:
                skipped.append({
                    "consumer_id": reference["consumer_id"],
                    "schedule_name": reference["schedule_name"],
                    "reason": "referenced schedule has no complete numeric profile",
                })
                continue
            profiles[reference["schedule_name"]] = {
                "values": values,
                "min": min(values),
                "max": max(values),
            }
        return {"profiles": profiles, "skipped": skipped}

    def plan_delta(self, **kwargs: Any) -> dict[str, Any]:
        return self._plan(
            idf=kwargs["idf"],
            consumer_refs=kwargs.get("consumer_refs", []),
            operation="delta",
            value=kwargs.get("delta_c"),
            bounds=kwargs.get("bounds"),
            clone_on_write=kwargs.get("clone_on_write", True),
        )

    def plan_scale(self, **kwargs: Any) -> dict[str, Any]:
        return self._plan(
            idf=kwargs["idf"],
            consumer_refs=kwargs.get("consumer_refs", []),
            operation="scale",
            value=kwargs.get("factor"),
            bounds=kwargs.get("bounds"),
            clone_on_write=kwargs.get("clone_on_write", True),
        )

    def apply_schedule_plan(self, **kwargs: Any) -> dict[str, Any]:
        idf = kwargs["idf"]
        serialized = kwargs.get("plan") or {}
        graph = ScheduleGraph(idf)
        references, skipped = self._resolve_references(
            graph, list(serialized.get("consumer_references", []))
        )
        if skipped:
            return {"success": False, "error": "schedule consumers changed since planning", "skipped": skipped}
        editor = ScheduleEditor(idf_loader=lambda _path: idf)
        plan = editor._plan(
            graph,
            references,
            str(serialized.get("schedule_operation")),
            serialized.get("schedule_value"),
            None,
            serialized.get("bounds"),
            bool(serialized.get("clone_on_write_requested", True)),
        )
        if plan.coverage != "complete":
            return {
                "success": False,
                "error": "schedule plan is no longer complete",
                "coverage": plan.coverage,
                "skipped": plan.skipped,
                "ambiguous": plan.ambiguous,
            }
        editor._apply(graph, plan)
        return {"success": True}

    def _plan(
        self,
        *,
        idf: Any,
        consumer_refs: Sequence[Mapping[str, Any]],
        operation: str,
        value: Any,
        bounds: Optional[Mapping[str, Any]],
        clone_on_write: bool,
    ) -> dict[str, Any]:
        graph = ScheduleGraph(idf)
        references, skipped = self._resolve_references(graph, consumer_refs)
        if skipped:
            return {"changes": [], "skipped": skipped, "ambiguous": []}
        editor = ScheduleEditor(idf_loader=lambda _path: idf)
        plan = editor._plan(
            graph, references, operation, value, None, bounds, clone_on_write
        )
        rendered = editor._render_plan(
            editor._response_base("<in-memory>", None, "", operation, "dry_run", value),
            plan,
        )
        return {
            "schedule_operation": operation,
            "schedule_value": value,
            "bounds": dict(bounds or {}),
            "clone_on_write_requested": clone_on_write,
            "consumer_references": references,
            "changes": self._flatten_changes(rendered),
            "skipped": rendered["skipped"],
            "ambiguous": rendered["ambiguous"],
            "warnings": rendered["warnings"],
            "clone_on_write": rendered["shared_objects"],
            "shared_object_relationships": rendered["shared_objects"],
        }

    @staticmethod
    def _resolve_references(
        graph: ScheduleGraph, references: Sequence[Mapping[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        resolved: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for reference in references:
            matches = [
                consumer
                for consumer in graph.consumers.values()
                if all(
                    _consumer_reference_identity(
                        key, reference.get(key, getattr(consumer, key))
                    )
                    == _consumer_reference_identity(key, getattr(consumer, key))
                    for key in ("object_type", "object_name", "field", "schedule_name")
                )
            ]
            if len(matches) != 1:
                skipped.append({
                    "consumer_id": reference.get("consumer_id"),
                    "reason": "HVAC schedule consumer did not resolve uniquely in the schedule graph",
                })
                continue
            resolved.append(matches[0].public())
        return resolved, skipped

    @staticmethod
    def _flatten_changes(rendered: Mapping[str, Any]) -> list[dict[str, Any]]:
        before = rendered.get("before", [])
        after = rendered.get("after", [])
        return [
            {
                **{key: value for key, value in left.items() if key != "value"},
                "before": left.get("value"),
                "after": right.get("value"),
            }
            for left, right in zip(before, after)
        ]


def inspect_schedule_graph(idf: Any, scope: str = "all") -> dict[str, Any]:
    """Convenience in-memory inspection seam for domain and HVAC callers."""
    return ScheduleGraph(idf).inspect(scope)


def edit_schedule_graph(
    input_file: str,
    consumer_references: Sequence[Mapping[str, Any]],
    operation: str,
    value: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    """Convenience file-backed edit seam; see :class:`ScheduleEditor`."""
    return ScheduleEditor(
        idf_loader=kwargs.pop("idf_loader", None),
        path_resolver=kwargs.pop("path_resolver", None),
    ).edit(input_file, consumer_references, operation, value, **kwargs)
