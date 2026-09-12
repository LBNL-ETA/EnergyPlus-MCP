"""Generic service-water domain facade."""

from __future__ import annotations

import json
import math
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Literal, Mapping, Optional

from eppy.modeleditor import IDF

from ..utils import service_water


def capabilities(idf: Any | None = None) -> dict[str, Any]:
    """Return generic service-water capabilities for a loaded IDF."""
    return service_water.capabilities(idf)


def inspect(idf: Any) -> dict[str, Any]:
    """Return semantic targets, connection/schedule relationships, and gates."""
    return service_water.inspect(idf)


def set_parameters(
    idf: Any,
    *,
    input_path: str,
    output_path: str,
    assignments: Mapping[str, Any],
    mode: str = "dry_run",
    expected_model_sha256: str | None = None,
) -> dict[str, Any]:
    """Plan or apply hash-bound service-water target assignments."""
    return service_water.execute(
        idf,
        input_path=input_path,
        output_path=output_path,
        assignments=assignments,
        mode=mode,
        expected_model_sha256=expected_model_sha256,
    )


def operation_contract() -> dict[str, Any]:
    """Describe the ``service_water_manager`` action surface."""
    return {
        "tool": "service_water_manager",
        "domain": "service_water",
        "actions": [
            {
                "name": "capabilities",
                "required": [],
                "optional": ["idf_path"],
                "delegates_to": "service_water.capabilities",
            },
            {
                "name": "parameter_capabilities",
                "required": [],
                "optional": ["idf_path"],
            },
            {
                "name": "inspect",
                "required": ["idf_path"],
                "delegates_to": "service_water.inspect",
            },
            {
                "name": "set_parameters",
                "required": ["idf_path", "assignments", "output_path"],
                "optional": ["mode", "expected_model_sha256"],
                "delegates_to": "service_water.execute",
            },
            {
                "name": "adjust_efficiency_percentage",
                "required": ["idf_path", "value", "output_path"],
                "optional": ["mode", "expected_model_sha256"],
            },
        ],
        "notes": [
            "Schedules, compressor COP, and controls remain separate semantics and are never changed by set_parameters.",
        ],
    }


def _load(ep_manager: Any, idf_path: str) -> tuple[str, Any, str]:
    resolved = ep_manager._resolve_idf_path(idf_path)
    ep_manager._assert_simulation_version_matches(resolved)
    return resolved, IDF(resolved), sha256(Path(resolved).read_bytes()).hexdigest()


