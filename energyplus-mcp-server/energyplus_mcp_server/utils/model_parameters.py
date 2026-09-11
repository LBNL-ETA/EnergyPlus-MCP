"""Small, whole-model semantic-parameter plans; no file or simulation ownership."""

import math

from . import parameter_hvac, parameter_loads


PARAMETERS = ("LPD", "EPD", "OCD", "INF", "WIN-U", "WIN-SHGC", "COP", "HE", "FAN")


def check_numeric_range(obj, field, value):
    """Check IDD bounds, including eppy's unconverted one-item bound lists."""
    if not math.isfinite(value):
        raise ValueError(f"Non-finite candidate value for {field}")
    bounds = obj.getrange(field)
    comparisons = {
        "minimum": lambda limit: value >= limit,
        "minimum>": lambda limit: value > limit,
        "maximum": lambda limit: value <= limit,
        "maximum<": lambda limit: value < limit,
    }
    for key, compare in comparisons.items():
        bound = bounds.get(key)
        if bound is None:
            continue
        if isinstance(bound, (list, tuple)):
            bound = bound[0]
        if not compare(float(bound)):
            raise ValueError(f"{field} value {value} violates IDD {key} {bound}")


def percentage_value(value):
    if isinstance(value, bool):
        raise ValueError("Percentage change must be numeric, not boolean")
    try:
        value = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Percentage change must be numeric") from error
    if not math.isfinite(value) or value < -100:
        raise ValueError("Percentage change must be finite and at least -100")
    return value


def plan(idf, parameter, percentage):
    """Return proposed field edits and unsupported relevant objects without mutation."""
    if parameter in parameter_loads.PARAMETERS:
        return parameter_loads.plan(idf, parameter, percentage)
    if parameter in parameter_hvac.PARAMETERS:
        return parameter_hvac.plan(idf, parameter, percentage)
    if parameter != "LPD":
        raise ValueError(f"Unsupported semantic parameter: {parameter}")
    fields = {
        "lightinglevel": "Lighting_Level",
        "watts/area": "Watts_per_Floor_Area",
        "watts/person": "Watts_per_Person",
    }
    planned, skipped = [], []
    for obj in idf.idfobjects.get("Lights", []):
        method = str(getattr(obj, "Design_Level_Calculation_Method", ""))
        field = fields.get(method.strip().casefold())
        if field == "Watts_per_Floor_Area" and not hasattr(obj, field):
            field = "Watts_per_Zone_Floor_Area"  # pre-Space EnergyPlus schemas
        info = {"object_type": "Lights", "object_name": str(obj.Name)}
        try:
            before = float(getattr(obj, field)) if field else None
            if before is None or not math.isfinite(before) or before < 0:
                raise ValueError()
        except (TypeError, ValueError, AttributeError):
            skipped.append({**info, "reason": "unsupported method or invalid active lighting power"})
            continue
        planned.append({**info, "object": obj, "field": field,
                        "before": before, "after": before * (1 + percentage / 100),
                        "calculation_method": method})
    return planned, skipped


def capabilities(idf=None):
    result = {}
    for parameter in PARAMETERS:
        planned, skipped = [], []
        if idf is not None:
            try:
                planned, skipped = plan(idf, parameter, 0)
            except ValueError as error:
                skipped = [{"reason": str(error)}]
        coverage = ("unverified" if idf is None else
                    "partial" if planned and skipped else
                    "complete" if planned else "none")
        result[parameter] = {
            "implemented": True,
            "supported": coverage == "complete",
            "coverage": coverage,
            "applicable_field_count": len(planned),
            "skipped": skipped,
            "tool": "domain_manager",
            "action": "adjust_percentage",
            "required_args": ["idf_path", "parameter", "value", "output_path"],
            "returns": ["output_file", "before", "after", "changes"],
            "value_semantics": "signed percentage change relative to idf_path",
            "minimum_value": -100,
            "operations": ["adjust_percentage"],
            "absolute_set_supported": False,
            "note": "Physical field limits also apply; partial object coverage is not enabled.",
        }
        absolute = inspect_absolute(idf, parameter) if idf is not None else {
            "coverage": "unverified", "targets": [], "skipped": [],
        }
        absolute_supported = absolute["coverage"] == "complete"
        result[parameter]["absolute_set_supported"] = absolute_supported
        if absolute_supported:
            result[parameter]["operations"].append("set_parameter")
        result[parameter]["absolute_set"] = {
            "supported": absolute_supported, "coverage": absolute["coverage"],
            "action": "set_parameter", "tool": "domain_manager",
            "units": sorted({target["units"] for target in absolute["targets"]}),
            "target_count": len(absolute["targets"]), "skipped": absolute["skipped"],
            "required_args": ["idf_path", "parameter", "value", "output_path"],
            "optional_args": ["target_ids", "assignments", "expected_model_sha256"],
            "note": "assignments maps target_id to absolute value and replaces value/target_ids",
        }
    return result


def _setter(parameter):
    from . import parameter_hvac_setters, parameter_load_setters
    if parameter in parameter_hvac_setters.PARAMETERS:
        return parameter_hvac_setters
    if parameter in parameter_load_setters.PARAMETERS:
        return parameter_load_setters
    raise ValueError(f"Unsupported absolute semantic parameter: {parameter}")


def inspect_absolute(idf, parameter):
    targets, skipped = _setter(parameter).inspect(idf, parameter)
    return {
        "coverage": "partial" if targets and skipped else "complete" if targets else "none",
        "targets": targets, "skipped": skipped,
    }


def plan_absolute(idf, parameter, value=None, target_ids=None, assignments=None):
    setter = _setter(parameter)
    if assignments is None:
        return setter.plan_set(idf, parameter, value, target_ids)
    if value is not None or target_ids is not None or not assignments:
        raise ValueError("Use nonempty assignments OR value/target_ids, not both")
    by_value = {}
    for target_id, target_value in assignments.items():
        if isinstance(target_value, bool) or not isinstance(target_value, (int, float)) or not math.isfinite(target_value):
            raise ValueError("Every assignment must have a finite numeric value")
        by_value.setdefault(target_value, []).append(target_id)
    planned, skipped, fields = [], [], {}
    for target_value, ids in by_value.items():
        group, rejected = setter.plan_set(idf, parameter, target_value, ids)
        skipped.extend(rejected)
        for change in group:
            key = (id(change["object"]), change["field"])
            if key in fields:
                if fields[key] != change["after"]:
                    raise ValueError("Assignments conflict on a shared model field; no candidate saved")
                continue
            fields[key] = change["after"]
            planned.append(change)
    return planned, skipped
