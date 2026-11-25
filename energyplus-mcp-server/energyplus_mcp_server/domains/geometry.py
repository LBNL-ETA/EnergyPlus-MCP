"""
Geometry domain manager tool.

Provides actions for extracting, analyzing, and visualizing building geometry.
"""

from pathlib import Path
from typing import Any, Optional, Literal
import json
import logging

from ..utils import reply_summary
from ..utils.path_utils import report_path, saved_file_reply

logger = logging.getLogger(__name__)


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    """Register the geometry_manager tool with the MCP server."""
    logger.info("domains.geometry.register starting")
    
    @mcp.tool()
    async def geometry_manager(
        action: Literal["extract_and_summary", "generate_html_str", "capabilities"],
        idf_path: Optional[str] = None,
        pretty: bool = True,
        output_path: Optional[str] = None,  # generate_html_str: where to save the viewer
        detail: Literal["summary", "full"] = "summary",
        return_html: bool = False,
    ) -> str:
        """
        Geometry domain manager for building geometry operations.

        Actions:
        - extract_and_summary: Extract building geometry with summary in single JSON response
        - generate_html_str: Save the interactive 3D HTML viewer to reports/ (or
          output_path) and reply with its path and size; return_html=True
          returns the page itself instead
        - capabilities: List available actions and parameters

        Args:
            action: The operation to perform
            idf_path: Path to the IDF file (required for extract_and_summary/generate_html_str)
            pretty: Whether to format JSON with indentation (default: True)
            detail: extract_and_summary returns the summary and zones by default
                ("summary"); "full" adds every surface, subsurface and shading
                surface with its vertices

        Returns:
            For generate_html_str: HTML string for interactive 3D viewer
            For extract_and_summary: JSON string with geometry data
            For capabilities: JSON string with tool capabilities

        Examples:
            # Extract geometry with summary
            {"action": "extract_and_summary", "idf_path": "sample_files/basic/5ZoneAirCooled.idf"}

            # Generate HTML viewer string
            {"action": "generate_html_str", "idf_path": "sample_files/basic/5ZoneAirCooled.idf"}

            # List capabilities
            {"action": "capabilities"}
        """
        try:
            if action == "capabilities":
                return (
                    '{"tool":"geometry_manager",'
                    '"actions":['
                    '{"name":"extract_and_summary","description":"Extract geometry with summary","required":["idf_path"],"optional":["pretty"]},'
                    '{"name":"generate_html_str","description":"Generate HTML viewer string","required":["idf_path"],"optional":[]}]}'
                )
            
            if not idf_path:
                return '{"error":"Missing required parameter: idf_path"}'
            
            if action == "extract_and_summary":
                text = ep_manager.extract_geometry_with_summary(idf_path, pretty=pretty)
                if detail == "full":
                    return text
                return reply_summary.summarize_text(text, reply_summary.geometry_summary, indent=2 if pretty else None)

            if action == "generate_html_str":
                html = ep_manager.generate_geometry_html(idf_path)
                if return_html:
                    return html
                target = output_path or report_path(config, f"{Path(idf_path).stem}_geometry.html")
                Path(target).parent.mkdir(parents=True, exist_ok=True)
                Path(target).write_text(html, encoding="utf-8")
                return json.dumps(saved_file_reply(config, target, action="generate_html_str", viewer="geometry"))

            return f'{{"error":"Unsupported action: {action}"}}'
            
        except FileNotFoundError as e:
            logger.warning(f"Geometry file not found: {str(e)}")
            return f'{{"error":"File not found: {str(e)}"}}'
        except Exception as e:
            logger.error(f"geometry_manager error: {str(e)}", exc_info=True)
            return f'{{"error":"Error in geometry_manager: {str(e)}"}}'
    
    logger.info("domains.geometry.register complete: geometry_manager available")


# --- Reusable domain helpers (importable by orchestrators) ---
def geometry_extract_and_summary(
    ep_manager: Any, 
    idf_path: str, 
    pretty: bool = True
) -> str:
    """Extract geometry data with summary from IDF file."""
    return ep_manager.extract_geometry_with_summary(idf_path, pretty=pretty)


def geometry_html(ep_manager: Any, idf_path: str) -> str:
    """Generate HTML viewer for building geometry."""
    return ep_manager.generate_geometry_html(idf_path)