def _capability(ep_manager: Any, idf_path: Optional[str]) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "parameter": "service_water_efficiency",
        "operation": "adjust_efficiency_percentage",
        "tool": "service_water_manager",
        "manager": "service_water_manager",
        "action": "adjust_efficiency_percentage",
        "capability_action": "parameter_capabilities",
        "inspect_action": "inspect",
        "units": "percent",
        "value_semantics": "signed percentage change to WaterHeater thermal-efficiency fields only",
        "required_args": ["idf_path", "value", "output_path"],
        "returns": ["output_file", "before", "after", "changes", "skipped", "ambiguous"],
        "operations": ["adjust_efficiency_percentage"],
        "minimum_value": -100.0,
        "minimum_inclusive": False,
        "applicable_field_count": 0,
    }
    if not idf_path:
        return {**base, "coverage": "unverified", "supported": False}
    resolved, idf, source_hash = _load(ep_manager, idf_path)
    inspection = service_water.inspect(idf)
    efficiency_targets = [
        target for target in inspection["applicable_targets"]
        if target.get("semantic") == "combustion_efficiency"
    ]
    coverage = inspection["coverage"] if efficiency_targets else "none"
    return {
        **base,
        "coverage": coverage,
        "supported": coverage == "complete",
        "input_file": resolved,
        "input_sha256": source_hash,
        "applicable_targets": efficiency_targets,
        "applicable_field_count": len(efficiency_targets),
        "all_service_water_targets": inspection["applicable_targets"],
        "shared_object_relationships": inspection["shared_relationships"],
        "skipped": inspection["skipped"],
        "ambiguous": inspection["ambiguous"],
        "warnings": inspection["warnings"],
        "limitations": inspection["limits"],
    }


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    """Register service-water inspection and copy-based semantic edits."""

    @mcp.tool()
    async def service_water_manager(
        action: Literal[
            "capabilities", "parameter_capabilities", "inspect",
            "set_parameters", "adjust_efficiency_percentage",
        ],
        idf_path: Optional[str] = None,
        output_path: Optional[str] = None,
        assignments: Optional[Dict[str, Any]] = None,
        value: Optional[float] = None,
        mode: Literal["dry_run", "apply"] = "dry_run",
        expected_model_sha256: Optional[str] = None,
    ) -> str:
        try:
            if action == "capabilities":
                return json.dumps(operation_contract(), indent=2)
            if action == "parameter_capabilities":
                return json.dumps({
                    "success": True,
                    "tool": "service_water_manager",
                    "manager": "service_water_manager",
                    "action": "parameter_capabilities",
                    "model_format": "idf",
                    "parameters": {"service_water_efficiency": _capability(ep_manager, idf_path)},
                }, indent=2)
            if not idf_path:
                return json.dumps({"success": False, "error": "Missing required parameter: idf_path"})
            resolved, idf, source_hash = _load(ep_manager, idf_path)
            if action == "inspect":
                payload = service_water.inspect(idf)
                payload.update({
                    "tool": "service_water_manager", "manager": "service_water_manager",
                    "action": action, "input_file": resolved,
                    "input_sha256": source_hash, "mode": "inspect",
                })
                return json.dumps(payload, indent=2)
            if not output_path:
                return json.dumps({"success": False, "error": f"{action} requires output_path"})
            if action == "set_parameters":
                if not assignments:
                    return json.dumps({"success": False, "error": "set_parameters requires assignments"})
                payload = service_water.execute(
                    idf, input_path=resolved, output_path=output_path,
                    assignments=assignments, mode=mode,
                    expected_model_sha256=expected_model_sha256,
                )
            elif action == "adjust_efficiency_percentage":
                try:
                    percent = float(value)  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    return json.dumps({"success": False, "error": "value must be a numeric percentage"})
                if not math.isfinite(percent) or percent <= -100.0:
                    return json.dumps({"success": False, "error": "efficiency percentage must be finite and greater than -100"})
                inspection = service_water.inspect(idf)
                targets = [
                    target for target in inspection["applicable_targets"]
                    if target.get("semantic") == "combustion_efficiency"
                ]
                if inspection["coverage"] != "complete" or not targets:
                    payload = {
                        **inspection,
                        "success": False,
                        "supported": False,
                        "error": "efficiency adjustment requires complete service-water coverage",
                        "changed": False,
                    }
                else:
                    factor = 1.0 + percent / 100.0
                    absolute = {
                        target["target_id"]: float(target["value"]) * factor
                        for target in targets
                    }
                    payload = service_water.execute(
                        idf, input_path=resolved, output_path=output_path,
                        assignments=absolute, mode=mode,
                        expected_model_sha256=expected_model_sha256,
                    )
                    payload.update({
                        "requested_value": percent,
                        "effective_value": percent,
                        "units": "percent",
                        "value_semantics": "signed percentage change to WaterHeater thermal-efficiency fields only",
                    })
            else:
                return json.dumps({"success": False, "error": f"Unsupported action: {action}"})
            payload.update({
                "tool": "service_water_manager", "manager": "service_water_manager",
                "action": action,
            })
            return json.dumps(payload, indent=2)
        except Exception as error:
            return json.dumps({
                "success": False, "tool": "service_water_manager",
                "manager": "service_water_manager", "action": action,
                "domain": "service_water", "model_format": "idf", "error": str(error),
            })
