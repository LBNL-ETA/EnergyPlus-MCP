"""Semantic, atomic coupled-occupancy operations for native IDFs.

This is not a people-density shortcut.  It ports the useful semantics of the
OpenStudio ``Set Occupancy Ratio`` reference measure: people are scaled (with
occupant-density guardrails), while non-per-person lighting and electric
equipment are scaled by the same ratio.  Watts/person loads remain unchanged
because the people definition is already changed.  Existing schedules and
scope assignments are never recreated or reassigned.

The module intentionally performs no simulation and has no calibration policy.
It returns deterministic plans that a domain manager can expose later.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

from .parameter_load_setters import _zone_geometry as _read_only_zone_geometry


DOMAIN = "internal_loads"
OPERATION = "set_occupancy_ratio"
PARAMETER = "OCC-RATIO"
MODEL_FORMAT = "idf"
RATIO_LIMITS = {"minimum": 0.5, "maximum": 1.0}
DENSITY_LIMITS = {"minimum": 0.01, "maximum": 0.4, "units": "people/m2"}

_SCOPE_FIELDS = (
    "Zone_or_ZoneList_or_Space_or_SpaceList_Name",
    "Zone_or_ZoneList_or_Space_or_SpaceList_Name",
    "Zone_or_ZoneList_Name",
)


def capabilities(idf: Any | None = None) -> dict[str, Any]:
    """Report whether one complete coupled-occupancy action is available."""
    inspection = inspect(idf) if idf is not None else {
        "coverage": "unverified",
        "supported": False,
        "applicable_targets": [],
        "skipped": [],
        "shared_relationships": [],
        "limits": _limits(),
    }
    return {
        "success": True,
        "domain": DOMAIN,
        "operation": "coupled_occupancy_capabilities",
        "model_format": MODEL_FORMAT,
        "parameter": PARAMETER,
        "actions": ["inspect_coupled_occupancy", OPERATION],
        "value_semantics": "absolute occupancy ratio multiplier applied atomically",
        **inspection,
    }


def inspect(idf: Any) -> dict[str, Any]:
    """Inspect complete semantic coverage without mutating an IDF."""
    records, preserved, skipped, relationships = _analyse(idf, ratio=None)
    coverage = _coverage(records, skipped)
    target = _target(records, preserved, relationships) if records else None
    return {
        "success": True,
        "domain": DOMAIN,
        "operation": "inspect_coupled_occupancy",
        "model_format": MODEL_FORMAT,
        "parameter": PARAMETER,
        "coverage": coverage,
        "supported": coverage == "complete",
        "applicable_targets": [target] if target else [],
        "preserved_per_person_loads": preserved,
        "shared_relationships": relationships,
        "skipped": skipped,
        "ambiguous": [item for item in skipped if item.get("classification") == "ambiguous"],
        "limits": _limits(),
    }


def plan(idf: Any, ratio: float) -> dict[str, Any]:
    """Return a non-mutating atomic plan for ``ratio``.

    A ratio is deliberately an absolute occupancy multiplier, not a
    percentage adjustment.  The reference measure accepts 0.5 through 1.0,
    so the native operation retains that guardrail until a separately reviewed
    generic occupancy policy expands it.
    """
    ratio_value = _number(ratio)
    if ratio_value is None or not RATIO_LIMITS["minimum"] <= ratio_value <= RATIO_LIMITS["maximum"]:
        return _failure(
            "requested occupancy ratio must be finite and between 0.5 and 1.0",
            requested_value=ratio,
        )
    records, preserved, skipped, relationships = _analyse(idf, ratio=ratio_value)
    coverage = _coverage(records, skipped)
    target = _target(records, preserved, relationships) if records else None
    before, after = _evidence(records)
    return {
        "success": coverage == "complete",
        "domain": DOMAIN,
        "operation": OPERATION,
        "model_format": MODEL_FORMAT,
        "parameter": PARAMETER,
        "coverage": coverage,
        "supported": coverage == "complete",
        "requested_value": ratio_value,
        "effective_value": ratio_value,
        "units": "fraction",
        "value_semantics": "absolute occupancy ratio multiplier applied atomically",
        "applicable_targets": [target] if target else [],
        "preserved_per_person_loads": preserved,
        "shared_relationships": relationships,
        "skipped": skipped,
        "ambiguous": [item for item in skipped if item.get("classification") == "ambiguous"],
        "limits": _limits(),
        "before": before,
        "after": after,
        "changes": _public_changes(records),
        "changed": any(not math.isclose(item["before"], item["after"], rel_tol=0.0, abs_tol=1e-12) for item in records),
    }


def execute(
    idf: Any,
    *,
    input_path: str,
    output_path: str,
    ratio: float,
    mode: str = "dry_run",
    expected_model_sha256: str | None = None,
) -> dict[str, Any]:
    """Plan or apply an occupancy action, binding writes to an input hash.

    ``idf`` is supplied by the owning EnergyPlus integration, which controls
    IDD/version loading.  This avoids creating a second model-loading stack.
    """
    source, destination, hash_or_error = _paths_and_hash(input_path, output_path)
    if source is None or destination is None:
        return _failure(hash_or_error)
    if expected_model_sha256 is not None and expected_model_sha256 != hash_or_error:
        return _failure("input model changed since inspection; inspect again before editing")
    if mode not in {"dry_run", "apply"}:
        return _failure("mode must be 'dry_run' or 'apply'")

    result = plan(idf, ratio)
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
    live_records, _preserved, _skipped, _relationships = _analyse(idf, ratio=float(ratio))
    try:
        _apply_records(live_records)
        destination.parent.mkdir(parents=True, exist_ok=True)
        idf.save(str(destination))
        result["output_sha256"] = hashlib.sha256(destination.read_bytes()).hexdigest()
    except Exception as error:
        # Restore all fields if saving fails; an output path is distinct from
        # input, so the source model remains unchanged on disk.
        _restore_records(live_records)
        result.update({
            "success": False,
            "changed": False,
            "error": f"failed to save coupled occupancy candidate: {error}",
        })
    return result


def _analyse(
    idf: Any, ratio: float | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    zones, zone_lists = _scopes(idf)
    records: list[dict[str, Any]] = []
    preserved: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    relationships: dict[str, dict[str, Any]] = {}

    people = _records_for_people(idf, zones, zone_lists, ratio, skipped, relationships)
    records.extend(people)
    if not people:
        skipped.append(_skip("People", "", "no supported People objects were found", "unsupported"))

    for object_type, method_field, scaled_methods, per_person_methods in (
        ("Lights", "Design_Level_Calculation_Method", {
            "lightinglevel": ("Lighting_Level",),
            "watts/area": ("Watts_per_Floor_Area", "Watts_per_Zone_Floor_Area"),
        }, {"watts/person"}),
        ("ElectricEquipment", "Design_Level_Calculation_Method", {
            "equipmentlevel": ("Design_Level",),
            "watts/area": ("Watts_per_Floor_Area", "Watts_per_Zone_Floor_Area"),
        }, {"watts/person"}),
    ):
        for obj in _objects(idf, object_type):
            name = _name(obj)
            scope, scope_error = _scope(obj, zones, zone_lists)
            if scope_error:
                skipped.append(_skip(object_type, name, scope_error, "ambiguous"))
                continue
            _relationship(relationships, scope, object_type, name)
            method_text = str(getattr(obj, method_field, ""))
            method = _method(method_text)
            if method in per_person_methods:
                preserved.append({
                    "object_type": object_type,
                    "object_name": name,
                    "scope": scope["name"],
                    "reason": "per-person load remains unchanged because People is scaled",
                })
                continue
            field = _present(obj, scaled_methods.get(method, ()))
            before = _number(getattr(obj, field, None)) if field else None
            if field is None or before is None or before < 0:
                skipped.append(_skip(
                    object_type, name,
                    f"unsupported or invalid active calculation method {method_text!r}",
                    "unsupported",
                ))
                continue
            after = before if ratio is None else before * ratio
            records.append(_record(
                obj, object_type, name, field, before, after, method_text, scope,
                semantic="non_per_person_load_scaled",
            ))

    return records, preserved, skipped, [relationships[key] for key in sorted(relationships)]


def _records_for_people(
    idf: Any,
    zones: dict[str, dict[str, Any]],
    zone_lists: dict[str, set[str]],
    ratio: float | None,
    skipped: list[dict[str, Any]],
    relationships: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    records = []
    methods = {
        "people": ("Number_of_People",),
        "number": ("Number_of_People",),
        "people/area": ("People_per_Floor_Area", "People_per_Zone_Floor_Area"),
        "area/person": ("Floor_Area_per_Person", "Zone_Floor_Area_per_Person"),
    }
    for obj in _objects(idf, "People"):
        name = _name(obj)
        scope, scope_error = _scope(obj, zones, zone_lists)
        if scope_error:
            skipped.append(_skip("People", name, scope_error, "ambiguous"))
            continue
        _relationship(relationships, scope, "People", name)
        method_text = str(getattr(obj, "Number_of_People_Calculation_Method", ""))
        method = _method(method_text)
        field = _present(obj, methods.get(method, ()))
        before = _number(getattr(obj, field, None)) if field else None
        if field is None or before is None or before < 0 or (method == "area/person" and before == 0):
            skipped.append(_skip(
                "People", name,
                f"unsupported or invalid active calculation method {method_text!r}",
                "unsupported",
            ))
            continue
        areas = [zones[key]["floor_area_m2"] for key in scope["zone_keys"]]
        area = 1.0
        if method in {"people", "number"}:
            if any(item is None or item <= 0 for item in areas):
                skipped.append(_skip(
                    "People", name,
                    "absolute people requires a positive resolved zone floor area for density bounds",
                    "ambiguous",
                ))
                continue
            if len(areas) > 1 and not _equal(areas):
                skipped.append(_skip(
                    "People", name,
                    "absolute people shared across unequal zones has ambiguous density bounds",
                    "ambiguous",
                ))
                continue
            area = float(areas[0])
        density = _density(method, before, area)
        if density is None:
            skipped.append(_skip("People", name, "cannot derive finite occupant density", "unsupported"))
            continue
        effective_density = density if ratio is None else _clamp(density * ratio)
        after = _field_for_density(method, effective_density, area)
        records.append(_record(
            obj, "People", name, field, before, after, method_text, scope,
            semantic="people_density_scaled_with_bounds",
            density_before=density,
            density_after=effective_density,
        ))
    return records


def _target(
    records: list[dict[str, Any]], preserved: list[dict[str, Any]], relationships: list[dict[str, Any]]
) -> dict[str, Any]:
    identities = sorted(
        f"{item['object_type']}|{item['object_name']}|{item['field']}|{item['scope']['name']}"
        for item in records
    )
    digest = hashlib.sha256("|".join(identities).encode()).hexdigest()[:16]
    return {
        "target_id": f"OCC-RATIO:coupled:{digest}",
        "units": "fraction",
        "value_definition": "one atomic ratio applied to People and non-per-person Lights/ElectricEquipment",
        "object_count": len(records),
        "preserved_per_person_load_count": len(preserved),
        "shared_scope_count": sum(1 for item in relationships if len(item["participants"]) > 1),
    }


def _coverage(records: list[dict[str, Any]], skipped: list[dict[str, Any]]) -> str:
    if any(item.get("classification") == "ambiguous" for item in skipped):
        return "ambiguous"
    if records and skipped:
        return "partial"
    if records:
        return "complete"
    return "none"


def _scopes(idf: Any) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]]]:
    """Resolve zone areas without changing the source model.

    ``Zone.Floor_Area`` is frequently blank in IDFs whose geometry is carried
    by ``BuildingSurface:Detailed``.  Reuse the load-setter geometry resolver:
    it derives an area only from readable Floor polygons and deliberately
    leaves it unset when geometry cannot prove one.  Absolute People methods
    retain their density-bound ambiguity in that latter case.
    """
    zones = {}
    for key, geometry in _read_only_zone_geometry(idf).items():
        zones[key] = {
            "name": geometry["name"],
            "floor_area_m2": geometry.get("floor_area_m2"),
        }
    zone_lists = {}
    for zone_list in _objects(idf, "ZoneList"):
        members = {_key(value) for value in _list_members(zone_list) if _key(value)}
        if members and members <= set(zones):
            zone_lists[_key(_name(zone_list))] = members
    return zones, zone_lists


def _scope(obj: Any, zones: dict[str, dict[str, Any]], zone_lists: dict[str, set[str]]) -> tuple[dict[str, Any] | None, str | None]:
    scope_name = next((str(getattr(obj, field, "")).strip() for field in _SCOPE_FIELDS if str(getattr(obj, field, "")).strip()), "")
    key = _key(scope_name)
    if key in zones:
        return {"name": zones[key]["name"], "zone_keys": [key]}, None
    if key in zone_lists:
        return {
            "name": scope_name,
            "zone_keys": sorted(zone_lists[key]),
        }, None
    return None, "scope does not resolve to a complete Zone or ZoneList; Space/SpaceList scopes require explicit support"


def _relationship(store: dict[str, dict[str, Any]], scope: dict[str, Any], object_type: str, name: str) -> None:
    item = store.setdefault(scope["name"], {
        "scope": scope["name"],
        "zone_keys": list(scope["zone_keys"]),
        "participants": [],
    })
    item["participants"].append({"object_type": object_type, "object_name": name})


def _record(obj: Any, object_type: str, name: str, field: str, before: float, after: float, method: str, scope: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "object": obj,
        "object_type": object_type,
        "object_name": name,
        "field": field,
        "before": before,
        "after": after,
        "calculation_method": method,
        "scope": scope,
        **extra,
    }


def _evidence(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    fields = ("object", "object_type", "object_name", "field", "before", "after", "scope", "semantic")
    before = [{key: item[key] for key in fields if key in item and key not in {"object", "after"}} for item in records]
    after = [{key: item[key] for key in fields if key in item and key not in {"object", "before"}} for item in records]
    return before, after


def _apply_records(records: list[dict[str, Any]]) -> None:
    applied = []
    try:
        for item in records:
            setattr(item["object"], item["field"], item["after"])
            applied.append(item)
    except Exception:
        for item in reversed(applied):
            setattr(item["object"], item["field"], item["before"])
        raise


def _restore_records(records: list[dict[str, Any]]) -> None:
    for item in reversed(records):
        setattr(item["object"], item["field"], item["before"])


def _public_changes(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: value for key, value in item.items() if key != "object"} for item in records]


def _paths_and_hash(input_path: str, output_path: str) -> tuple[Path | None, Path | None, str]:
    source = Path(input_path).expanduser()
    destination = Path(output_path).expanduser()
    if not source.is_file():
        return None, None, f"input_path must be an existing IDF: {source}"
    if source.resolve() == destination.resolve():
        return None, None, "output_path must differ from input_path"
    return source.resolve(), destination.resolve(), hashlib.sha256(source.read_bytes()).hexdigest()


def _limits() -> dict[str, Any]:
    return {"occupancy_ratio": dict(RATIO_LIMITS), "occupant_density": dict(DENSITY_LIMITS)}


def _density(method: str, value: float, area: float) -> float | None:
    if method in {"people", "number"}:
        return value / area
    if method == "people/area":
        return value
    if method == "area/person":
        return 1 / value
    return None


def _field_for_density(method: str, density: float, area: float) -> float:
    if method in {"people", "number"}:
        return density * area
    if method == "people/area":
        return density
    return 1 / density


def _clamp(value: float) -> float:
    return min(max(value, DENSITY_LIMITS["minimum"]), DENSITY_LIMITS["maximum"])


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _objects(idf: Any, object_type: str) -> list[Any]:
    return list(getattr(idf, "idfobjects", {}).get(object_type, []))


def _name(obj: Any) -> str:
    return str(getattr(obj, "Name", "")).strip() or "<unnamed>"


def _present(obj: Any, names: tuple[str, ...]) -> str | None:
    return next((name for name in names if hasattr(obj, name)), None)


def _method(value: str) -> str:
    return "".join(value.strip().casefold().split())


def _key(value: str) -> str:
    return value.strip().casefold()


def _list_members(zone_list: Any) -> list[str]:
    values = list(getattr(zone_list, "fieldvalues", []) or [])
    if len(values) > 2:
        return [str(value) for value in values[2:] if str(value).strip()]
    return [
        str(value) for field, value in vars(zone_list).items()
        if field.casefold().startswith("zone") and field != "Name" and str(value).strip()
    ]


def _equal(values: list[float]) -> bool:
    return all(math.isclose(value, values[0], rel_tol=1e-9, abs_tol=1e-12) for value in values[1:])


def _skip(object_type: str, object_name: str, reason: str, classification: str) -> dict[str, Any]:
    return {"object_type": object_type, "object_name": object_name, "reason": reason, "classification": classification}


def _failure(message: str, **extra: Any) -> dict[str, Any]:
    return {
        "success": False,
        "domain": DOMAIN,
        "operation": OPERATION,
        "model_format": MODEL_FORMAT,
        "parameter": PARAMETER,
        "coverage": "none",
        "supported": False,
        "changed": False,
        "error": message,
        **extra,
    }
