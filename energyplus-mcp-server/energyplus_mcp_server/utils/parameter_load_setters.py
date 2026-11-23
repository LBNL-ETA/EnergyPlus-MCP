"""Inspectable absolute native-IDF semantic parameter setters.

The source OpenStudio measures recreate loads as new density definitions.  A
native IDF plan deliberately does not recreate objects: it keeps the original
objects, schedules, and active calculation methods, then applies one factor to
each object's active value.  A target is only offered when that factor reaches
the requested canonical density in every affected zone.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

from . import parameter_loads
from .geometry_utils import extract_vertices


PARAMETERS = ("LPD", "EPD", "OCD", "INF", "WIN-U", "WIN-SHGC")

_SCOPE_FIELDS = (
    "Zone_or_ZoneList_or_Space_or_SpaceList_Name",
    "Zone_or_ZoneList_Name",
)
_LOAD_SPECS = {
    "LPD": {
        "object_type": "Lights",
        "method_field": "Design_Level_Calculation_Method",
        "fields": {
            "lightinglevel": "Lighting_Level",
            "watts/area": ("Watts_per_Floor_Area", "Watts_per_Zone_Floor_Area"),
            "watts/person": "Watts_per_Person",
        },
        "units": "W/m2",
        "basis": "floor_area_m2",
    },
    "EPD": {
        "object_type": "ElectricEquipment",
        "method_field": "Design_Level_Calculation_Method",
        "fields": {
            "equipmentlevel": "Design_Level",
            "watts/area": ("Watts_per_Floor_Area", "Watts_per_Zone_Floor_Area"),
            "watts/person": "Watts_per_Person",
        },
        "units": "W/m2",
        "basis": "floor_area_m2",
    },
    "OCD": {
        "object_type": "People",
        "method_field": "Number_of_People_Calculation_Method",
        "fields": {
            "people": "Number_of_People",
            "number": "Number_of_People",
            "people/area": ("People_per_Floor_Area", "People_per_Zone_Floor_Area"),
            "area/person": ("Floor_Area_per_Person", "Zone_Floor_Area_per_Person"),
        },
        "units": "people/m2",
        "basis": "floor_area_m2",
    },
    "INF": {
        "object_type": "ZoneInfiltration:DesignFlowRate",
        "method_field": "Design_Flow_Rate_Calculation_Method",
        "fields": {
            "flow/zone": "Design_Flow_Rate",
            "flow/area": ("Flow_Rate_per_Zone_Floor_Area", "Flow_per_Zone_Floor_Area"),
            "flow/exteriorarea": (
                "Flow_Rate_per_Exterior_Surface_Area",
                "Flow_per_Exterior_Surface_Area",
            ),
            "flow/exteriorwallarea": (
                "Flow_Rate_per_Exterior_Surface_Area",
                "Flow_per_Exterior_Surface_Area",
            ),
            "airchanges/hour": "Air_Changes_per_Hour",
        },
        "units": "m3/s/m2",
        "basis": "exterior_surface_area_m2",
    },
}


def inspect(
    idf: Any, parameter: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return stable absolute-set targets and any unsupported source coverage."""
    _, targets, skipped = _inspect_details(idf, parameter)
    return targets, skipped


