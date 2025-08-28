from typing import Any, Dict, List, Optional
import json
import logging

from energyplus_mcp_server.domains.envelope import modify_envelope
from energyplus_mcp_server.domains.internal_loads import modify_internal_loads

logger = logging.getLogger(__name__)


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    @mcp.tool()
    async def modify_basic_parameters(
        idf_path: str,
        operations: List[Dict[str, Any]],
        mode: str = "dry_run",
        output_path: Optional[str] = None,
        validation_level: str = "moderate",
        conflict_strategy: str = "error",
        capabilities: bool = False,
        detail: str = "summary",
    ) -> str:
        allowed_ops = {
            "people.update",
            "lights.update",
            "electric_equipment.update",
            "infiltration.scale",
            "envelope.add_window_film",
            "envelope.add_coating",
            "outputs.add_variables",
            "outputs.add_meters",
        }
        if capabilities or (mode.lower() == "dry_run" and not operations):
            return json.dumps({
                "supported_ops": sorted(list(allowed_ops)),
                "notes": ["Use simulation_manager for SimulationControl/RunPeriod."],
            }, indent=2)
        plan = []
        errors: Dict[str, Any] = {}
        results: List[Dict[str, Any]] = []
        for idx, op in enumerate(operations):
            op_name = str(op.get("op", "")).strip()
            if op_name not in allowed_ops:
                errors[str(idx)] = f"Unknown op '{op_name}'"
                continue
            plan.append({"index": idx, "op": op_name})
        if mode.lower() != "apply":
            return json.dumps({"plan": plan, "errors": errors}, indent=2)

        current_path = idf_path
        final_output = None
        for idx, op in enumerate(operations):
            op_name = str(op.get("op", "")).strip()
            params = op.get("params", {}) or {}
            try:
                if op_name in {"people.update", "lights.update", "electric_equipment.update"}:
                    mods = params.get("modifications") or []
                    resp = modify_internal_loads(ep_manager, current_path, op_name, mods, None)
                elif op_name in {"infiltration.scale", "envelope.add_window_film", "envelope.add_coating"}:
                    resp = modify_envelope(ep_manager, current_path, op_name, params, None)
                elif op_name == "outputs.add_variables":
                    resp = ep_manager.add_output_variables(current_path, params.get("variables", []), validation_level, bool(params.get("allow_duplicates", False)), None)
                elif op_name == "outputs.add_meters":
                    resp = ep_manager.add_output_meters(current_path, params.get("meters", []), validation_level, bool(params.get("allow_duplicates", False)), None)
                else:
                    resp = json.dumps({"unsupported": op_name})
                output_file = None
                try:
                    data = json.loads(resp)
                    output_file = data.get("output_file") or data.get("output_path")
                except Exception:
                    pass
                if output_file:
                    current_path = output_file
                    final_output = output_file
                results.append({"index": idx, "op": op_name, "output_file": output_file})
            except Exception as e:
                results.append({"index": idx, "op": op_name, "status": "error", "error": str(e)})

        if output_path and final_output:
            try:
                ep_manager.copy_file(final_output, output_path, True, None)
            except Exception as e:
                errors["final_copy"] = str(e)

        return json.dumps({
            "results": results,
            "final_file": final_output or idf_path,
            "errors": errors,
        }, indent=2)

