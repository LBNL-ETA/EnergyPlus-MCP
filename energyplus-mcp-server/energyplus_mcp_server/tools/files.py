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
        """File utilities for managing EnergyPlus files.

        Args:
            action: The action to perform. Valid values are:
                - 'list': List available files in the workspace
                - 'copy': Copy a file from source to target
            include_example_files: Controls whether to include files from the EnergyPlus installation directory.
                **DEFAULT IS FALSE - workspace files only.**
                ONLY set to True if user explicitly asks for "EnergyPlus installation examples" or
                "official EnergyPlus example files". When user says "sample files" or "my files",
                keep this False to search workspace only. (for 'list' action only)
            include_weather_data: Controls whether to include weather (.epw) files in results.
                **DEFAULT IS FALSE.**
                ONLY set to True if user explicitly asks about weather files or .epw files.
                (for 'list' action only)
            extensions: Optional list of file extensions to filter (e.g., ['idf', 'epw']). (for 'list' action only)
            limit: Maximum number of files to return. Default 100. (for 'list' action only)
            source_path: Source file path (required for 'copy' action)
            target_path: Target file path (required for 'copy' action)
            file_types: List of file types to copy (for 'copy' action)
            overwrite: Whether to overwrite existing files (for 'copy' action)
            mode: Operation mode - 'apply' to execute, other values to preview

        Returns:
            JSON string with file list or copy operation results
        """
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

