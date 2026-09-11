"""Non-mutating native-IDF plans for internal-load and envelope parameters.

The parameter-operation caller owns validation, applying a plan, and saving the
candidate IDF.  Keeping discovery and arithmetic here side-effect free makes
the same operation safe to use for both model capability checks and a later
perturbation.
"""

from __future__ import annotations

import math
from typing import Any


PARAMETERS = ("EPD", "OCD", "INF", "WIN-U", "WIN-SHGC")


def plan(idf: Any, parameter: str, percentage: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Plan a signed percentage change without mutating ``idf``.

    ``percentage`` is converted to ``1 + percentage / 100``.  The returned
    planned entries retain their IDF object only for the caller to apply after
    the complete model has passed its support gate; skipped entries are plain
    metadata suitable for a capability or failure response.
    """
    normalized_parameter = _normalize_parameter(parameter)
    if normalized_parameter not in PARAMETERS:
        return [], [{
            "parameter": normalized_parameter or str(parameter),
            "reason": f"unsupported semantic parameter; expected one of {', '.join(PARAMETERS)}",
        }]

    percent = _as_finite_number(percentage)
    if percent is None:
        return [], [{
            "parameter": normalized_parameter,
            "reason": "percentage must be a finite number",
        }]
    factor = 1.0 + percent / 100.0
    if not math.isfinite(factor):
        return [], [{
            "parameter": normalized_parameter,
            "reason": "percentage produces a non-finite scaling factor",
        }]

    if normalized_parameter == "EPD":
        planned, skipped = _plan_active_field(
            idf=idf,
            parameter=normalized_parameter,
            object_type="ElectricEquipment",
            method_field="Design_Level_Calculation_Method",
            fields_by_method={
                "equipmentlevel": "Design_Level",
                "watts/area": ("Watts_per_Floor_Area", "Watts_per_Zone_Floor_Area"),
                "watts/person": "Watts_per_Person",
            },
            factor=factor,
        )
        skipped.extend(_unsupported_epd_objects(idf))
        return planned, skipped
    if normalized_parameter == "OCD":
        return _plan_active_field(
            idf=idf,
            parameter=normalized_parameter,
            object_type="People",
            method_field="Number_of_People_Calculation_Method",
            fields_by_method={
                "people": "Number_of_People",
                "number": "Number_of_People",
                "people/area": ("People_per_Floor_Area", "People_per_Zone_Floor_Area"),
                "area/person": ("Floor_Area_per_Person", "Zone_Floor_Area_per_Person"),
            },
            factor=factor,
            inverse_methods={"area/person"},
        )
    if normalized_parameter == "INF":
        planned, skipped = _plan_active_field(
            idf=idf,
            parameter=normalized_parameter,
            object_type="ZoneInfiltration:DesignFlowRate",
            method_field="Design_Flow_Rate_Calculation_Method",
            fields_by_method={
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
            factor=factor,
        )
        skipped.extend(_unsupported_infiltration_objects(idf))
        return planned, skipped
    return _plan_window_simple_glazing(idf, normalized_parameter, factor)


def _plan_active_field(
    *,
    idf: Any,
    parameter: str,
    object_type: str,
    method_field: str,
    fields_by_method: dict[str, str | tuple[str, ...]],
    factor: float,
    inverse_methods: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    planned: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    inverse_methods = inverse_methods or set()

    for obj in _objects(idf, object_type):
        object_name = _object_name(obj)
        method = str(getattr(obj, method_field, "")).strip()
        normalized_method = _normalize_method(method)
        field_names = fields_by_method.get(normalized_method)
        if field_names is None:
            skipped.append(_skip(
                object_type,
                object_name,
                f"unsupported active calculation method {method!r}",
                calculation_method=method,
            ))
            continue
        field = _present_field(obj, field_names)
        if field is None:
            aliases = ", ".join(_field_names(field_names))
            skipped.append(_skip(
                object_type,
                object_name,
                f"supported calculation method has no recognized active input field ({aliases})",
                calculation_method=method,
            ))
            continue

        before = _as_finite_number(getattr(obj, field, None))
        if before is None:
            skipped.append(_skip(
                object_type,
                object_name,
                "active input field is not a finite number",
                field=field,
                calculation_method=method,
            ))
            continue

        if before < 0:
            skipped.append(_skip(
                object_type,
                object_name,
                "active input field must be non-negative",
                field=field,
                calculation_method=method,
            ))
            continue

        if normalized_method in inverse_methods:
            if before == 0:
                skipped.append(_skip(
                    object_type,
                    object_name,
                    "Area/Person must be greater than 0",
                    field=field,
                    calculation_method=method,
                ))
                continue
            if factor == 0:
                skipped.append(_skip(
                    object_type,
                    object_name,
                    "percentage -100 is invalid for Area/Person because its field scales inversely",
                    field=field,
                    calculation_method=method,
                ))
                continue
            after = before / factor
        else:
            after = before * factor

        if not math.isfinite(after):
            skipped.append(_skip(
                object_type,
                object_name,
                "requested percentage produces a non-finite value",
                field=field,
                calculation_method=method,
            ))
            continue
        planned.append(_planned(obj, object_type, object_name, field, before, after, method))

    return planned, skipped


def _plan_window_simple_glazing(
    idf: Any,
    parameter: str,
    factor: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Plan a change to simple glazing referenced by actual window surfaces.

    A direct material-field edit cannot reproduce the source measure's cloning
    behavior.  We therefore reject a material shared with a non-window
    fenestration construction instead of silently changing a glass door.
    """
    planned: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    surfaces = _objects(idf, "FenestrationSurface:Detailed")
    construction_by_name = _construction_by_name(idf)
    simple_glazing_by_name = {
        _normalized_name(_object_name(material)): material
        for material in _objects(idf, "WindowMaterial:SimpleGlazingSystem")
        if _normalized_name(_object_name(material))
    }
    surface_types_by_construction: dict[str, set[str]] = {}
    for surface in surfaces:
        construction_name = str(getattr(surface, "Construction_Name", "")).strip()
        if construction_name:
            surface_types_by_construction.setdefault(_normalized_name(construction_name), set()).add(
                _normalize_method(str(getattr(surface, "Surface_Type", "")))
            )

    selected_materials: dict[str, Any] = {}
    handled_constructions: set[str] = set()
    for surface in surfaces:
        if _normalize_method(str(getattr(surface, "Surface_Type", ""))) != "window":
            continue
        surface_name = _object_name(surface)
        construction_name = str(getattr(surface, "Construction_Name", "")).strip()
        construction_key = _normalized_name(construction_name)
        if not construction_key or construction_key not in construction_by_name:
            skipped.append(_skip(
                "FenestrationSurface:Detailed",
                surface_name,
                "window references a missing construction",
                field="Construction_Name",
            ))
            continue
        if construction_key in handled_constructions:
            continue
        handled_constructions.add(construction_key)

        construction = construction_by_name[construction_key]
        layers = _construction_layers(construction)
        material = simple_glazing_by_name.get(_normalized_name(layers[0])) if len(layers) == 1 else None
        if material is None:
            skipped.append(_skip(
                "Construction",
                _object_name(construction),
                "window construction is layered or does not use a single WindowMaterial:SimpleGlazingSystem",
            ))
            continue

        material_key = _normalized_name(_object_name(material))
        if _material_has_nonwindow_use(
            material_key,
            construction_by_name,
            surface_types_by_construction,
        ):
            skipped.append(_skip(
                "Construction",
                _object_name(construction),
                "simple-glazing material is shared with a non-window fenestration construction; cloning is required",
            ))
            continue
        selected_materials[material_key] = material

    field = "UFactor" if parameter == "WIN-U" else "Solar_Heat_Gain_Coefficient"
    for material in selected_materials.values():
        object_name = _object_name(material)
        before = _as_finite_number(getattr(material, field, None))
        if before is None:
            skipped.append(_skip(
                "WindowMaterial:SimpleGlazingSystem",
                object_name,
                "simple-glazing field is not a finite number",
                field=field,
            ))
            continue
        if (parameter == "WIN-U" and before <= 0) or (
            parameter == "WIN-SHGC" and not 0 < before <= 1
        ):
            constraint = "U-Factor must be greater than 0" if parameter == "WIN-U" else "SHGC must be greater than 0 and no more than 1"
            skipped.append(_skip(
                "WindowMaterial:SimpleGlazingSystem",
                object_name,
                f"source value is invalid: {constraint}",
                field=field,
            ))
            continue
        after = before * factor
        if not math.isfinite(after) or (parameter == "WIN-U" and after <= 0) or (
            parameter == "WIN-SHGC" and not 0 < after <= 1
        ):
            constraint = "U-Factor must be greater than 0" if parameter == "WIN-U" else "SHGC must be greater than 0 and no more than 1"
            skipped.append(_skip(
                "WindowMaterial:SimpleGlazingSystem",
                object_name,
                f"requested percentage is invalid: {constraint}",
                field=field,
            ))
            continue
        planned.append(_planned(material, "WindowMaterial:SimpleGlazingSystem", object_name, field, before, after))

    return planned, skipped


def _unsupported_epd_objects(idf: Any) -> list[dict[str, Any]]:
    """Flag IT equipment rather than silently excluding it from EPD coverage."""
    return [
        _skip(
            "ElectricEquipment:ITE:AirCooled",
            _object_name(obj),
            "ElectricEquipment:ITE:AirCooled is not supported by the EPD MVP",
        )
        for obj in _objects(idf, "ElectricEquipment:ITE:AirCooled")
    ]


def _unsupported_infiltration_objects(idf: Any) -> list[dict[str, Any]]:
    """Flag alternate infiltration representations outside DesignFlowRate."""
    skipped: list[dict[str, Any]] = []
    for object_type in (
        "ZoneInfiltration:EffectiveLeakageArea",
        "ZoneInfiltration:FlowCoefficient",
    ):
        for obj in _objects(idf, object_type):
            skipped.append(_skip(
                object_type,
                _object_name(obj),
                "only ZoneInfiltration:DesignFlowRate is supported by the INF MVP",
            ))
    for object_type, objects in _object_collections(idf):
        if not str(object_type).casefold().startswith("airflownetwork:multizone"):
            continue
        for obj in objects:
            skipped.append(_skip(
                str(object_type),
                _object_name(obj),
                "AirflowNetwork multi-zone infiltration is not supported by the INF MVP",
            ))
    return skipped


def _objects(idf: Any, object_type: str) -> list[Any]:
    """Read an IDF object collection without assuming the dictionary's casing."""
    for key, objects in _object_collections(idf):
        if str(key).casefold() == object_type.casefold():
            return list(objects)
    return []


def _object_collections(idf: Any) -> list[tuple[Any, Any]]:
    collections = getattr(idf, "idfobjects", {})
    return list(collections.items())


def _present_field(obj: Any, field_names: str | tuple[str, ...]) -> str | None:
    return next((field for field in _field_names(field_names) if hasattr(obj, field)), None)


def _field_names(field_names: str | tuple[str, ...]) -> tuple[str, ...]:
    return (field_names,) if isinstance(field_names, str) else field_names


def _construction_by_name(idf: Any) -> dict[str, Any]:
    constructions: dict[str, Any] = {}
    for object_type in (
        "Construction",
        "Construction:WindowEquivalentLayer",
        "Construction:ComplexFenestrationState",
    ):
        for construction in _objects(idf, object_type):
            name = _normalized_name(_object_name(construction))
            if name:
                constructions[name] = construction
    return constructions


def _construction_layers(construction: Any) -> list[str]:
    """Return populated construction layers from the conventional IDF fields."""
    layers: list[str] = []
    for field in ("Outside_Layer", *(f"Layer_{index}" for index in range(2, 21))):
        value = str(getattr(construction, field, "")).strip()
        if value:
            layers.append(value)
    return layers


def _material_has_nonwindow_use(
    material_key: str,
    construction_by_name: dict[str, Any],
    surface_types_by_construction: dict[str, set[str]],
) -> bool:
    for construction_key, construction in construction_by_name.items():
        layers = _construction_layers(construction)
        if material_key not in {_normalized_name(layer) for layer in layers}:
            continue
        surface_types = surface_types_by_construction.get(construction_key, set())
        if any(surface_type != "window" for surface_type in surface_types):
            return True
    return False


def _planned(
    obj: Any,
    object_type: str,
    object_name: str,
    field: str,
    before: float,
    after: float,
    calculation_method: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "object": obj,
        "object_type": object_type,
        "object_name": object_name,
        "field": field,
        "before": before,
        "after": after,
    }
    if calculation_method is not None:
        item["calculation_method"] = calculation_method
    return item


def _skip(
    object_type: str,
    object_name: str,
    reason: str,
    *,
    field: str | None = None,
    calculation_method: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "object_type": object_type,
        "object_name": object_name,
        "reason": reason,
    }
    if field is not None:
        item["field"] = field
    if calculation_method is not None:
        item["calculation_method"] = calculation_method
    return item


def _normalize_parameter(parameter: Any) -> str:
    return parameter.strip().upper() if isinstance(parameter, str) else ""


def _normalize_method(value: str) -> str:
    return "".join(value.strip().casefold().split())


def _normalized_name(value: str) -> str:
    return value.strip().casefold()


def _object_name(obj: Any) -> str:
    value = str(getattr(obj, "Name", "")).strip()
    return value or "Unnamed"


def _as_finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
