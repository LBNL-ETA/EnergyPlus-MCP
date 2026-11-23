from typing import Any, Dict, Optional, Literal
import json
from datetime import datetime

from energyplus_mcp_server.domains.hvac import hvac_discover, hvac_topology, hvac_visualize


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    @mcp.tool()
    async def hvac_loop_inspect(
        idf_path: str,
        action: Literal["discover", "topology", "visualize"],
        types: Literal["plant", "air", "condenser", "all"] = "all",
        loop_name: Optional[str] = None,
        detail: Literal["summary", "detailed"] = "summary",
        topology_format: Literal["json", "graph"] = "json",
        image_format: Literal["png", "jpg", "pdf", "svg"] = "png",
        show_legend: bool = True,
        output_path: Optional[str] = None,
    ) -> str:
        timestamp = datetime.utcnow().isoformat()
        if action == "discover":
            loops_json = hvac_discover(ep_manager, idf_path)
            try:
                loops_data = json.loads(loops_json)
            except Exception:
                loops_data = {"raw": loops_json}
            if isinstance(loops_data, dict) and types != "all":
                key_map = {"plant": "PlantLoops", "air": "AirLoops", "condenser": "CondenserLoops"}
                sel_key = key_map.get(types)
                data: Dict[str, Any] = {}
                if sel_key and sel_key in loops_data:
                    data[sel_key] = loops_data.get(sel_key)
                else:
                    data = loops_data
            else:
                data = loops_data
            return json.dumps({"meta": {"action": action, "idf_path": idf_path, "types": types, "detail": detail, "timestamp": timestamp}, "data": data}, indent=2)
        if action == "topology":
            if not loop_name:
                return json.dumps({"error": "loop_name is required for action='topology'"}, indent=2)
            topo_json = hvac_topology(ep_manager, idf_path, loop_name)
            try:
                topo = json.loads(topo_json)
            except Exception:
                topo = {"raw": topo_json}
            return json.dumps({"meta": {"action": action, "idf_path": idf_path, "loop_name": loop_name, "detail": detail, "timestamp": timestamp}, "data": topo}, indent=2)
        if action == "visualize":
            viz_json = hvac_visualize(ep_manager, idf_path, loop_name, output_path, image_format, show_legend)
            try:
                viz = json.loads(viz_json)
            except Exception:
                viz = {"raw": viz_json}
            return json.dumps({"meta": {"action": action, "idf_path": idf_path, "loop_name": loop_name, "image_format": image_format, "timestamp": timestamp}, "data": viz}, indent=2)
        return json.dumps({"error": f"Unknown action '{action}'"}, indent=2)