def plan_set(
    idf: Any,
    parameter: str,
    value: float,
    target_ids: list[str] | tuple[str, ...] | str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Plan a non-mutating absolute setter for all or selected independent targets."""
    normalized_parameter = _parameter(parameter)
    details, _, skipped = _inspect_details(idf, normalized_parameter)
    if skipped:
        return [], skipped

    requested = _number(value)
    if requested is None:
        return [], [
            {
                "parameter": normalized_parameter,
                "reason": "absolute value must be a finite number",
            }
        ]
    value_error = _value_error(normalized_parameter, requested)
    if value_error:
        return [], [{"parameter": normalized_parameter, "reason": value_error}]

    detail_by_id = {detail["target"]["target_id"]: detail for detail in details}
    selected_ids, selection_skipped = _selected_ids(target_ids, detail_by_id)
    if selection_skipped:
        return [], selection_skipped

    planned: list[dict[str, Any]] = []
    for target_id in selected_ids:
        detail = detail_by_id[target_id]
        if detail["kind"] == "window":
            planned.append(
                _planned(
                    detail["object"],
                    "WindowMaterial:SimpleGlazingSystem",
                    parameter_loads._object_name(detail["object"]),
                    detail["field"],
                    detail["value"],
                    requested,
                )
            )
            continue

        current = detail["value"]
        if current == 0 and requested > 0:
            return [], [
                _target_skip(
                    target_id,
                    "zero current density cannot be set to a nonzero value without creating or redistributing objects",
                )
            ]
        factor = 1.0 if current == 0 else requested / current
        for record in detail["records"]:
            changes, error = _scaled_changes(record, factor)
            if error:
                return [], [_target_skip(target_id, error)]
            planned.extend(changes)

    return planned, []


def _inspect_details(
    idf: Any,
    parameter: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    parameter = _parameter(parameter)
    if parameter not in PARAMETERS:
        return (
            [],
            [],
            [
                {
                    "parameter": parameter or str(parameter),
                    "reason": f"unsupported absolute semantic parameter; expected one of {', '.join(PARAMETERS)}",
                }
            ],
        )
    if parameter in {"WIN-U", "WIN-SHGC"}:
        return _window_details(idf, parameter)

    geometry = _zone_geometry(idf)
    resolver = _ScopeResolver(idf, geometry)
    records, skipped = _load_records(idf, parameter, resolver)
    if parameter in {"LPD", "EPD"}:
        people_by_zone, people_skipped = _people_by_zone(idf, resolver, geometry)
        for record in records[:]:
            if record["method"] != "watts/person":
                continue
            if any(zone not in people_by_zone for zone in record["zones"]):
                records.remove(record)
                skipped.append(
                    _record_skip(
                        record,
                        "Watts/Person requires a complete, resolvable People calculation for every affected zone",
                    )
                )
        if any(record["method"] == "watts/person" for record in records):
            skipped.extend(people_skipped)

    details: list[dict[str, Any]] = []
    for component in _components(records):
        detail, component_skip = _component_detail(
            parameter,
            component,
            geometry,
            people_by_zone if parameter in {"LPD", "EPD"} else {},
        )
        if component_skip:
            skipped.append(component_skip)
        else:
            details.append(detail)
    return details, [detail["target"] for detail in details], skipped


def _window_details(
    idf: Any,
    parameter: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    planned, skipped = parameter_loads.plan(idf, parameter, 0)
    field = "UFactor" if parameter == "WIN-U" else "Solar_Heat_Gain_Coefficient"
    units = "W/m2-K" if parameter == "WIN-U" else "fraction"
    details = []
    for change in planned:
        object_name = change["object_name"]
        target = {
            "target_id": _target_id(parameter, [f"material:{object_name}"]),
            "value": change["before"],
            "units": units,
            "basis": {
                "value_definition": f"{field} of the safe window SimpleGlazingSystem material"
            },
            "object_names": [object_name],
        }
        details.append(
            {
                "kind": "window",
                "target": target,
                "object": change["object"],
                "field": field,
                "value": change["before"],
            }
        )
    return details, [detail["target"] for detail in details], skipped


def _load_records(
    idf: Any,
    parameter: str,
    resolver: "_ScopeResolver",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    spec = _LOAD_SPECS[parameter]
    records: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for obj in parameter_loads._objects(idf, spec["object_type"]):
        object_name = parameter_loads._object_name(obj)
        method = str(getattr(obj, spec["method_field"], "")).strip()
        normalized_method = _method(method)
        field_spec = spec["fields"].get(normalized_method)
        if field_spec is None:
            skipped.append(
                _skip(
                    spec["object_type"],
                    object_name,
                    f"unsupported active calculation method {method!r}",
                )
            )
            continue
        field = _present_field(obj, field_spec)
        if field is None:
            skipped.append(
                _skip(
                    spec["object_type"],
                    object_name,
                    "supported calculation method has no recognized active input field",
                )
            )
            continue
        before = _number(getattr(obj, field, None))
        if (
            before is None
            or before < 0
            or (normalized_method == "area/person" and before == 0)
        ):
            skipped.append(
                _skip(
                    spec["object_type"],
                    object_name,
                    "active source field is invalid for an absolute setter",
                    field=field,
                )
            )
            continue
        scope = _first_text(obj, _SCOPE_FIELDS)
        zones = resolver.resolve(scope)
        if zones is None:
            skipped.append(
                _skip(
                    spec["object_type"],
                    object_name,
                    resolver.reason(scope)
                    or "object does not resolve to a supported Zone or ZoneList scope",
                )
            )
            continue
        records.append(
            {
                "object": obj,
                "object_type": spec["object_type"],
                "object_name": object_name,
                "method": normalized_method,
                "method_text": method,
                "method_field": spec["method_field"],
                "field": field,
                "before": before,
                "zones": zones,
                "parameter": parameter,
            }
        )

    if parameter == "EPD":
        for obj in parameter_loads._objects(idf, "ElectricEquipment:ITE:AirCooled"):
            skipped.append(
                _skip(
                    "ElectricEquipment:ITE:AirCooled",
                    parameter_loads._object_name(obj),
                    "ITE equipment is outside the EPD absolute-set MVP",
                )
            )
    if parameter == "INF":
        skipped.extend(parameter_loads._unsupported_infiltration_objects(idf))
    return records, skipped


def _people_by_zone(
    idf: Any,
    resolver: "_ScopeResolver",
    geometry: dict[str, dict[str, Any]],
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    records, skipped = _load_records(idf, "OCD", resolver)
    people_by_zone = {key: 0.0 for key in geometry}
    invalid_zones: set[str] = set()
    for record in records:
        for zone in record["zones"]:
            value, error = _zone_quantity("OCD", record, geometry[zone], {})
            if error:
                invalid_zones.add(zone)
            else:
                people_by_zone[zone] += value
    for zone in invalid_zones:
        people_by_zone.pop(zone, None)
    return people_by_zone, skipped


def _components(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    for record in records:
        matches = [
            component
            for component in components
            if component["zones"] & record["zones"]
        ]
        if not matches:
            components.append({"zones": set(record["zones"]), "records": [record]})
            continue
        primary = matches[0]
        primary["zones"].update(record["zones"])
        primary["records"].append(record)
        for component in matches[1:]:
            primary["zones"].update(component["zones"])
            primary["records"].extend(component["records"])
            components.remove(component)
    return components


def _component_detail(
    parameter: str,
    component: dict[str, Any],
    geometry: dict[str, dict[str, Any]],
    people_by_zone: dict[str, float],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    spec = _LOAD_SPECS[parameter]
    basis_field = spec["basis"]
    zone_values: dict[str, float] = {}
    zone_basis: dict[str, float] = {}
    nonapplicable_zones: list[str] = []
    for zone in sorted(component["zones"]):
        zone_geometry = geometry[zone]
        basis = zone_geometry.get(basis_field)
        if basis is None:
            return None, _component_skip(
                parameter,
                component,
                f"missing positive {basis_field} for zone {zone_geometry['name']}",
            )
        if basis <= 0:
            if parameter == "INF" and _zero_infiltration_in_zero_basis_zone(
                component["records"], zone_geometry
            ):
                nonapplicable_zones.append(zone_geometry["name"])
                continue
            return None, _component_skip(
                parameter,
                component,
                f"missing positive {basis_field} for zone {zone_geometry['name']}",
            )
        numerator = 0.0
        for record in component["records"]:
            if zone not in record["zones"]:
                continue
            quantity, error = _zone_quantity(
                parameter, record, zone_geometry, people_by_zone
            )
            if error:
                return None, _component_skip(parameter, component, error)
            numerator += quantity * zone_geometry["multiplier"]
        weighted_basis = basis * zone_geometry["multiplier"]
        zone_values[zone] = numerator / weighted_basis
        zone_basis[zone] = weighted_basis

    values = list(zone_values.values())
    if not values:
        return None, _component_skip(
            parameter,
            component,
            f"missing positive {basis_field} for every affected zone",
        )
    if not all(
        math.isclose(value, values[0], rel_tol=1e-9, abs_tol=1e-12)
        for value in values[1:]
    ):
        return None, _component_skip(
            parameter,
            component,
            "affected zones have different canonical densities; setting one shared target would require clone or redistribution",
        )
    zone_names = [geometry[zone]["name"] for zone in sorted(component["zones"])]
    total_basis = sum(zone_basis.values())
    target = {
        "target_id": _target_id(parameter, sorted(component["zones"])),
        "value": values[0],
        "units": spec["units"],
        "zone_names": zone_names,
        "basis": {
            basis_field: total_basis,
            "per_zone_value": {
                geometry[zone]["name"]: zone_values[zone]
                for zone in sorted(zone_values)
            },
            "value_definition": _value_definition(parameter),
        },
        "object_names": [record["object_name"] for record in component["records"]],
    }
    if nonapplicable_zones:
        target["nonapplicable_zone_names"] = nonapplicable_zones
    if values[0] == 0:
        target["limitations"] = [
            "zero source density can be verified or set to zero; setting it positive requires object creation or redistribution",
        ]
    return {
        "kind": "load",
        "target": target,
        "value": values[0],
        "records": component["records"],
    }, None


def _zero_infiltration_in_zero_basis_zone(
    records: list[dict[str, Any]], geometry: dict[str, Any]
) -> bool:
    """Return whether every active source has provably zero flow in this zone.

    A shared Flow/ExteriorArea object legitimately has zero flow in an interior
    zone.  That zone has no exterior-area density and is excluded from the
    denominator, while an unknown or potentially nonzero contribution remains
    unsupported.
    """
    for record in records:
        if geometry["key"] not in record["zones"]:
            continue
        if not geometry.get("has_surface_geometry"):
            return False
        if record["before"] == 0:
            continue
        if (
            record["method"] == "flow/exteriorarea"
            and geometry.get("exterior_surface_area_m2") == 0
        ):
            continue
        if (
            record["method"] == "flow/exteriorwallarea"
            and geometry.get("exterior_wall_area_m2") == 0
        ):
            continue
        return False
    return True


def _zone_quantity(
    parameter: str,
    record: dict[str, Any],
    geometry: dict[str, Any],
    people_by_zone: dict[str, float],
) -> tuple[float, str | None]:
    before = record["before"]
    method = record["method"]
    if parameter in {"LPD", "EPD"}:
        if method in {"lightinglevel", "equipmentlevel"}:
            return before, None
        if method == "watts/area":
            floor_area = geometry.get("floor_area_m2")
            if floor_area is None or floor_area <= 0:
                return (
                    0.0,
                    f"Watts/Area requires positive floor area for {geometry['name']}",
                )
            return before * floor_area, None
        if method == "watts/person":
            return before * people_by_zone.get(geometry["key"], 0.0), None
    if parameter == "OCD":
        if method in {"people", "number"}:
            return before, None
        if method == "people/area":
            floor_area = geometry.get("floor_area_m2")
            if floor_area is None or floor_area <= 0:
                return (
                    0.0,
                    f"People/Area requires positive floor area for {geometry['name']}",
                )
            return before * floor_area, None
        if method == "area/person":
            floor_area = geometry.get("floor_area_m2")
            if floor_area is None or floor_area <= 0:
                return (
                    0.0,
                    f"Area/Person requires positive floor area for {geometry['name']}",
                )
            return floor_area / before, None
    if parameter == "INF":
        if method == "flow/zone":
            return before, None
        if method == "flow/area":
            floor_area = geometry.get("floor_area_m2")
            if floor_area is None or floor_area <= 0:
                return (
                    0.0,
                    f"Flow/Area requires positive floor area for {geometry['name']}",
                )
            return before * floor_area, None
        if method == "flow/exteriorarea":
            return before * geometry["exterior_surface_area_m2"], None
        if method == "flow/exteriorwallarea":
            return before * geometry["exterior_wall_area_m2"], None
        if method == "airchanges/hour":
            volume = geometry.get("volume_m3")
            if volume is None or volume <= 0:
                return (
                    0.0,
                    f"AirChanges/Hour requires positive explicit Zone Volume for {geometry['name']}",
                )
            return before * volume / 3600.0, None
    return 0.0, f"unsupported calculation method {record['method_text']!r}"


def _scaled_changes(
    record: dict[str, Any],
    factor: float,
) -> tuple[list[dict[str, Any]], str | None]:
    if record["method"] == "area/person":
        if factor == 0:
            density_field = _present_field(
                record["object"], _LOAD_SPECS["OCD"]["fields"]["people/area"]
            )
            if density_field is None:
                return [], "Area/Person cannot be normalized to People/Area in this IDD"
            return [
                _planned(
                    record["object"],
                    record["object_type"],
                    record["object_name"],
                    record["method_field"],
                    record["method_text"],
                    "People/Area",
                ),
                _planned(
                    record["object"],
                    record["object_type"],
                    record["object_name"],
                    density_field,
                    getattr(record["object"], density_field, ""),
                    0.0,
                ),
            ], None
        after = record["before"] / factor
    else:
        after = record["before"] * factor
    if not math.isfinite(after) or after < 0:
        return [], "requested absolute value produces an invalid active field"
    return [
        _planned(
            record["object"],
            record["object_type"],
            record["object_name"],
            record["field"],
            record["before"],
            after,
            record["method_text"],
        )
    ], None


def _zone_geometry(idf: Any) -> dict[str, dict[str, Any]]:
    zones: dict[str, dict[str, Any]] = {}
    for zone in parameter_loads._objects(idf, "Zone"):
        name = parameter_loads._object_name(zone)
        key = _name(name)
        if not key:
            continue
        floor_area = _number(getattr(zone, "Floor_Area", None))
        zones[key] = {
            "key": key,
            "name": name,
            "floor_area_m2": floor_area
            if floor_area is not None and floor_area > 0
            else None,
            "derived_floor_area_m2": 0.0,
            "exterior_surface_area_m2": 0.0,
            "exterior_wall_area_m2": 0.0,
            "has_surface_geometry": False,
            "volume_m3": _positive_number(getattr(zone, "Volume", None)),
            "multiplier": _positive_number(getattr(zone, "Multiplier", None)) or 1.0,
        }
    for surface in parameter_loads._objects(idf, "BuildingSurface:Detailed"):
        zone_key = _name(str(getattr(surface, "Zone_Name", "")))
        if zone_key not in zones:
            continue
        area = _surface_area(surface)
        if area is None or area <= 0:
            continue
        zones[zone_key]["has_surface_geometry"] = True
        surface_type = _method(str(getattr(surface, "Surface_Type", "")))
        outside = _method(str(getattr(surface, "Outside_Boundary_Condition", "")))
        if surface_type == "floor":
            zones[zone_key]["derived_floor_area_m2"] += area
        if outside == "outdoors":
            zones[zone_key]["exterior_surface_area_m2"] += area
            if surface_type == "wall":
                zones[zone_key]["exterior_wall_area_m2"] += area
    for zone in zones.values():
        if zone["floor_area_m2"] is None and zone["derived_floor_area_m2"] > 0:
            zone["floor_area_m2"] = zone["derived_floor_area_m2"]
    return zones


class _ScopeResolver:
    def __init__(self, idf: Any, geometry: dict[str, dict[str, Any]]) -> None:
        self._zones = geometry
        self._zone_lists: dict[str, set[str]] = {}
        self._invalid_zone_lists: dict[str, str] = {}
        for zone_list in parameter_loads._objects(idf, "ZoneList"):
            list_key = _name(parameter_loads._object_name(zone_list))
            members = set(_zone_list_members(zone_list))
            if not list_key:
                continue
            if not members:
                self._invalid_zone_lists[list_key] = (
                    "ZoneList has no readable zone members"
                )
                continue
            unknown = sorted(members - geometry.keys())
            if unknown:
                self._invalid_zone_lists[list_key] = (
                    "ZoneList references missing Zone member(s): " + ", ".join(unknown)
                )
                continue
            self._zone_lists[list_key] = members

    def resolve(self, scope: str | None) -> set[str] | None:
        key = _name(scope or "")
        if key in self._zones:
            return {key}
        if key in self._zone_lists:
            return set(self._zone_lists[key])
        return None

    def reason(self, scope: str | None) -> str | None:
        return self._invalid_zone_lists.get(_name(scope or ""))


def _zone_list_members(zone_list: Any) -> list[str]:
    members: list[str] = []
    fieldvalues = getattr(zone_list, "fieldvalues", [])
    # Eppy stores the object type and ZoneList Name before its extensible zone
    # members.  Do not treat an unresolvable member as harmless partial scope.
    for value in fieldvalues[2:]:
        key = _name(str(value))
        if key:
            members.append(key)
    if members:
        return members
    for field, value in vars(zone_list).items():
        if field != "Name" and field.casefold().startswith("zone"):
            key = _name(str(value))
            if key:
                members.append(key)
    return members


def _surface_area(surface: Any) -> float | None:
    vertices = getattr(surface, "Vertices", None) or extract_vertices(surface)
    if len(vertices) < 3:
        return None
    normal = [0.0, 0.0, 0.0]
    for index, point in enumerate(vertices):
        next_point = vertices[(index + 1) % len(vertices)]
        normal[0] += (point[1] - next_point[1]) * (point[2] + next_point[2])
        normal[1] += (point[2] - next_point[2]) * (point[0] + next_point[0])
        normal[2] += (point[0] - next_point[0]) * (point[1] + next_point[1])
    return 0.5 * math.sqrt(sum(value * value for value in normal))


def _selected_ids(
    target_ids: Any,
    detail_by_id: dict[str, dict[str, Any]],
) -> tuple[list[str], list[dict[str, Any]]]:
    if target_ids is None:
        return list(detail_by_id), []
    try:
        values = [target_ids] if isinstance(target_ids, str) else list(target_ids)
    except TypeError:
        return [], [
            {"reason": "target_ids must be a target ID or an iterable of target IDs"}
        ]
    if not values:
        return [], [{"reason": "target_ids must not be empty"}]
    if any(not isinstance(target_id, str) for target_id in values):
        return [], [{"reason": "target_ids must contain only strings"}]
    if len(set(values)) != len(values):
        return [], [{"reason": "target_ids must not contain duplicates"}]
    unknown = [
        str(target_id) for target_id in values if str(target_id) not in detail_by_id
    ]
    if unknown:
        return [], [
            _target_skip(target_id, "unknown target_id") for target_id in unknown
        ]
    return values, []


def _value_error(parameter: str, value: float) -> str | None:
    if parameter in {"LPD", "EPD", "OCD", "INF"} and value < 0:
        return f"{parameter} absolute value must be non-negative"
    if parameter == "WIN-U" and value <= 0:
        return "WIN-U absolute value must be greater than 0"
    if parameter == "WIN-SHGC" and not 0 < value <= 1:
        return "WIN-SHGC absolute value must be greater than 0 and no more than 1"
    return None


def _value_definition(parameter: str) -> str:
    return {
        "LPD": "total active lighting design power divided by each zone floor area",
        "EPD": "total active electric-equipment design power divided by each zone floor area",
        "OCD": "total design people divided by each zone floor area",
        "INF": "total design infiltration flow divided by each zone exterior surface area",
    }[parameter]


def _target_id(parameter: str, parts: list[str]) -> str:
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
    return f"{parameter}:zones:{digest}"


def _component_skip(
    parameter: str, component: dict[str, Any], reason: str
) -> dict[str, Any]:
    return {
        "object_type": parameter,
        "object_name": ", ".join(
            sorted({record["object_name"] for record in component["records"]})
        ),
        "reason": reason,
    }


def _record_skip(record: dict[str, Any], reason: str) -> dict[str, Any]:
    return _skip(
        record["object_type"], record["object_name"], reason, field=record["field"]
    )


def _target_skip(target_id: str, reason: str) -> dict[str, Any]:
    return {"target_id": target_id, "reason": reason}


def _planned(
    obj: Any,
    object_type: str,
    object_name: str,
    field: str,
    before: Any,
    after: Any,
    calculation_method: str | None = None,
) -> dict[str, Any]:
    change = {
        "object": obj,
        "object_type": object_type,
        "object_name": object_name,
        "field": field,
        "before": before,
        "after": after,
    }
    if calculation_method is not None:
        change["calculation_method"] = calculation_method
    return change


def _skip(
    object_type: str, object_name: str, reason: str, *, field: str | None = None
) -> dict[str, Any]:
    item = {"object_type": object_type, "object_name": object_name, "reason": reason}
    if field is not None:
        item["field"] = field
    return item


def _present_field(obj: Any, fields: str | tuple[str, ...]) -> str | None:
    names = (fields,) if isinstance(fields, str) else fields
    return next((field for field in names if hasattr(obj, field)), None)


def _first_text(obj: Any, fields: tuple[str, ...]) -> str | None:
    for field in fields:
        value = str(getattr(obj, field, "")).strip()
        if value:
            return value
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive_number(value: Any) -> float | None:
    number = _number(value)
    return number if number is not None and number > 0 else None


def _parameter(parameter: Any) -> str:
    return parameter.strip().upper() if isinstance(parameter, str) else ""


def _method(value: str) -> str:
    return "".join(value.strip().casefold().split())


def _name(value: str) -> str:
    return value.strip().casefold()
