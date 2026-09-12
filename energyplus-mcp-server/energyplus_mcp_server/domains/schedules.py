"""Generic schedule-domain manager backed by the native IDF schedule graph."""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence

from ..utils.schedule_graph import ScheduleEditor


SCHEDULE_SCOPES = {
    "lighting_schedule": "lighting",
    "equipment_schedule": "electric_equipment",
    "hvac_availability_schedule": "hvac_availability",
}


def _editor(ep_manager: Any) -> ScheduleEditor:
    """Bind only EnergyPlusManager's existing path resolver when available."""
    resolver = getattr(ep_manager, "_resolve_idf_path", None)
    return ScheduleEditor(path_resolver=resolver)


def _parameter_capabilities(ep_manager: Any, idf_path: Optional[str]) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "success": True,
        "tool": "schedule_manager",
        "manager": "schedule_manager",
        "action": "parameter_capabilities",
        "model_format": "idf",
        "parameters": {},
    }
    if not idf_path:
        for operation, scope in SCHEDULE_SCOPES.items():
            result["parameters"][operation] = {
                "operation": operation,
                "scope": scope,
                "coverage": "unverified",
                "supported": False,
                "tool": "schedule_manager",
                "manager": "schedule_manager",
                "action": "adjust_percentage",
                "capability_action": "parameter_capabilities",
                "inspect_action": "inspect",
                "units": "percent",
                "value_semantics": "signed percentage scaling of bounded schedule values",
                "required_args": ["idf_path", "scope", "value", "output_path"],
                "returns": ["output_file", "before", "after", "changed", "skipped", "ambiguous"],
                "operations": ["adjust_percentage"],
                "minimum_value": -100.0,
                "minimum_inclusive": True,
                "applicable_field_count": 0,
            }
        return result

    service = _editor(ep_manager)
    for operation, scope in SCHEDULE_SCOPES.items():
        inspection = service.inspect(idf_path, scope)
        consumers = inspection.get("consumers", [])
        plan = service.edit(
            input_file=idf_path,
            consumer_references=consumers,
            operation="scale",
            value=1.0,
            bounds={"minimum": 0.0, "maximum": 1.0},
            clone_on_write=True,
            expected_model_sha256=inspection.get("input_sha256"),
            mode="dry_run",
        ) if consumers else {
            **inspection,
            "coverage": "none",
            "supported": False,
            "applicable_targets": [],
            "shared_objects": [],
        }
        result["parameters"][operation] = {
            "operation": operation,
            "scope": scope,
            "coverage": plan.get("coverage", "none"),
            "supported": plan.get("coverage") == "complete",
            "tool": "schedule_manager",
            "manager": "schedule_manager",
            "action": "adjust_percentage",
            "capability_action": "parameter_capabilities",
            "inspect_action": "inspect",
            "units": "percent",
            "value_semantics": "signed percentage scaling of bounded schedule values",
            "required_args": ["idf_path", "scope", "value", "output_path"],
            "returns": ["output_file", "before", "after", "changed", "skipped", "ambiguous"],
            "operations": ["adjust_percentage"],
            "minimum_value": -100.0,
            "minimum_inclusive": True,
            "applicable_field_count": len(plan.get("before", [])),
            "input_file": inspection.get("input_file"),
            "input_sha256": inspection.get("input_sha256"),
            "applicable_targets": plan.get("applicable_targets", []),
            "consumer_references": consumers,
            "shared_object_relationships": plan.get("shared_objects", []),
            "skipped": plan.get("skipped", []),
            "ambiguous": plan.get("ambiguous", []),
            "warnings": plan.get("warnings", []),
            "limitations": plan.get("limitations", []),
        }
    return result


def inspect_schedules_data(
    ep_manager: Any, idf_path: str, scope: str = "all", *,
    schedule_editor: Optional[ScheduleEditor] = None,
) -> Dict[str, Any]:
    """Return graph-aware schedule profiles and explicit direct consumers.

    ``scope`` may be ``all``, ``lighting``, ``electric_equipment``,
    ``hvac_availability``, ``thermostat_setpoint``, or ``occupancy``.
    """
    return (schedule_editor or _editor(ep_manager)).inspect(idf_path, scope)


def edit_schedules(
    ep_manager: Any,
    idf_path: str,
    consumer_references: Sequence[Mapping[str, Any]],
    operation: str,
    value: Any,
    *,
    output_path: Optional[str] = None,
    target_ids: Optional[Sequence[str]] = None,
    bounds: Optional[Mapping[str, Any]] = None,
    clone_on_write: bool = True,
    expected_model_sha256: Optional[str] = None,
    mode: str = "dry_run",
    schedule_editor: Optional[ScheduleEditor] = None,
) -> Dict[str, Any]:
    """Plan or apply a graph-aware schedule edit.

    Consumers must be explicit inspection-returned references.  In apply mode,
    the editor verifies ``expected_model_sha256`` when supplied and writes only
    a distinct ``output_path``; it never overwrites the source model.
    """
    return (schedule_editor or _editor(ep_manager)).edit(
        input_file=idf_path,
        consumer_references=consumer_references,
        operation=operation,
        value=value,
        output_file=output_path,
        target_ids=target_ids,
        bounds=bounds,
        clone_on_write=clone_on_write,
        expected_model_sha256=expected_model_sha256,
        mode=mode,
    )


