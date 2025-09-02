from typing import Any, Optional, Literal
import json


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    @mcp.tool()
    async def post_processing(
        action: Literal["interactive_plot", "parse_errors", "capabilities"],
        output_directory: Optional[str] = None,
        err_file_path: Optional[str] = None,
        idf_name: Optional[str] = None,
        file_type: Literal["auto", "meter", "variable"] = "auto",
        custom_title: Optional[str] = None,
    ) -> str:
        if action == "capabilities":
            return json.dumps({
                "tool": "post_processing",
                "actions": [
                    {"name": "interactive_plot", "required": ["output_directory"], "optional": ["idf_name", "file_type", "custom_title"]},
                    {"name": "parse_errors", "required": ["err_file_path"], "optional": []}
                ],
            }, indent=2)
        if action == "interactive_plot":
            if not output_directory:
                return "Missing required parameter: output_directory"
            result = ep_manager.create_interactive_plot(output_directory, idf_name, file_type, custom_title)
            return f"Interactive plot created:\n{result}"
        if action == "parse_errors":
            if not err_file_path:
                return "Missing required parameter: err_file_path"
            result = ep_manager.parse_simulation_errors(err_file_path)
            return json.dumps(result, indent=2)
        return f"Unsupported action: {action}"

