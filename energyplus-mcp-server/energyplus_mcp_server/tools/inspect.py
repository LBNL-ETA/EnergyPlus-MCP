from typing import Any, Dict, List, Optional
import json
import logging

from energyplus_mcp_server.domains.envelope import inspect_envelope_data
from energyplus_mcp_server.domains.internal_loads import inspect_internal_loads_data

logger = logging.getLogger(__name__)


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    @mcp.tool()
    async def inspect_model(
        idf_path: str,
        focus: Optional[List[str]] = None,
        detail: str = "summary",
        include_values: bool = False,
    ) -> str:
        canonical = {
            "summary": "summary",
            "zones": "zones",
            "surfaces": "surfaces",
            "materials": "materials",
            "schedules": "schedules",
            "people": "people",
            "lights": "lights",
            "electric_equipment": "electric_equipment",
            "all": "all",
        }
        all_focus = ["summary", "zones", "surfaces", "materials", "schedules", "people", "lights", "electric_equipment"]
        if not focus or any(canonical.get(x, x) == "all" for x in focus):
            normalized: List[str] = list(all_focus)
        else:
            normalized = []
            for item in focus:
                key = canonical.get(item, item)
                if key in all_focus:
                    normalized.append(key)

        results: Dict[str, Any] = {}
        errors: Dict[str, str] = {}
        try:
            if "summary" in normalized:
                results["summary"] = ep_manager.get_model_basics(idf_path)
            if "zones" in normalized:
                results["zones"] = ep_manager.list_zones(idf_path)
            if "schedules" in normalized:
                results["schedules"] = ep_manager.inspect_schedules(idf_path, include_values)
            env_keys = [k for k in ("surfaces", "materials") if k in normalized]
            if env_keys:
                results.update(inspect_envelope_data(ep_manager, idf_path, env_keys))
            il_keys = [k for k in ("people", "lights", "electric_equipment") if k in normalized]
            if il_keys:
                results.update(inspect_internal_loads_data(ep_manager, idf_path, il_keys))
        except FileNotFoundError as e:
            for k in normalized:
                errors.setdefault(k, f"File not found: {str(e)}")
        except Exception as e:
            errors["aggregation"] = str(e)

        return json.dumps({
            "meta": {"idf_path": idf_path, "detail": detail, "focus": normalized},
            "results": results,
            "errors": errors,
        }, indent=2)

