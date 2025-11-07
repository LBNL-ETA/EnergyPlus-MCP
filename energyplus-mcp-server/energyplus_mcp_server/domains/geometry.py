"""
Geometry domain manager tool.

Provides actions for extracting, analyzing, and visualizing building geometry.
"""

from typing import Any, Optional, Literal
import logging

logger = logging.getLogger(__name__)


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    """Register the geometry_manager tool with the MCP server."""
    logger.info("domains.geometry.register starting")
    
    @mcp.tool()
    async def geometry_manager(
        action: Literal["extract_and_summary", "generate_html", "capabilities"],
        idf_path: Optional[str] = None,
        pretty: bool = True,
    ) -> str:
        """
        Geometry domain manager for building geometry operations.
        
        Actions:
        - extract_and_summary: Extract building geometry with summary in single JSON response
        - generate_html: Generate interactive 3D HTML viewer string
        - capabilities: List available actions and parameters
        
        Args:
            action: The operation to perform
            idf_path: Path to the IDF file (required for extract_and_summary/generate_html)
            pretty: Whether to format JSON with indentation (default: True)
            
        Returns:
            JSON string or HTML string depending on action
            
        Examples:
            # Extract geometry with summary
            {"action": "extract_and_summary", "idf_path": "sample_files/5ZoneAirCooled.idf"}
            
            # Generate HTML viewer
            {"action": "generate_html", "idf_path": "sample_files/5ZoneAirCooled.idf"}
            
            # List capabilities
            {"action": "capabilities"}
        """
        try:
            if action == "capabilities":
                return (
                    '{"tool":"geometry_manager",'
                    '"actions":['
                    '{"name":"extract_and_summary","description":"Extract geometry with summary","required":["idf_path"],"optional":["pretty"]},'
                    '{"name":"generate_html","description":"Generate HTML viewer string","required":["idf_path"]}]}'
                )
            
            if not idf_path:
                return '{"error":"Missing required parameter: idf_path"}'
            
            if action == "extract_and_summary":
                return ep_manager.extract_geometry_with_summary(idf_path, pretty=pretty)
            
            if action == "generate_html":
                return ep_manager.generate_geometry_html(idf_path)
            
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


