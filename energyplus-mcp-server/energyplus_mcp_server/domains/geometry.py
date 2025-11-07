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
        action: Literal["extract", "summary", "visualize", "generate_html", "validate", "capabilities"],
        idf_path: Optional[str] = None,
        output_format: str = "json",
        output_path: Optional[str] = None,
        pretty: bool = True,
    ) -> str:
        """
        Geometry domain manager for building geometry operations.
        
        Actions:
        - extract: Extract complete geometry data (building, zones, surfaces, subsurfaces, shading)
        - summary: Get a human-readable summary of the geometry
        - visualize: Create an interactive 3D HTML viewer file (writes to disk)
        - generate_html: Generate HTML viewer string (no file writing)
        - validate: Validate geometry consistency (future implementation)
        - capabilities: List available actions and parameters
        
        Args:
            action: The operation to perform
            idf_path: Path to the IDF file (required for extract/summary/visualize/generate_html/validate)
            output_format: Format for output ("json", "threejs", or "summary") - used with extract action
            output_path: Output path for visualization files (used with visualize action)
            pretty: Whether to format JSON with indentation (default: True)
            
        Returns:
            JSON string, HTML string, or operation result depending on action
            
        Examples:
            # Extract complete geometry
            {"action": "extract", "idf_path": "sample_files/5ZoneAirCooled.idf"}
            
            # Extract in three.js format
            {"action": "extract", "idf_path": "sample_files/5ZoneAirCooled.idf", "output_format": "threejs"}
            
            # Generate HTML viewer (returns HTML string)
            {"action": "generate_html", "idf_path": "sample_files/5ZoneAirCooled.idf"}
            
            # Create interactive viewer file
            {"action": "visualize", "idf_path": "sample_files/5ZoneAirCooled.idf"}
            
            # Get summary
            {"action": "summary", "idf_path": "sample_files/5ZoneAirCooled.idf"}
            
            # List capabilities
            {"action": "capabilities"}
        """
        try:
            if action == "capabilities":
                return (
                    '{"tool":"geometry_manager",'
                    '"actions":['
                    '{"name":"extract","description":"Extract complete building geometry","required":["idf_path"],"optional":["output_format","pretty"]},'
                    '{"name":"summary","description":"Get human-readable geometry summary","required":["idf_path"]},'
                    '{"name":"generate_html","description":"Generate HTML viewer string (no file writing)","required":["idf_path"]},'
                    '{"name":"visualize","description":"Create interactive 3D HTML viewer file","required":["idf_path"],"optional":["output_path"]},'
                    '{"name":"validate","description":"Validate geometry consistency (future)","required":["idf_path"]}],'
                    '"output_formats":["json","threejs","summary"]}'
                )
            
            if not idf_path:
                return '{"error":"Missing required parameter: idf_path"}'
            
            if action == "extract":
                return ep_manager.extract_geometry(idf_path, output_format=output_format, pretty=pretty)
            
            if action == "summary":
                return ep_manager.get_geometry_summary(idf_path)
            
            if action == "generate_html":
                return ep_manager.generate_geometry_html(idf_path)
            
            if action == "visualize":
                return ep_manager.create_geometry_viewer(idf_path, output_path=output_path)
            
            if action == "validate":
                return '{"status":"not_implemented","message":"Geometry validation is planned for future release"}'
            
            return f'{{"error":"Unsupported action: {action}"}}'
            
        except FileNotFoundError as e:
            logger.warning(f"Geometry file not found: {str(e)}")
            return f'{{"error":"File not found: {str(e)}"}}'
        except Exception as e:
            logger.error(f"geometry_manager error: {str(e)}", exc_info=True)
            return f'{{"error":"Error in geometry_manager: {str(e)}"}}'
    
    logger.info("domains.geometry.register complete: geometry_manager available")


# --- Reusable domain helpers (importable by orchestrators) ---
def geometry_extract(
    ep_manager: Any, 
    idf_path: str, 
    output_format: str = "json", 
    pretty: bool = True
) -> str:
    """Extract geometry data from IDF file."""
    return ep_manager.extract_geometry(idf_path, output_format=output_format, pretty=pretty)


def geometry_summary(ep_manager: Any, idf_path: str) -> str:
    """Get geometry summary from IDF file."""
    return ep_manager.get_geometry_summary(idf_path)


