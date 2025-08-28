from typing import Any, Dict, Optional, Literal
import json
import logging

logger = logging.getLogger(__name__)

# --- Reusable domain helpers (importable by orchestrators) ---
def inspect_envelope_data(ep_manager: Any, idf_path: str, focus: str | list[str] = "both") -> Dict[str, Any]:
    """Return envelope inspection data keyed by section names.

    focus: "surfaces" | "materials" | "both" | list of these
    Values are whatever `ep_manager` returns (usually JSON strings).
    """
    if isinstance(focus, str):
        focus_list = [focus]
    else:
        focus_list = focus
    out: Dict[str, Any] = {}
    if "surfaces" in focus_list or focus == "both":
        out["surfaces"] = ep_manager.get_surfaces(idf_path)
    if "materials" in focus_list or focus == "both":
        out["materials"] = ep_manager.get_materials(idf_path)
    return out

def modify_envelope(ep_manager: Any, idf_path: str, op: str, params: Optional[Dict[str, Any]] = None, output_path: Optional[str] = None) -> str:
    p = params or {}
    if op == "infiltration.scale":
        return ep_manager.change_infiltration_by_mult(idf_path, float(p.get("mult", 1.0)), output_path)
    if op == "envelope.add_window_film":
        return ep_manager.add_window_film_outside(
            idf_path,
            float(p.get("u_value", 4.94)),
            float(p.get("shgc", 0.45)),
            float(p.get("visible_transmittance", 0.66)),
            output_path,
        )
    if op == "envelope.add_coating":
        return ep_manager.add_coating_outside(
            idf_path,
            p.get("location", "wall"),
            float(p.get("solar_abs", 0.4)),
            float(p.get("thermal_abs", 0.9)),
            output_path,
        )
    raise ValueError(f"Unsupported envelope op: {op}")


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    logger.info("domains.envelope.register starting")
    @mcp.tool()
    async def envelope_manager(
        action: Literal["inspect", "modify", "capabilities"],
        idf_path: Optional[str] = None,
        # Inspect
        focus: Literal["surfaces", "materials", "both"] = "both",
        # Modify
        op: Optional[Literal[
            "infiltration.scale",
            "envelope.add_window_film",
            "envelope.add_coating",
        ]] = None,
        params: Optional[Dict[str, Any]] = None,
        output_path: Optional[str] = None,
        mode: Literal["apply", "dry_run"] = "apply",
    ) -> str:
        """
        Envelope domain manager.

        - inspect: surfaces/materials
        - modify: infiltration scale, add window film, add coating
        - capabilities: describe supported actions
        """
        try:
            if action == "capabilities":
                return json.dumps({
                    "tool": "envelope_manager",
                    "actions": [
                        {"name": "inspect", "required": ["idf_path"], "optional": ["focus"]},
                        {"name": "modify", "required": ["idf_path", "op"], "optional": ["params", "output_path", "mode"]},
                    ],
                    "ops": [
                        {"op": "infiltration.scale", "params": {"mult": 0.9}},
                        {"op": "envelope.add_window_film", "params": {"u_value": 4.94, "shgc": 0.45, "visible_transmittance": 0.66}},
                        {"op": "envelope.add_coating", "params": {"location": "wall|roof", "solar_abs": 0.4, "thermal_abs": 0.9}},
                    ],
                }, indent=2)

            if not idf_path:
                return "Missing required parameter: idf_path"

            if action == "inspect":
                payload: Dict[str, Any] = {"focus": focus}
                if focus in ("surfaces", "both"):
                    payload["surfaces"] = ep_manager.get_surfaces(idf_path)
                if focus in ("materials", "both"):
                    payload["materials"] = ep_manager.get_materials(idf_path)
                return json.dumps(payload, indent=2)

            if action == "modify":
                if mode == "dry_run":
                    return json.dumps({
                        "mode": mode,
                        "plan": {"op": op, "params": params or {}},
                    }, indent=2)
                if op == "infiltration.scale":
                    mult = float((params or {}).get("mult", 1.0))
                    return ep_manager.change_infiltration_by_mult(idf_path, mult, output_path)
                if op == "envelope.add_window_film":
                    p = params or {}
                    return ep_manager.add_window_film_outside(
                        idf_path,
                        float(p.get("u_value", 4.94)),
                        float(p.get("shgc", 0.45)),
                        float(p.get("visible_transmittance", 0.66)),
                        output_path,
                    )
                if op == "envelope.add_coating":
                    p = params or {}
                    return ep_manager.add_coating_outside(
                        idf_path,
                        p.get("location", "wall"),
                        float(p.get("solar_abs", 0.4)),
                        float(p.get("thermal_abs", 0.9)),
                        output_path,
                    )
                return f"Unsupported op: {op}"

            return f"Unsupported action: {action}"
        except FileNotFoundError as e:
            logger.warning(f"Envelope file not found: {str(e)}")
            return f"File not found: {str(e)}"
        except Exception as e:
            logger.error(f"envelope_manager error: {str(e)}")
            return f"Error in envelope_manager: {str(e)}"
    logger.info("domains.envelope.register complete: envelope_manager available")
