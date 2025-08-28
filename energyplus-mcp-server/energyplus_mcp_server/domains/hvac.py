from typing import Any, Optional, Literal
import logging

logger = logging.getLogger(__name__)


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    logger.info("domains.hvac.register starting")
    @mcp.tool()
    async def hvac_manager(
        action: Literal["discover", "topology", "visualize", "capabilities"],
        idf_path: Optional[str] = None,
        loop_name: Optional[str] = None,
        output_path: Optional[str] = None,
        image_format: str = "png",
        show_legend: bool = True,
    ) -> str:
        """
        HVAC domain manager (unified).

        - discover: list loops and components
        - topology: detailed loop topology for a given loop
        - visualize: generate a diagram (returns path)
        - capabilities: enumerate actions
        """
        try:
            if action == "capabilities":
                return (
                    '{"tool":"hvac_manager","actions":[{"name":"discover","required":["idf_path"]},{"name":"topology","required":["idf_path","loop_name"]},{"name":"visualize","required":["idf_path"],"optional":["loop_name","output_path","image_format","show_legend"]}]}'
                )
            if not idf_path:
                return "Missing required parameter: idf_path"
            if action == "discover":
                return ep_manager.discover_hvac_loops(idf_path)
            if action == "topology":
                if not loop_name:
                    return "Missing required parameter: loop_name"
                return ep_manager.get_loop_topology(idf_path, loop_name)
            if action == "visualize":
                return ep_manager.visualize_loop_diagram(idf_path, loop_name, output_path, image_format, show_legend)
            return f"Unsupported action: {action}"
        except FileNotFoundError as e:
            logger.warning(f"HVAC file not found: {str(e)}")
            return f"File not found: {str(e)}"
        except Exception as e:
            logger.error(f"hvac_manager error: {str(e)}")
            return f"Error in hvac_manager: {str(e)}"
    logger.info("domains.hvac.register complete: hvac_manager available")


# --- Reusable domain helpers (importable by orchestrators) ---
def hvac_discover(ep_manager: Any, idf_path: str) -> str:
    return ep_manager.discover_hvac_loops(idf_path)


def hvac_topology(ep_manager: Any, idf_path: str, loop_name: str) -> str:
    return ep_manager.get_loop_topology(idf_path, loop_name)


def hvac_visualize(
    ep_manager: Any,
    idf_path: str,
    loop_name: Optional[str] = None,
    output_path: Optional[str] = None,
    image_format: str = "png",
    show_legend: bool = True,
) -> str:
    return ep_manager.visualize_loop_diagram(idf_path, loop_name, output_path, image_format, show_legend)