def register(
    mcp: Any, ep_manager: Any, config: Any,
    schedule_editor: Optional[ScheduleEditor] = None,
) -> None:
    """Register graph-aware inspection and copy-based schedule operations."""
    service = schedule_editor or _editor(ep_manager)

    @mcp.tool()
    async def schedule_manager(
        action: Literal["capabilities", "parameter_capabilities", "inspect", "edit", "adjust_percentage"],
        idf_path: Optional[str] = None,
        scope: Literal[
            "all", "lighting", "electric_equipment", "hvac_availability",
            "thermostat_setpoint", "occupancy", "schedule_consumer",
        ] = "all",
        consumer_references: Optional[List[Dict[str, Any]]] = None,
        operation: Optional[Literal["scale", "delta", "shift_or_extend"]] = None,
        value: Any = None,
        output_path: Optional[str] = None,
        target_ids: Optional[List[str]] = None,
        bounds: Optional[Dict[str, Any]] = None,
        clone_on_write: bool = True,
        expected_model_sha256: Optional[str] = None,
        mode: Literal["dry_run", "apply"] = "dry_run",
        percentage_change: Optional[float] = None,
    ) -> str:
        """Inspect IDF schedules or plan/apply a selected-consumer schedule edit."""
        if action == "capabilities":
            return json.dumps({
                "tool": "schedule_manager",
                "domain": "schedules",
                "registered": True,
                "actions": [
                    {"name": "inspect", "required": ["idf_path"], "optional": ["scope"]},
                    {
                        "name": "edit",
                        "required": ["idf_path", "consumer_references", "operation", "value"],
                        "optional": ["output_path", "target_ids", "bounds", "clone_on_write", "expected_model_sha256", "mode"],
                    },
                    {"name": "parameter_capabilities", "required": [], "optional": ["idf_path"]},
                    {"name": "adjust_percentage", "required": ["idf_path", "scope", "percentage_change"], "optional": ["output_path", "expected_model_sha256", "mode"]},
                ],
                "operations": {
                    "scale": {"value_semantics": "finite multiplier"},
                    "delta": {"value_semantics": "finite additive schedule-value increment"},
                    "shift_or_extend": {
                        "value_semantics": "{shift_hours, extend_hours, occupied_threshold?, extension_side?}",
                        "supported_families": ["Schedule:Day:Hourly", "Schedule:Day:List at whole-hour resolution"],
                    },
                },
                "supported_families": [
                    "Schedule:Constant", "Schedule:Compact", "Schedule:Day:Hourly",
                    "Schedule:Day:Interval", "Schedule:Day:List", "Schedule:Week:Daily",
                    "Schedule:Week:Compact", "Schedule:Year",
                ],
                "unsupported": ["Schedule:File"],
            }, indent=2)
        if action == "parameter_capabilities":
            return json.dumps(_parameter_capabilities(ep_manager, idf_path), indent=2)
        if not idf_path:
            return json.dumps({"success": False, "error": "Missing required parameter: idf_path"})
        try:
            if action == "inspect":
                return json.dumps(service.inspect(idf_path, scope), indent=2)
            if action == "adjust_percentage":
                if scope not in SCHEDULE_SCOPES.values():
                    return json.dumps({
                        "success": False,
                        "error": "adjust_percentage scope must be lighting, electric_equipment, or hvac_availability",
                    })
                requested_percent = percentage_change if percentage_change is not None else value
                try:
                    percent = float(requested_percent)
                except (TypeError, ValueError):
                    return json.dumps({"success": False, "error": "percentage_change must be numeric"})
                if not math.isfinite(percent) or percent < -100.0:
                    return json.dumps({"success": False, "error": "percentage_change must be finite and at least -100"})
                inspection = service.inspect(idf_path, scope)
                consumers = inspection.get("consumers", [])
                if not consumers:
                    return json.dumps({
                        **inspection,
                        "success": False,
                        "operation": next((key for key, value in SCHEDULE_SCOPES.items() if value == scope), "schedule_adjustment"),
                        "coverage": "none",
                        "supported": False,
                    }, indent=2)
                response = service.edit(
                    input_file=idf_path,
                    consumer_references=consumers,
                    operation="scale",
                    value=1.0 + percent / 100.0,
                    output_file=output_path,
                    bounds={"minimum": 0.0, "maximum": 1.0},
                    clone_on_write=True,
                    expected_model_sha256=expected_model_sha256,
                    mode=mode,
                )
                response["operation"] = next(
                    key for key, value in SCHEDULE_SCOPES.items() if value == scope
                )
                response["requested_value"] = percent
                response["effective_value"] = percent
                response["units"] = "percent"
                response["value_semantics"] = "signed percentage scaling of bounded schedule values"
                return json.dumps(response, indent=2)
            if action != "edit":
                return json.dumps({"success": False, "error": f"Unsupported action: {action}"})
            if not consumer_references or operation is None:
                return json.dumps({
                    "success": False,
                    "error": "edit requires consumer_references, operation, and value",
                })
            return json.dumps(service.edit(
                input_file=idf_path,
                consumer_references=consumer_references,
                operation=operation,
                value=value,
                output_file=output_path,
                target_ids=target_ids,
                bounds=bounds,
                clone_on_write=clone_on_write,
                expected_model_sha256=expected_model_sha256,
                mode=mode,
            ), indent=2)
        except Exception as error:
            return json.dumps({
                "success": False,
                "domain": "schedules",
                "operation": action,
                "model_format": "idf",
                "error": str(error),
            })
