"""Lean native-IDF operations used by the calibration service."""

import json
from typing import Any, Dict, List, Literal, Optional


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    @mcp.tool()
    async def calibration_manager(
        action: Literal["capabilities", "inspect", "perturb", "set"],
        idf_path: Optional[str] = None,
        parameter: str = "LPD",
        value: Optional[float] = None,
        output_path: Optional[str] = None,
        target_ids: Optional[List[str]] = None,
        assignments: Optional[Dict[str, float]] = None,
        expected_model_sha256: Optional[str] = None,
    ) -> str:
        """Report native-IDF calibration support or perturb the supplied model.

        perturb uses signed percentages. inspect reports canonical absolute
        quantities and target IDs. set uses an absolute value (optionally
        target_ids), or assignments mapping IDs to values, never both.
        expected_model_sha256 binds set to an inspection. Partial coverage
        is not enabled. Physical limits apply; no hidden clipping occurs.
        """
        if action == "capabilities":
            payload = ep_manager.calibration_capabilities(idf_path)
            payload["action"] = "capabilities"
            return json.dumps(payload, indent=2)

        if action not in ("inspect", "perturb", "set"):
            return json.dumps({"success": False, "error": f"Unsupported action: {action}"}, indent=2)
        if not idf_path or (action != "inspect" and (not output_path or (value is None and assignments is None))):
            return json.dumps({
                "success": False,
                "error": "Missing required parameters: idf_path, parameter, value, output_path",
            }, indent=2)
        try:
            if action == "inspect":
                return json.dumps(ep_manager.inspect_calibration_parameter(idf_path, parameter), indent=2)
            if action == "set":
                return json.dumps(ep_manager.set_calibration_values(
                    idf_path, parameter, value, output_path, target_ids,
                    assignments, expected_model_sha256,
                ), indent=2)
            if target_ids is not None or assignments is not None or expected_model_sha256 is not None:
                raise ValueError("target_ids, assignments, and expected_model_sha256 apply only to set")
            return json.dumps(
                ep_manager.adjust_calibration_percentage(idf_path, parameter, value, output_path),
                indent=2,
            )
        except Exception as error:
            return json.dumps({"success": False, "parameter": parameter, "error": str(error)}, indent=2)
