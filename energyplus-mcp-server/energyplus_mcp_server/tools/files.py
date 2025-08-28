from typing import Any, Dict, List, Optional
import json
from pathlib import Path
from datetime import datetime


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    @mcp.tool()
    async def file_utils(
        action: str,
        include_example_files: bool = False,
        include_weather_data: bool = False,
        extensions: Optional[List[str]] = None,
        limit: int = 100,
        source_path: Optional[str] = None,
        target_path: Optional[str] = None,
        file_types: Optional[List[str]] = None,
        overwrite: bool = False,
        mode: str = "apply",
    ) -> str:
        if action == "list":
            from energyplus_mcp_server.utils.path_utils import list_files
            files = list_files(config, include_example_files, include_weather_data, extensions or [], limit)
            return json.dumps({"files": files}, indent=2)
        if action == "copy":
            if not source_path or not target_path:
                return "Missing required parameters: source_path, target_path"
            if mode != "apply":
                return json.dumps({"mode": mode, "plan": {"source": source_path, "target": target_path}}, indent=2)
            result = ep_manager.copy_file(source_path, target_path, overwrite, file_types)
            return f"File copy operation completed:\n{result}"
        return f"Unsupported action: {action}"

