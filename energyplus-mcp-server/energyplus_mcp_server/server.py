"""
EnergyPlus MCP Server with FastMCP
"""

import os
import asyncio
import logging
import json
from typing import Optional, Dict, Any, List, Literal
from pathlib import Path
from datetime import datetime

# Import FastMCP instead of the low-level Server
from mcp.server.fastmcp import FastMCP

# Import our EnergyPlus utilities and configuration
from energyplus_mcp_server.energyplus_tools import EnergyPlusManager
from energyplus_mcp_server.config import get_config, Config
from energyplus_mcp_server.domains import register_all as register_domain_managers
from energyplus_mcp_server.tools import register_all as register_master_tools

logger = logging.getLogger(__name__)

# Initialize configuration and set up logging
config = get_config()

# Optional YAML tool-surface config
def _load_tool_surface_config() -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "mode": None,
        "enable_wrappers": None,
        "domains": {"envelope": None, "internal_loads": None, "hvac": None},
    }
    path = os.getenv("MCP_CONFIG_PATH") or str(Path(config.paths.workspace_root) / "config.yaml")
    try:
        import yaml  # type: ignore
        if os.path.exists(path):
            with open(path, "r") as f:
                data = yaml.safe_load(f) or {}
            ts = (data or {}).get("tool_surface", {})
            cfg["mode"] = ts.get("mode")
            cfg["enable_wrappers"] = ts.get("enable_wrappers")
            doms = ts.get("domains", {}) or {}
            cfg["domains"]["envelope"] = doms.get("envelope")
            cfg["domains"]["internal_loads"] = doms.get("internal_loads")
            cfg["domains"]["hvac"] = doms.get("hvac")
            logger.info(f"Loaded tool_surface config from {path}: {cfg}")
        else:
            logger.info(f"Tool surface config not found at {path}; using defaults/env flags")
    except Exception as e:
        logger.info(f"YAML not available or failed to parse ({e}); using defaults/env flags")
    return cfg

tool_surface_cfg = _load_tool_surface_config()

# Initialize the FastMCP server with configuration
mcp = FastMCP(config.server.name)

# Flag to control exposure of individual inspect wrappers
EXPOSE_INSPECT_WRAPPERS = os.getenv("MCP_EXPOSE_INSPECT_WRAPPERS", "false").lower() in ("1", "true", "yes")
EXPOSE_OUTPUT_WRAPPERS = os.getenv("MCP_EXPOSE_OUTPUT_WRAPPERS", "false").lower() in ("1", "true", "yes")
EXPOSE_SUMMARY_WRAPPER = os.getenv("MCP_EXPOSE_SUMMARY_WRAPPER", "false").lower() in ("1", "true", "yes")
EXPOSE_MODIFY_WRAPPERS = os.getenv("MCP_EXPOSE_MODIFY_WRAPPERS", "false").lower() in ("1", "true", "yes")
EXPOSE_SERVER_WRAPPERS = os.getenv("MCP_EXPOSE_SERVER_WRAPPERS", "false").lower() in ("1", "true", "yes")
EXPOSE_HVAC_WRAPPERS = os.getenv("MCP_EXPOSE_HVAC_WRAPPERS", "false").lower() in ("1", "true", "yes")
EXPOSE_FILE_WRAPPERS = os.getenv("MCP_EXPOSE_FILE_WRAPPERS", "false").lower() in ("1", "true", "yes")
# Model wrapper exposure (load/validate wrappers)
EXPOSE_MODEL_WRAPPERS = os.getenv("MCP_EXPOSE_MODEL_WRAPPERS", "false").lower() in ("1", "true", "yes")
# Post-processing wrapper exposure
EXPOSE_POST_WRAPPERS = os.getenv("MCP_EXPOSE_POST_WRAPPERS", "false").lower() in ("1", "true", "yes")
# Domain managers and masters exposure (default masters on, domains via config or env)
EXPOSE_DOMAIN_MANAGERS = os.getenv("MCP_EXPOSE_DOMAIN_MANAGERS", "false").lower() in ("1", "true", "yes")
EXPOSE_MASTERS = os.getenv("MCP_EXPOSE_MASTERS", "true").lower() in ("1", "true", "yes")

def _apply_tool_surface_overrides() -> None:
    global EXPOSE_DOMAIN_MANAGERS, EXPOSE_MASTERS
    global EXPOSE_INSPECT_WRAPPERS, EXPOSE_OUTPUT_WRAPPERS, EXPOSE_SUMMARY_WRAPPER
    global EXPOSE_MODIFY_WRAPPERS, EXPOSE_SERVER_WRAPPERS, EXPOSE_HVAC_WRAPPERS
    global EXPOSE_FILE_WRAPPERS, EXPOSE_MODEL_WRAPPERS, EXPOSE_POST_WRAPPERS

    mode = (tool_surface_cfg.get("mode") or "").lower()
    if mode in ("masters", "domains", "hybrid"):
        EXPOSE_MASTERS = mode in ("masters", "hybrid")
        EXPOSE_DOMAIN_MANAGERS = mode in ("domains", "hybrid")
        logger.info(f"Tool surface mode='{mode}' => masters={EXPOSE_MASTERS}, domains={EXPOSE_DOMAIN_MANAGERS}")
    ew = tool_surface_cfg.get("enable_wrappers")
    if isinstance(ew, bool):
        EXPOSE_INSPECT_WRAPPERS = ew
        EXPOSE_OUTPUT_WRAPPERS = ew
        EXPOSE_SUMMARY_WRAPPER = ew
        EXPOSE_MODIFY_WRAPPERS = ew
        EXPOSE_SERVER_WRAPPERS = ew
        EXPOSE_HVAC_WRAPPERS = ew
        EXPOSE_FILE_WRAPPERS = ew
        EXPOSE_MODEL_WRAPPERS = ew
        EXPOSE_POST_WRAPPERS = ew
        logger.info(f"Wrapper exposure overridden by config: {ew}")

_apply_tool_surface_overrides()
# Simulation wrapper exposure (run/modify wrappers)
EXPOSE_SIM_WRAPPERS = os.getenv("MCP_EXPOSE_SIM_WRAPPERS", "false").lower() in ("1", "true", "yes")

def expose_inspect_tool():
    def _noop(func):
        return func
    return _noop

def expose_output_tool():
    def _noop(func):
        return func
    return _noop

def expose_summary_tool():
    def _noop(func):
        return func
    return _noop

def expose_modify_tool():
    def _noop(func):
        return func
    return _noop

def expose_server_tool():
    def _noop(func):
        return func
    return _noop

def expose_hvac_tool():
    def _noop(func):
        return func
    return _noop

def expose_file_tool():
    def _noop(func):
        return func
    return _noop

def expose_sim_tool():
    """Decorator factory: expose simulation wrappers only when enabled."""
    if EXPOSE_SIM_WRAPPERS:
        return mcp.tool()
    def _noop(func):
        return func
    return _noop

def expose_model_tool():
    def _noop(func):
        return func
    return _noop

def expose_post_tool():
    def _noop(func):
        return func
    return _noop

def expose_master_tool():
    def _noop(func):
        return func
    return _noop

# Initialize EnergyPlus manager with configuration
ep_manager = EnergyPlusManager(config)

logger.info(f"EnergyPlus MCP Server '{config.server.name}' v{config.server.version} initialized")
# Track startup time for reporting uptime
STARTUP_TIME = datetime.utcnow()

# Optionally register domain manager tools
logger.info("EXPOSE_DOMAIN_MANAGERS=%s EXPOSE_MASTERS=%s", EXPOSE_DOMAIN_MANAGERS, EXPOSE_MASTERS)
if EXPOSE_DOMAIN_MANAGERS:
    # Override per-domain toggles via YAML if provided
    doms = tool_surface_cfg.get("domains") or {}
    envelope = doms.get("envelope")
    internal_loads = doms.get("internal_loads")
    hvac = doms.get("hvac")
    outputs = doms.get("outputs")
    register_domain_managers(
        mcp,
        ep_manager,
        config,
        envelope=True if envelope is None else bool(envelope),
        internal_loads=True if internal_loads is None else bool(internal_loads),
        hvac=True if hvac is None else bool(hvac),
        outputs=True if outputs else False,
    )
    logger.info("Domain manager tools registered")
else:
    logger.info("Domain manager tools not registered (flag disabled)")

# Register master tools via submodules when requested.
if EXPOSE_MASTERS:
    # Prevent local definitions (below) from registering by setting flag false,
    # and rely on submodule registration instead.
    EXPOSE_MASTERS = False
    register_master_tools(mcp, ep_manager, config)
    # Provide STARTUP_TIME to tools.server for uptime reporting
    try:
        from energyplus_mcp_server.tools import server as tools_server
        tools_server.STARTUP_TIME = STARTUP_TIME
    except Exception:
        pass
    logger.info("Master tools registered via tools/ submodules")


"""Tools are registered via domains/ and tools/ submodules based on config.yaml.
This module bootstraps configuration and FastMCP, then registers tool groups.
"""

@expose_file_tool()
async def copy_file(source_path: str, target_path: str, overwrite: bool = False, file_types: Optional[List[str]] = None) -> str:
    """
    Copy a file from source to target location with intelligent path resolution
    
    Args:
        source_path: Source file path. Can be:
                    - Absolute path: "/full/path/to/file.idf"
                    - Relative path: "models/mymodel.idf"
                    - Filename only: "1ZoneUncontrolled.idf" (searches in sample_files)
                    - Fuzzy name: Will search in sample_files, example_files, weather_data, etc.
        target_path: Target path for the copy. Can be:
                    - Absolute path: "/full/path/to/copy.idf"
                    - Relative path: "outputs/modified_file.idf"  
                    - Filename only: "my_copy.idf" (saves to outputs directory)
        overwrite: Whether to overwrite existing target file (default: False)
        file_types: List of acceptable file extensions (e.g., [".idf", ".epw"]). If None, accepts any file type.
    
    Returns:
        JSON string with copy operation results including resolved paths, file sizes, and validation status
        
    Examples:
        # Copy IDF file with validation
        copy_file("1ZoneUncontrolled.idf", "my_model.idf", file_types=[".idf"])
        
        # Copy weather file
        copy_file("USA_CA_San.Francisco.epw", "sf_weather.epw", file_types=[".epw"])
        
        # Copy any file type
        copy_file("sample.idf", "outputs/test.idf", overwrite=True)
        
        # Copy with fuzzy matching (e.g., city name for weather files)
        copy_file("san francisco", "my_weather.epw", file_types=[".epw"])
    """
    return json.dumps({"error": "copy_file wrapper removed; use file_utils in tools/"}, indent=2)


@expose_master_tool()
async def server_manager(
    action: Literal["status", "logs", "clear_logs"],
    include_config: bool = False,
    detail: Literal["summary", "detailed"] = "summary",
    type: Literal["server", "error", "both"] = "server",
    lines: int = 50,
    contains: Optional[str] = None,
    since: Optional[str] = None,
    format: Literal["summary", "raw"] = "summary",
    select: Literal["server", "error", "both"] = "both",
    mode: Literal["dry_run", "apply"] = "dry_run",
) -> str:
    """
    Unified server management:
    - action="status": returns server/system/energyplus/logs info (include_config to add config; detail controls verbosity)
    - action="logs": returns recent logs with filters (type, lines, contains, since, format)
    - action="clear_logs": rotates logs safely (select, mode), never deletes
    """
    log_dir = Path(config.paths.workspace_root) / "logs"
    now = datetime.utcnow().isoformat()

    def _file_info(p: Path) -> Dict[str, Any]:
        try:
            return {
                "path": str(p),
                "exists": p.exists(),
                "size_bytes": p.stat().st_size if p.exists() else 0,
                "last_modified": datetime.utcfromtimestamp(p.stat().st_mtime).isoformat() if p.exists() else None,
            }
        except Exception:
            return {"path": str(p), "exists": False}

    if action == "status":
        try:
            uptime_seconds = int((datetime.utcnow() - STARTUP_TIME).total_seconds())
            import sys, platform
            data = {
                "server": {
                    "name": config.server.name,
                    "version": config.server.version,
                    "log_level": config.server.log_level,
                    "startup_time": STARTUP_TIME.isoformat(),
                    "uptime_seconds": uptime_seconds,
                    "debug_mode": config.debug_mode,
                },
                "system": {
                    "python_version": sys.version,
                    "platform": platform.platform(),
                    "architecture": platform.architecture()[0],
                },
                "energyplus": {
                    "version": config.energyplus.version,
                    "idd_available": os.path.exists(config.energyplus.idd_path) if config.energyplus.idd_path else False,
                    "executable_available": os.path.exists(config.energyplus.executable_path) if config.energyplus.executable_path else False,
                },
                "logs": {
                    "directory": str(log_dir),
                    "server_log": _file_info(log_dir / "energyplus_mcp_server.log"),
                    "error_log": _file_info(log_dir / "energyplus_mcp_errors.log"),
                },
            }
            if include_config and detail == "detailed":
                try:
                    data["config"] = json.loads(ep_manager.get_configuration_info())
                except Exception:
                    data["config"] = {"note": "configuration info unavailable"}

            return json.dumps({"meta": {"action": action, "detail": detail, "timestamp": now}, "data": data}, indent=2)
        except Exception as e:
            logger.error(f"server_manager status error: {e}")
            return f"Error getting status: {str(e)}"

    if action == "logs":
        try:
            targets: List[Path] = []
            if type in ("server", "both"):
                targets.append(log_dir / "energyplus_mcp_server.log")
            if type in ("error", "both"):
                targets.append(log_dir / "energyplus_mcp_errors.log")

            files_meta = [_file_info(p) for p in targets]
            content_parts: List[str] = []
            truncated = False

            def _parse_line_ts(line: str) -> Optional[datetime]:
                # Expect leading 'YYYY-MM-DD HH:MM:SS'
                try:
                    ts = line[:19]
                    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    return None

            since_dt = None
            if since:
                try:
                    since_dt = datetime.fromisoformat(since)
                except Exception:
                    since_dt = None

            for p in targets:
                if not p.exists():
                    continue
                with open(p, "r") as f:
                    lines_all = f.readlines()
                lines_filtered = lines_all
                if contains:
                    lines_filtered = [ln for ln in lines_filtered if contains in ln]
                if since_dt:
                    tmp = []
                    for ln in lines_filtered:
                        ts = _parse_line_ts(ln)
                        if (ts is None) or (ts >= since_dt):
                            tmp.append(ln)
                    lines_filtered = tmp
                if len(lines_filtered) > lines:
                    lines_filtered = lines_filtered[-lines:]
                    truncated = True
                content_parts.append("".join(lines_filtered))

            data = {
                "files": files_meta,
                "showing": {"type": type, "lines": lines, "filtered_contains": contains or None, "since": since},
                "truncated": truncated,
            }
            if content_parts:
                data["content"] = "\n\n".join(content_parts)

            return json.dumps({"meta": {"action": action, "detail": format, "timestamp": now}, "data": data}, indent=2)
        except Exception as e:
            logger.error(f"server_manager logs error: {e}")
            return f"Error getting logs: {str(e)}"

    if action == "clear_logs":
        try:
            to_rotate: List[Path] = []
            if select in ("server", "both"):
                to_rotate.append(log_dir / "energyplus_mcp_server.log")
            if select in ("error", "both"):
                to_rotate.append(log_dir / "energyplus_mcp_errors.log")
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            plan = []
            for p in to_rotate:
                if p.exists():
                    suggested = p.with_name(f"{p.stem}_backup_{ts}{p.suffix}")
                    plan.append({"from": str(p), "to": str(suggested)})
            if mode == "dry_run":
                return json.dumps({
                    "meta": {"action": action, "mode": mode, "timestamp": now},
                    "data": {"will_rotate": plan, "backup_dir": str(log_dir)}
                }, indent=2)
            rotated = []
            for item in plan:
                src = Path(item["from"])
                dst = Path(item["to"])
                try:
                    if src.exists():
                        src.rename(dst)
                        rotated.append({"from": str(src), "to": str(dst)})
                except Exception as e:
                    logger.error(f"Error rotating {src}: {e}")
            return json.dumps({
                "meta": {"action": action, "mode": mode, "timestamp": now},
                "data": {"rotated": rotated, "backup_dir": str(log_dir), "message": "Log files rotated"}
            }, indent=2)
        except Exception as e:
            logger.error(f"server_manager clear_logs error: {e}")
            return f"Error clearing logs: {str(e)}"

    return json.dumps({"error": f"Unknown action '{action}'"}, indent=2)


@expose_master_tool()
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
    """
    Unified HVAC loop inspection tool.

    - action="discover": List HVAC loops by type (plant/air/condenser or all)
    - action="topology": Get detailed topology for a specific loop
    - action (future): "visualize" handled via legacy wrapper for now; reserved parameters included

    Args:
      idf_path: Path to the IDF file.
      types: Loop types to include when discovering (ignored for topology).
      loop_name: Target loop for topology view (required for topology).
      detail: Controls verbosity of returned payload.
      format: Reserved for future graph outputs (currently returns JSON structures).
    """
    timestamp = datetime.utcnow().isoformat()
    try:
        if action == "discover":
            loops_json = hvac_discover(ep_manager, idf_path)
            try:
                loops_data = json.loads(loops_json)
            except Exception:
                loops_data = {"raw": loops_json}

            if isinstance(loops_data, dict) and types != "all":
                filtered: Dict[str, Any] = {}
                # Keep only requested type key if present
                key_map = {"plant": "PlantLoops", "air": "AirLoops", "condenser": "CondenserLoops"}
                sel_key = key_map.get(types)
                if sel_key and sel_key in loops_data:
                    filtered[sel_key] = loops_data.get(sel_key)
                else:
                    filtered = loops_data  # fallback
                data = filtered
            else:
                data = loops_data

            payload = {"meta": {"action": action, "idf_path": idf_path, "types": types, "detail": detail, "timestamp": timestamp},
                       "data": data}
            return json.dumps(payload, indent=2)

        if action == "topology":
            if not loop_name:
                return json.dumps({"error": "loop_name is required for action='topology'"}, indent=2)
            topo_json = hvac_topology(ep_manager, idf_path, loop_name)
            try:
                topo = json.loads(topo_json)
            except Exception:
                topo = {"raw": topo_json}
            payload = {"meta": {"action": action, "idf_path": idf_path, "loop_name": loop_name, "detail": detail, "timestamp": timestamp},
                       "data": topo}
            return json.dumps(payload, indent=2)

        if action == "visualize":
            viz_json = hvac_visualize(ep_manager, idf_path, loop_name, output_path, image_format, show_legend)
            try:
                viz = json.loads(viz_json)
            except Exception:
                viz = {"raw": viz_json}
            payload = {"meta": {"action": action, "idf_path": idf_path, "loop_name": loop_name, "image_format": image_format, "timestamp": timestamp},
                       "data": viz}
            return json.dumps(payload, indent=2)

        return json.dumps({"error": f"Unknown action '{action}'"}, indent=2)
    except ValueError as e:
        # Try to assist by returning available loops
        assist = None
        try:
            assist = json.loads(ep_manager.discover_hvac_loops(idf_path))
        except Exception:
            assist = None
        return json.dumps({
            "error": str(e),
            "hints": {"available_loops": assist} if assist else {"note": "Could not discover available loops"}
        }, indent=2)
    except FileNotFoundError as e:
        return f"File not found: {str(e)}"
    except Exception as e:
        logger.error(f"hvac_loop_inspect error: {e}")
        return f"Error inspecting HVAC loops: {str(e)}"


@expose_master_tool()
async def file_utils(
    action: Literal["list", "copy"],
    # list options
    include_example_files: bool = False,
    include_weather_data: bool = False,
    extensions: Optional[List[str]] = None,
    contains: Optional[str] = None,
    limit: int = 200,
    # copy options
    source_path: Optional[str] = None,
    target_path: Optional[str] = None,
    overwrite: bool = False,
    file_types: Optional[List[str]] = None,
    mode: Literal["dry_run", "apply"] = "dry_run",
) -> str:
    """
    Unified file utilities: list available files and copy files with path resolution.

    - action="list": returns files from sample/example/weather directories.
      Filters: extensions, contains (substring), limit per category.
    - action="copy": resolves paths (dry_run) or performs copy (apply) via ep_manager.
    """
    try:
        if action == "list":
            raw = ep_manager.list_available_files(include_example_files, include_weather_data)
            try:
                data = json.loads(raw)
            except Exception:
                return raw
            # Apply filters
            def _filter_list(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
                out = []
                for it in items:
                    name = it.get("name", "")
                    if contains and contains not in name:
                        continue
                    if extensions:
                        if not any(name.lower().endswith(ext.lower()) for ext in extensions):
                            continue
                    out.append(it)
                    if len(out) >= max(1, limit):
                        break
                return out

            for key in list(data.keys()):
                section = data[key]
                for cat in ("IDF files", "Weather files", "Other files"):
                    if cat in section and isinstance(section[cat], list):
                        section[cat] = _filter_list(section[cat])

            return json.dumps({
                "meta": {
                    "action": action,
                    "include_example_files": include_example_files,
                    "include_weather_data": include_weather_data,
                    "extensions": extensions,
                    "contains": contains,
                    "limit": limit,
                },
                "data": data,
            }, indent=2)

        if action == "copy":
            if not source_path or not target_path:
                return json.dumps({"error": "source_path and target_path are required for copy"}, indent=2)
            if mode == "apply":
                return await copy_file(source_path=source_path, target_path=target_path, overwrite=overwrite, file_types=file_types)
            # dry_run: resolve paths without writing
            try:
                from energyplus_mcp_server.utils.path_utils import resolve_path
                file_description = "file"
                if file_types:
                    if ".idf" in file_types:
                        file_description = "IDF file"
                    elif ".epw" in file_types:
                        file_description = "weather file"
                enable_fuzzy = file_types and ".epw" in file_types
                resolved_source = resolve_path(config, source_path, file_types, file_description, must_exist=True, enable_fuzzy_weather_matching=enable_fuzzy)
                resolved_target = resolve_path(config, target_path, must_exist=False, description="target file")
                will_overwrite = os.path.exists(resolved_target)
                return json.dumps({
                    "meta": {"action": action, "mode": mode},
                    "plan": {
                        "source_path": source_path,
                        "resolved_source": resolved_source,
                        "target_path": target_path,
                        "resolved_target": resolved_target,
                        "will_overwrite": will_overwrite,
                        "overwrite": overwrite,
                        "file_types": file_types,
                    }
                }, indent=2)
            except Exception as e:
                return json.dumps({"error": f"Path resolution failed: {str(e)}"}, indent=2)

        return json.dumps({"error": f"Unknown action '{action}'"}, indent=2)
    except Exception as e:
        logger.error(f"file_utils error: {e}")
        return f"Error in file_utils: {str(e)}"


@mcp.tool()
async def modify_basic_parameters(
    idf_path: str,
    operations: List[Dict[str, Any]],
    mode: Literal["dry_run", "apply"] = "dry_run",
    output_path: Optional[str] = None,
    validation_level: Literal["strict", "moderate", "lenient"] = "moderate",
    conflict_strategy: Literal["error", "skip", "overwrite"] = "error",
    capabilities: bool = False,
    detail: Literal["summary", "detailed"] = "summary",
) -> str:
    """
    Orchestrate non-HVAC model modifications by delegating to existing helpers.

    Args:
        idf_path: Path to the input IDF file.
        operations: List of operations with fields:
          - op: one of [
              "people.update", "lights.update", "electric_equipment.update",
              "infiltration.scale", "envelope.add_window_film", "envelope.add_coating",
              "outputs.add_variables", "outputs.add_meters"
            ]
          - target: optional object with selection hints (passed through where supported)
          - params: op-specific parameters (see individual modify_* tools for shapes)
        mode: "dry_run" (default) validates and returns a plan; "apply" executes changes.
        output_path: Optional final output path (if provided and mode==apply, final file is copied here).
        validation_level: Validation strictness passed to output ops where applicable.
        conflict_strategy: Future use; reserved for in-place/conflict behaviors.
        capabilities: If true (or when mode="dry_run" and operations=[]), return capability info
          describing supported operations and parameter schemas without making changes.
        detail: Controls verbosity of capabilities payload ("summary" or "detailed").

    Returns:
        JSON with meta, per-op results, errors, and final file path if applied.
    """
    logger.info(f"modify_basic_parameters start: {idf_path}, mode={mode}, ops={len(operations)}")

    allowed_ops = {
        "people.update",
        "lights.update",
        "electric_equipment.update",
        "infiltration.scale",
        "envelope.add_window_film",
        "envelope.add_coating",
        "outputs.add_variables",
        "outputs.add_meters",
    }

    # Capabilities mode: describe what can be modified safely
    if capabilities or (mode.lower() == "dry_run" and not operations):
        try:
            freq_enum_vars = list(getattr(ep_manager.output_var_manager, "VALID_FREQUENCIES", {}).keys())
            freq_enum_meters = list(getattr(ep_manager.output_meter_manager, "VALID_FREQUENCIES", {}).keys())
            meter_types = list(getattr(ep_manager.output_meter_manager, "VALID_METER_TYPES", {}).keys())
        except Exception:
            freq_enum_vars, freq_enum_meters, meter_types = [], [], []

        ops_spec = [
            {"op": "people.update", "description": "Update People objects by all/zone/name target.",
             "params": {"modifications": "list of {target, field_updates}"}},
            {"op": "lights.update", "description": "Update Lights objects by all/zone/name target.",
             "params": {"modifications": "list of {target, field_updates}"}},
            {"op": "electric_equipment.update", "description": "Update ElectricEquipment by all/zone/name target.",
             "params": {"modifications": "list of {target, field_updates}"}},
            # Simulation settings updates moved to simulation_manager tool
            {"op": "infiltration.scale", "description": "Scale ZoneInfiltration:DesignFlowRate by factor.",
             "params": {"mult": 0.9}},
            {"op": "envelope.add_window_film", "description": "Apply exterior window film via SimpleGlazingSystem.",
             "params": {"u_value": 4.94, "shgc": 0.45, "visible_transmittance": 0.66}},
            {"op": "envelope.add_coating", "description": "Apply exterior coating to walls or roofs.",
             "params": {"location": "wall|roof", "solar_abs": 0.4, "thermal_abs": 0.9}},
            {"op": "outputs.add_variables", "description": "Add Output:Variable entries.",
             "params": {"variables": "list[str|[name,frequency]|dict]", "validation_level": validation_level, "allow_duplicates": False}},
            {"op": "outputs.add_meters", "description": "Add Output:Meter entries.",
             "params": {"meters": "list[str|[name,frequency]|dict]", "validation_level": validation_level, "allow_duplicates": False}},
        ]

        targets = {
            "people.update|lights.update|electric_equipment.update": [
                "all", "zone:ZoneName", "name:ObjectName"
            ]
        }

        enums = {
            "reporting_frequencies_variables": freq_enum_vars,
            "reporting_frequencies_meters": freq_enum_meters,
            "meter_types": meter_types,
        }

        model_hints: Dict[str, Any] = {"included": False}
        # Provide light model hints if an idf_path is given and detail requested
        if idf_path and detail == "detailed":
            try:
                zones_json = ep_manager.list_zones(idf_path)
                zone_list = json.loads(zones_json)
                model_hints = {
                    "included": True,
                    "zones": [z.get("Name") for z in zone_list][:10],
                    "zones_count": len(zone_list),
                }
            except Exception:
                model_hints = {"included": False}

        capability_payload = {
            "meta": {
                "idf_path": idf_path,
                "mode": mode,
                "capabilities": True,
                "detail": detail,
            },
            "supported_ops": ops_spec,
            "targets": targets,
            "enums": enums,
            "limitations": [
                "HVAC graph edits are not handled by this orchestrator.",
                "Schedules and geometry edits are out of scope here.",
            ],
            "model_hints": model_hints,
            "examples": [
                {
                    "op": "people.update",
                    "params": {"modifications": [{"target": "all", "field_updates": {"Number_of_People": 10}}]}
                },
                {
                    "op": "outputs.add_variables",
                    "params": {"variables": [["Zone Air Temperature", "hourly"]]}
                }
            ],
        }
        return json.dumps(capability_payload, indent=2)

    plan = []
    errors: Dict[str, Any] = {}
    results: List[Dict[str, Any]] = []

    # Basic schema validation and planning
    for idx, op in enumerate(operations):
        op_name = str(op.get("op", "")).strip()
        if op_name not in allowed_ops:
            errors[str(idx)] = f"Unknown op '{op_name}'. Allowed: {sorted(list(allowed_ops))}"
            continue
        plan.append({"index": idx, "op": op_name})

    if mode.lower() != "apply":
        payload = {
            "meta": {
                "idf_path": idf_path,
                "mode": mode,
                "validation_level": validation_level,
                "conflict_strategy": conflict_strategy,
            },
            "plan": plan,
            "errors": errors,
        }
        return json.dumps(payload, indent=2)

    # Apply mode: execute sequentially and chain output files
    current_path = idf_path
    final_output = None

    for idx, op in enumerate(operations):
        op_name = str(op.get("op", "")).strip()
        target = op.get("target", {}) or {}
        params = op.get("params", {}) or {}

        if op_name not in allowed_ops:
            results.append({"index": idx, "op": op_name, "status": "error", "error": "unsupported"})
            continue

        try:
            if op_name in {"people.update", "lights.update", "electric_equipment.update"}:
                mods = params.get("modifications") or []
                resp = modify_internal_loads(ep_manager, current_path, op_name, mods, None)
            # simulation_control.update and run_period.update are handled via simulation_manager
            elif op_name in {"infiltration.scale", "envelope.add_window_film", "envelope.add_coating"}:
                resp = modify_envelope(ep_manager, current_path, op_name, params, None)
            elif op_name == "outputs.add_variables":
                resp = ep_manager.add_output_variables(
                    idf_path=current_path,
                    variables=params.get("variables", []),
                    validation_level=str(params.get("validation_level", validation_level)),
                    allow_duplicates=bool(params.get("allow_duplicates", False)),
                    output_path=None,
                )
            elif op_name == "outputs.add_meters":
                resp = ep_manager.add_output_meters(
                    idf_path=current_path,
                    meters=params.get("meters", []),
                    validation_level=str(params.get("validation_level", validation_level)),
                    allow_duplicates=bool(params.get("allow_duplicates", False)),
                    output_path=None,
                )

            status = "applied"
            output_file = None
            try:
                data = json.loads(resp)
                output_file = data.get("output_file") or data.get("output_path")
            except Exception:
                data = {"raw": resp}

            if output_file:
                current_path = output_file
                final_output = output_file

            results.append({
                "index": idx,
                "op": op_name,
                "status": status,
                "output_file": output_file,
            })

        except FileNotFoundError as e:
            logger.warning(f"File not found during modify_basic_parameters: {current_path}")
            results.append({"index": idx, "op": op_name, "status": "error", "error": f"File not found: {str(e)}"})
        except Exception as e:
            logger.error(f"Error applying op {op_name} at index {idx}: {str(e)}")
            results.append({"index": idx, "op": op_name, "status": "error", "error": str(e)})

    # Optional final copy
    final_copied = None
    if output_path and final_output:
        try:
            ep_manager.copy_file(final_output, output_path, True, None)
            final_copied = output_path
        except Exception as e:
            errors["final_copy"] = str(e)

    payload = {
        "meta": {
            "idf_path": idf_path,
            "mode": mode,
            "validation_level": validation_level,
            "conflict_strategy": conflict_strategy,
        },
        "results": results,
        "final_file": final_copied or final_output or idf_path,
        "errors": errors,
    }
    logger.info("modify_basic_parameters complete")
    return json.dumps(payload, indent=2)


@expose_model_tool()
async def load_idf_model(idf_path: str) -> str:
    """
    Deprecated thin wrapper. Use model_preflight(action="load").
    
    Args:
        idf_path: Path to the IDF file (can be absolute, relative, or just filename for sample files)
    
    Returns:
        JSON string with model information and loading status
    """
    # Delegate to unified preflight tool
    return await model_preflight(action="load", idf_path=idf_path)


@expose_summary_tool()
async def get_model_summary(idf_path: str) -> str:
    """
    Get basic model information (Building, Site, SimulationControl, Version)
    
    Args:
        idf_path: Path to the IDF file
    
    Returns:
        JSON string with model summary information
    """
    try:
        logger.info(f"Getting model summary: {idf_path}")
        summary = ep_manager.get_model_basics(idf_path)
        return f"Model Summary for {idf_path}:\n{summary}"
    except FileNotFoundError as e:
        logger.warning(f"IDF file not found: {idf_path}")
        return f"File not found: {str(e)}"
    except Exception as e:
        logger.error(f"Error getting model summary for {idf_path}: {str(e)}")
        return f"Error getting model summary for {idf_path}: {str(e)}"


@expose_master_tool()
async def model_preflight(
    action: Literal["load", "validate", "info", "resolve_paths", "readiness", "capabilities"],
    idf_path: Optional[str] = None,
    weather_file: Optional[str] = None,
    detail: Literal["summary", "detailed"] = "summary",
) -> str:
    """
    Read-only model preflight: load, validate, info, path resolution, readiness.

    - load: basic open + counts
    - validate: errors/warnings from ep_manager.validate_idf
    - info: model basics (Building, Site, SimulationControl, Version)
    - resolve_paths: resolve idf/weather paths using server config
    - readiness: quick verdict with issues list (idd, idf, optional weather)
    - capabilities: enumerate actions + params
    """
    try:
        if action == "capabilities":
            payload = {
                "tool": "model_preflight",
                "actions": [
                    {"name": "load", "required": ["idf_path"]},
                    {"name": "validate", "required": ["idf_path"]},
                    {"name": "info", "required": ["idf_path"]},
                    {"name": "resolve_paths", "required": ["idf_path"], "optional": ["weather_file"]},
                    {"name": "readiness", "required": ["idf_path"], "optional": ["weather_file"]},
                ],
                "detail": detail,
            }
            return json.dumps(payload, indent=2)

        if not idf_path and action != "capabilities":
            return "Missing required parameter: idf_path"

        if action == "load":
            logger.info(f"model_preflight.load: {idf_path}")
            result = ep_manager.load_idf(idf_path)
            return json.dumps(result, indent=2)

        if action == "validate":
            logger.info(f"model_preflight.validate: {idf_path}")
            result = ep_manager.validate_idf(idf_path)
            return f"Validation results for {idf_path}:\n{result}"

        if action == "info":
            logger.info(f"model_preflight.info: {idf_path}")
            result = ep_manager.get_model_basics(idf_path)
            return f"Model basics for {idf_path}:\n{result}"

        if action == "resolve_paths":
            logger.info(f"model_preflight.resolve_paths: idf={idf_path}, weather={weather_file}")
            idf_resolved = ep_manager._resolve_idf_path(idf_path)  # Uses config + search paths
            weather_resolved = None
            weather_error = None
            if weather_file:
                try:
                    weather_resolved = ep_manager._resolve_weather_file_path(weather_file)
                except Exception as e:
                    weather_error = str(e)
            payload = {
                "idf": {"input": idf_path, "resolved": idf_resolved, "exists": os.path.exists(idf_resolved)},
                "weather": {
                    "input": weather_file,
                    "resolved": weather_resolved,
                    "exists": bool(weather_resolved and os.path.exists(weather_resolved)),
                    "error": weather_error,
                },
            }
            return json.dumps(payload, indent=2)

        if action == "readiness":
            logger.info(f"model_preflight.readiness: idf={idf_path}, weather={weather_file}")
            issues = []
            verdict = True

            # IDD availability
            idd_path = config.energyplus.idd_path
            idd_ok = bool(idd_path and os.path.exists(idd_path))
            if not idd_ok:
                issues.append(f"IDD not found at configured path: {idd_path}")
                verdict = False

            # IDF resolution
            try:
                idf_resolved = ep_manager._resolve_idf_path(idf_path)
                if not os.path.exists(idf_resolved):
                    issues.append(f"Resolved IDF does not exist: {idf_resolved}")
                    verdict = False
            except Exception as e:
                issues.append(f"Failed to resolve IDF: {str(e)}")
                verdict = False
                idf_resolved = None

            # Weather optional check
            weather_resolved = None
            if weather_file:
                try:
                    weather_resolved = ep_manager._resolve_weather_file_path(weather_file)
                    if not os.path.exists(weather_resolved):
                        issues.append(f"Resolved weather does not exist: {weather_resolved}")
                        verdict = False
                except Exception as e:
                    issues.append(f"Failed to resolve weather file: {str(e)}")
                    verdict = False

            # Validation quick pass
            try:
                validation = ep_manager.validate_idf(idf_path)
                # validation is JSON string from manager; keep as-is but detect error count if present
                validation_obj = json.loads(validation) if isinstance(validation, str) else validation
                err_cnt = validation_obj.get("errors_count") if isinstance(validation_obj, dict) else None
                if isinstance(err_cnt, int) and err_cnt > 0:
                    issues.append(f"Validation errors: {err_cnt}")
                    verdict = False
            except Exception as e:
                issues.append(f"Validation failed: {str(e)}")
                verdict = False

            payload = {
                "verdict": verdict,
                "idf": {"input": idf_path, "resolved": idf_resolved},
                "weather": {"input": weather_file, "resolved": weather_resolved},
                "idd": {"path": idd_path, "exists": idd_ok},
                "issues": issues,
            }
            return json.dumps(payload, indent=2)

        return f"Unsupported action: {action}"

    except FileNotFoundError as e:
        logger.warning(f"File not found in model_preflight: {str(e)}")
        return f"File not found: {str(e)}"
    except Exception as e:
        logger.error(f"model_preflight error: {str(e)}")
        return f"Error in model_preflight: {str(e)}"
async def check_simulation_settings(idf_path: str) -> str:
    """
    Check SimulationControl and RunPeriod settings with information about modifiable fields
    
    Args:
        idf_path: Path to the IDF file
    
    Returns:
        JSON string with current settings and descriptions of modifiable fields
    """
    try:
        logger.info(f"Checking simulation settings: {idf_path}")
        settings = ep_manager.check_simulation_settings(idf_path)
        return f"Simulation settings for {idf_path}:\n{settings}"
    except FileNotFoundError as e:
        logger.warning(f"IDF file not found: {idf_path}")
        return f"File not found: {str(e)}"
    except Exception as e:
        logger.error(f"Error checking simulation settings for {idf_path}: {str(e)}")
        return f"Error checking simulation settings for {idf_path}: {str(e)}"


@expose_inspect_tool()
async def inspect_schedules(idf_path: str, include_values: bool = False) -> str:
    """
    Inspect and inventory all schedule objects in the EnergyPlus model
    
    Args:
        idf_path: Path to the IDF file
        include_values: Whether to extract actual schedule values (default: False)
    
    Returns:
        JSON string with detailed schedule inventory and analysis
    """
    try:
        logger.info(f"Inspecting schedules: {idf_path} (include_values={include_values})")
        schedules_info = ep_manager.inspect_schedules(idf_path, include_values)
        return f"Schedule inspection for {idf_path}:\n{schedules_info}"
    except FileNotFoundError as e:
        logger.warning(f"IDF file not found: {idf_path}")
        return f"File not found: {str(e)}"
    except Exception as e:
        logger.error(f"Error inspecting schedules for {idf_path}: {str(e)}")
        return f"Error inspecting schedules for {idf_path}: {str(e)}"


@expose_inspect_tool()
async def inspect_people(idf_path: str) -> str:
    """
    Inspect and list all People objects in the EnergyPlus model
    
    Args:
        idf_path: Path to the IDF file
    
    Returns:
        JSON string with detailed People objects information including:
        - Name, zone, and schedule associations
        - Calculation method (People, People/Area, Area/Person)
        - Occupancy values and thermal comfort settings
        - Summary statistics by zone and calculation method
    """
    try:
        logger.info(f"Inspecting People objects: {idf_path}")
        result = ep_manager.inspect_people(idf_path)
        return f"People objects inspection for {idf_path}:\n{result}"
    except FileNotFoundError as e:
        logger.warning(f"IDF file not found: {idf_path}")
        return f"File not found: {str(e)}"
    except Exception as e:
        logger.error(f"Error inspecting People objects for {idf_path}: {str(e)}")
        return f"Error inspecting People objects for {idf_path}: {str(e)}"


@expose_modify_tool()
async def modify_people(
    idf_path: str,
    modifications: List[Dict[str, Any]],
    output_path: Optional[str] = None
) -> str:
    """
    Modify People objects in the EnergyPlus model
    
    Args:
        idf_path: Path to the input IDF file
        modifications: List of modification specifications. Each item should contain:
                      - "target": Specifies which People objects to modify
                        - "all": Apply to all People objects
                        - "zone:ZoneName": Apply to People objects in specific zone
                        - "name:PeopleName": Apply to specific People object by name
                      - "field_updates": Dictionary of field names and new values
                        Valid fields include:
                        - Number_of_People_Schedule_Name
                        - Number_of_People_Calculation_Method (People, People/Area, Area/Person)
                        - Number_of_People
                        - People_per_Floor_Area
                        - Floor_Area_per_Person
                        - Fraction_Radiant
                        - Sensible_Heat_Fraction
                        - Activity_Level_Schedule_Name
                        - Carbon_Dioxide_Generation_Rate
                        - Clothing_Insulation_Schedule_Name
                        - Air_Velocity_Schedule_Name
                        - Thermal_Comfort_Model_1_Type
                        - Thermal_Comfort_Model_2_Type
        output_path: Optional path for output file (if None, creates one with _modified suffix)
    
    Returns:
        JSON string with modification results
        
    Examples:
        # Modify all People objects to use 0.1 people/m2
        modify_people("model.idf", [
            {
                "target": "all",
                "field_updates": {
                    "Number_of_People_Calculation_Method": "People/Area",
                    "People_per_Floor_Area": 0.1
                }
            }
        ])
        
        # Modify People objects in specific zone
        modify_people("model.idf", [
            {
                "target": "zone:Office Zone",
                "field_updates": {
                    "Number_of_People": 10,
                    "Activity_Level_Schedule_Name": "Office Activity"
                }
            }
        ])
        
        # Modify specific People object by name
        modify_people("model.idf", [
            {
                "target": "name:Office People",
                "field_updates": {
                    "Fraction_Radiant": 0.3,
                    "Sensible_Heat_Fraction": 0.6
                }
            }
        ])
    """
    try:
        logger.info(f"Modifying People objects: {idf_path}")
        result = ep_manager.modify_people(idf_path, modifications, output_path)
        return f"People modification results:\n{result}"
    except FileNotFoundError as e:
        logger.warning(f"IDF file not found: {idf_path}")
        return f"File not found: {str(e)}"
    except ValueError as e:
        logger.warning(f"Invalid input for modify_people: {str(e)}")
        return f"Invalid input: {str(e)}"
    except Exception as e:
        logger.error(f"Error modifying People objects for {idf_path}: {str(e)}")
        return f"Error modifying People objects for {idf_path}: {str(e)}"


@expose_inspect_tool()
async def inspect_lights(idf_path: str) -> str:
    """
    Inspect and list all Lights objects in the EnergyPlus model
    
    Args:
        idf_path: Path to the IDF file
    
    Returns:
        JSON string with detailed Lights objects information including:
        - Name, zone, and schedule associations
        - Calculation method (LightingLevel, Watts/Area, Watts/Person)
        - Lighting power values and heat fraction settings
        - Summary statistics by zone and calculation method
    """
    try:
        logger.info(f"Inspecting Lights objects: {idf_path}")
        result = ep_manager.inspect_lights(idf_path)
        return f"Lights objects inspection for {idf_path}:\n{result}"
    except FileNotFoundError as e:
        logger.warning(f"IDF file not found: {idf_path}")
        return f"File not found: {str(e)}"
    except Exception as e:
        logger.error(f"Error inspecting Lights objects for {idf_path}: {str(e)}")
        return f"Error inspecting Lights objects for {idf_path}: {str(e)}"


@expose_modify_tool()
async def modify_lights(
    idf_path: str,
    modifications: List[Dict[str, Any]],
    output_path: Optional[str] = None
) -> str:
    """
    Modify Lights objects in the EnergyPlus model
    
    Args:
        idf_path: Path to the input IDF file
        modifications: List of modification specifications. Each item should contain:
                      - "target": Specifies which Lights objects to modify
                        - "all": Apply to all Lights objects
                        - "zone:ZoneName": Apply to Lights objects in specific zone
                        - "name:LightsName": Apply to specific Lights object by name
                      - "field_updates": Dictionary of field names and new values
                        Valid fields include:
                        - Schedule_Name
                        - Design_Level_Calculation_Method (LightingLevel, Watts/Area, Watts/Person)
                        - Lighting_Level
                        - Watts_per_Floor_Area
                        - Watts_per_Person
                        - Return_Air_Fraction
                        - Fraction_Radiant
                        - Fraction_Visible
                        - Fraction_Replaceable
                        - EndUse_Subcategory
                        - Return_Air_Fraction_Calculated_from_Plenum_Temperature
                        - Return_Air_Fraction_Function_of_Plenum_Temperature_Coefficient_1
                        - Return_Air_Fraction_Function_of_Plenum_Temperature_Coefficient_2
                        - Return_Air_Heat_Gain_Node_Name
                        - Exhaust_Air_Heat_Gain_Node_Name
        output_path: Optional path for output file (if None, creates one with _modified suffix)
    
    Returns:
        JSON string with modification results
        
    Examples:
        # Modify all Lights objects to use 10 W/m2
        modify_lights("model.idf", [
            {
                "target": "all",
                "field_updates": {
                    "Design_Level_Calculation_Method": "Watts/Area",
                    "Watts_per_Floor_Area": 10.0
                }
            }
        ])
        
        # Modify Lights objects in specific zone
        modify_lights("model.idf", [
            {
                "target": "zone:Office Zone",
                "field_updates": {
                    "Lighting_Level": 2000,
                    "Schedule_Name": "Office Lighting Schedule"
                }
            }
        ])
        
        # Modify specific Lights object by name
        modify_lights("model.idf", [
            {
                "target": "name:Office Lights",
                "field_updates": {
                    "Fraction_Radiant": 0.42,
                    "Fraction_Visible": 0.18
                }
            }
        ])
    """
    try:
        logger.info(f"Modifying Lights objects: {idf_path}")
        result = ep_manager.modify_lights(idf_path, modifications, output_path)
        return f"Lights modification results:\n{result}"
    except FileNotFoundError as e:
        logger.warning(f"IDF file not found: {idf_path}")
        return f"File not found: {str(e)}"
    except ValueError as e:
        logger.warning(f"Invalid input for modify_lights: {str(e)}")
        return f"Invalid input: {str(e)}"
    except Exception as e:
        logger.error(f"Error modifying Lights objects for {idf_path}: {str(e)}")
        return f"Error modifying Lights objects for {idf_path}: {str(e)}"


@expose_inspect_tool()
async def inspect_electric_equipment(idf_path: str) -> str:
    """
    Inspect and list all ElectricEquipment objects in the EnergyPlus model
    
    Args:
        idf_path: Path to the IDF file
    
    Returns:
        JSON string with detailed ElectricEquipment objects information including:
        - Name, zone, and schedule associations
        - Calculation method (EquipmentLevel, Watts/Area, Watts/Person)
        - Equipment power values and heat fraction settings
        - Summary statistics by zone and calculation method
    """
    try:
        logger.info(f"Inspecting ElectricEquipment objects: {idf_path}")
        result = ep_manager.inspect_electric_equipment(idf_path)
        return f"ElectricEquipment objects inspection for {idf_path}:\n{result}"
    except FileNotFoundError as e:
        logger.warning(f"IDF file not found: {idf_path}")
        return f"File not found: {str(e)}"
    except Exception as e:
        logger.error(f"Error inspecting ElectricEquipment objects for {idf_path}: {str(e)}")
        return f"Error inspecting ElectricEquipment objects for {idf_path}: {str(e)}"


@expose_modify_tool()
async def modify_electric_equipment(
    idf_path: str,
    modifications: List[Dict[str, Any]],
    output_path: Optional[str] = None
) -> str:
    """
    Modify ElectricEquipment objects in the EnergyPlus model
    
    Args:
        idf_path: Path to the input IDF file
        modifications: List of modification specifications. Each item should contain:
                      - "target": Specifies which ElectricEquipment objects to modify
                        - "all": Apply to all ElectricEquipment objects
                        - "zone:ZoneName": Apply to ElectricEquipment objects in specific zone
                        - "name:ElectricEquipmentName": Apply to specific ElectricEquipment object by name
                      - "field_updates": Dictionary of field names and new values
                        Valid fields include:
                        - Schedule_Name
                        - Design_Level_Calculation_Method (EquipmentLevel, Watts/Area, Watts/Person)
                        - Design_Level
                        - Watts_per_Floor_Area
                        - Watts_per_Person
                        - Fraction_Latent
                        - Fraction_Radiant
                        - Fraction_Lost
                        - EndUse_Subcategory
        output_path: Optional path for output file (if None, creates one with _modified suffix)
    
    Returns:
        JSON string with modification results
        
    Examples:
        # Modify all ElectricEquipment objects to use 15 W/m2
        modify_electric_equipment("model.idf", [
            {
                "target": "all",
                "field_updates": {
                    "Design_Level_Calculation_Method": "Watts/Area",
                    "Watts_per_Floor_Area": 15.0
                }
            }
        ])
        
        # Modify ElectricEquipment objects in specific zone
        modify_electric_equipment("model.idf", [
            {
                "target": "zone:Office Zone",
                "field_updates": {
                    "Design_Level": 3000,
                    "Schedule_Name": "Office Equipment Schedule"
                }
            }
        ])
        
        # Modify specific ElectricEquipment object by name
        modify_electric_equipment("model.idf", [
            {
                "target": "name:Office Equipment",
                "field_updates": {
                    "Fraction_Radiant": 0.3,
                    "Fraction_Latent": 0.1
                }
            }
        ])
    """
    try:
        logger.info(f"Modifying ElectricEquipment objects: {idf_path}")
        result = ep_manager.modify_electric_equipment(idf_path, modifications, output_path)
        return f"ElectricEquipment modification results:\n{result}"
    except FileNotFoundError as e:
        logger.warning(f"IDF file not found: {idf_path}")
        return f"File not found: {str(e)}"
    except ValueError as e:
        logger.warning(f"Invalid input for modify_electric_equipment: {str(e)}")
        return f"Invalid input: {str(e)}"
    except Exception as e:
        logger.error(f"Error modifying ElectricEquipment objects for {idf_path}: {str(e)}")
        return f"Error modifying ElectricEquipment objects for {idf_path}: {str(e)}"


@expose_sim_tool()
async def modify_simulation_control(
    idf_path: str, 
    field_updates: Dict[str, Any],  # Changed from str to Dict[str, Any]
    output_path: Optional[str] = None
) -> str:
    """
    Modify SimulationControl settings and save to a new file
    
    Args:
        idf_path: Path to the input IDF file
        field_updates: Dictionary with field names and new values (e.g., {"Run_Simulation_for_Weather_File_Run_Periods": "Yes"})
        output_path: Optional path for output file (if None, creates one with _modified suffix)
    
    Returns:
        JSON string with modification results
    """
    try:
        logger.info(f"Modifying SimulationControl (wrapper): {idf_path}")
        result = await simulation_manager(
            action="update_settings",
            idf_path=idf_path,
            settings=field_updates,
        )
        return result
    except FileNotFoundError as e:
        logger.warning(f"IDF file not found: {idf_path}")
        return f"File not found: {str(e)}"
    except Exception as e:
        logger.error(f"Error modifying SimulationControl for {idf_path}: {str(e)}")
        return f"Error modifying SimulationControl for {idf_path}: {str(e)}"


@expose_sim_tool()
async def modify_run_period(
    idf_path: str, 
    field_updates: Dict[str, Any],  # Changed from str to Dict[str, Any]
    run_period_index: int = 0,
    output_path: Optional[str] = None
) -> str:
    """
    Modify RunPeriod settings and save to a new file
    
    Args:
        idf_path: Path to the input IDF file
        field_updates: Dictionary with field names and new values (e.g., {"Begin_Month": 1, "End_Month": 3})
        run_period_index: Index of RunPeriod to modify (default 0 for first RunPeriod)
        output_path: Optional path for output file (if None, creates one with _modified suffix)
    
    Returns:
        JSON string with modification results
    """
    try:
        logger.info(f"Modifying RunPeriod (wrapper): {idf_path}")
        result = await simulation_manager(
            action="update_run_period",
            idf_path=idf_path,
            run_period=field_updates,
            run_period_index=run_period_index,
        )
        return result
    except FileNotFoundError as e:
        logger.warning(f"IDF file not found: {idf_path}")
        return f"File not found: {str(e)}"
    except Exception as e:
        logger.error(f"Error modifying RunPeriod for {idf_path}: {str(e)}")
        return f"Error modifying RunPeriod for {idf_path}: {str(e)}"


@expose_modify_tool()
async def change_infiltration_by_mult(
    idf_path: str, 
    mult: float,
    output_path: Optional[str] = None
) -> str:
    """
    Modify infiltration in ZoneInfiltration:DesignFlowRate and save to a new file
    
    Args:
        idf_path: Path to the input IDF file
        mult: Multiplicative factor to apply to all ZoneInfiltration:DesignFlowRate objects
        output_path: Optional path for output file (if None, creates one with _modified suffix)
    
    Returns:
        JSON string with modification results
    """
    try:
        logger.info(f"Modifying Infiltration: {idf_path}")
        
        # No need to parse JSON since we're receiving a dict directly
        result = ep_manager.change_infiltration_by_mult(
            idf_path=idf_path,
            mult=mult,  # Pass the float directly
            output_path=output_path
        )
        return f"Infiltration modification results:\n{result}"
    except FileNotFoundError as e:
        logger.warning(f"IDF file not found: {idf_path}")
        return f"File not found: {str(e)}"
    except Exception as e:
        logger.error(f"Error Infiltration modification for {idf_path}: {str(e)}")
        return f"Error Infiltration modification for {idf_path}: {str(e)}"


@expose_modify_tool()
async def add_window_film_outside(
    idf_path: str,
    u_value: float = 4.94,
    shgc: float = 0.45,
    visible_transmittance: float = 0.66,
    output_path: Optional[str] = None
) -> str:
    """
    Add exterior window film to all exterior windows using WindowMaterial:SimpleGlazingSystem
    
    Args:
        idf_path: Path to the input IDF file
        u_value: U-value of the window film (default: 4.94 W/m²·K from CBES)
        shgc: Solar Heat Gain Coefficient of the window film (default: 0.45)
        visible_transmittance: Visible transmittance of the window film (default: 0.66)
        output_path: Optional path for output file (if None, creates one with _modified suffix)
    
    Returns:
        JSON string with modification results
    """
    try:
        logger.info(f"Adding window film to exterior windows: {idf_path}")
        result = ep_manager.add_window_film_outside(
            idf_path=idf_path,
            u_value=u_value,
            shgc=shgc,
            visible_transmittance=visible_transmittance,
            output_path=output_path
        )
        return f"Window film modification results:\n{result}"
    except FileNotFoundError as e:
        logger.warning(f"IDF file not found: {idf_path}")
        return f"File not found: {str(e)}"
    except Exception as e:
        logger.error(f"Error adding window film for {idf_path}: {str(e)}")
        return f"Error adding window film for {idf_path}: {str(e)}"


@expose_modify_tool()
async def add_coating_outside(
    idf_path: str,
    location: str,
    solar_abs: float = 0.4,
    thermal_abs: float = 0.9,
    output_path: Optional[str] = None
) -> str:
    """
    Add exterior coating to all exterior surfaces of the specified location (wall or roof)
    
    Args:
        idf_path: Path to the input IDF file
        location: Surface type - either "wall" or "roof"
        solar_abs: Solar Absorptance of the exterior coating (default: 0.4)
        thermal_abs: Thermal Absorptance of the exterior coating (default: 0.9)
        output_path: Optional path for output file (if None, creates one with _modified suffix)
    
    Returns:
        JSON string with modification results
    """
    try:
        logger.info(f"Adding exterior coating to {location} surfaces: {idf_path}")
        result = ep_manager.add_coating_outside(
            idf_path=idf_path,
            location=location,
            solar_abs=solar_abs,
            thermal_abs=thermal_abs,
            output_path=output_path
        )
        return f"Exterior coating modification results:\n{result}"
    except FileNotFoundError as e:
        logger.warning(f"IDF file not found: {idf_path}")
        return f"File not found: {str(e)}"
    except ValueError as e:
        logger.warning(f"Invalid location parameter: {location}")
        return f"Invalid location (must be 'wall' or 'roof'): {str(e)}"
    except Exception as e:
        logger.error(f"Error adding exterior coating for {idf_path}: {str(e)}")
        return f"Error adding exterior coating for {idf_path}: {str(e)}"


@expose_inspect_tool()
async def list_zones(idf_path: str) -> str:
    """
    List all zones in the EnergyPlus model
    
    Args:
        idf_path: Path to the IDF file
    
    Returns:
        JSON string with detailed zone information
    """
    try:
        logger.info(f"Listing zones: {idf_path}")
        zones = ep_manager.list_zones(idf_path)
        return f"Zones in {idf_path}:\n{zones}"
    except FileNotFoundError as e:
        logger.warning(f"IDF file not found: {idf_path}")
        return f"File not found: {str(e)}"
    except Exception as e:
        logger.error(f"Error listing zones for {idf_path}: {str(e)}")
        return f"Error listing zones for {idf_path}: {str(e)}"


@expose_inspect_tool()
async def get_surfaces(idf_path: str) -> str:
    """
    Get detailed surface information from the EnergyPlus model
    
    Args:
        idf_path: Path to the IDF file
    
    Returns:
        JSON string with surface details
    """
    try:
        logger.info(f"Getting surfaces: {idf_path}")
        surfaces = ep_manager.get_surfaces(idf_path)
        return f"Surfaces in {idf_path}:\n{surfaces}"
    except FileNotFoundError as e:
        logger.warning(f"IDF file not found: {idf_path}")
        return f"File not found: {str(e)}"
    except Exception as e:
        logger.error(f"Error getting surfaces for {idf_path}: {str(e)}")
        return f"Error getting surfaces for {idf_path}: {str(e)}"

@expose_inspect_tool()
async def get_materials(idf_path: str) -> str:
    """
    Get material information from the EnergyPlus model
    
    Args:
        idf_path: Path to the IDF file
    
    Returns:
        JSON string with material details
    """
    try:
        logger.info(f"Getting materials: {idf_path}")
        materials = ep_manager.get_materials(idf_path)
        return f"Materials in {idf_path}:\n{materials}"
    except FileNotFoundError as e:
        logger.warning(f"IDF file not found: {idf_path}")
        return f"File not found: {str(e)}"
    except Exception as e:
        logger.error(f"Error getting materials for {idf_path}: {str(e)}")
        return f"Error getting materials for {idf_path}: {str(e)}"


@expose_model_tool()
async def validate_idf(idf_path: str) -> str:
    """
    Validate an EnergyPlus IDF file and return validation results
    
    Args:
        idf_path: Path to the IDF file
    
    Returns:
        JSON string with validation results, warnings, and errors
    """
    # Thin wrapper -> model_preflight(action="validate")
    return await model_preflight(action="validate", idf_path=idf_path)


@expose_master_tool()
async def get_outputs(
    idf_path: str,
    type: str = "variables",
    discover_available: bool = False,
    run_days: int = 1,
) -> str:
    """
    Unified outputs accessor for variables/meters.

    Args:
        idf_path: Path to the IDF file.
        type: One of "variables", "meters", or "both".
        discover_available: If true, runs a short sim to discover available signals.
        run_days: Number of days for discovery simulation (if enabled).

    Returns:
        JSON string with keys: {"variables": ..., "meters": ...} depending on `type`.
    """
    try:
        logger.info(f"Getting outputs: {idf_path} (type={type}, discover_available={discover_available})")
        kind = (type or "variables").lower()
        if kind not in ("variables", "meters", "both"):
            msg = "Invalid type. Use 'variables', 'meters', or 'both'."
            logger.warning(msg)
            return json.dumps({"error": msg, "allowed": ["variables", "meters", "both"]}, indent=2)

        payload: Dict[str, Any] = {}
        if kind in ("variables", "both"):
            try:
                payload["variables"] = ep_manager.get_output_variables(idf_path, discover_available, run_days)
            except Exception as e:
                logger.error(f"Variables retrieval failed: {e}")
                payload.setdefault("errors", {})["variables"] = str(e)
        if kind in ("meters", "both"):
            try:
                payload["meters"] = ep_manager.get_output_meters(idf_path, discover_available, run_days)
            except Exception as e:
                logger.error(f"Meters retrieval failed: {e}")
                payload.setdefault("errors", {})["meters"] = str(e)

        return json.dumps({"idf_path": idf_path, **payload}, indent=2)
    except FileNotFoundError as e:
        logger.warning(f"IDF file not found: {idf_path}")
        return f"File not found: {str(e)}"
    except Exception as e:
        logger.error(f"Error getting outputs for {idf_path}: {str(e)}")
        return f"Error getting outputs for {idf_path}: {str(e)}"


@expose_output_tool()
async def get_output_variables(idf_path: str, discover_available: bool = False, run_days: int = 1) -> str:
    """
    Get output variables from the model - either configured variables or discover all available ones
    
    Args:
        idf_path: Path to the IDF file (can be absolute, relative, or just filename for sample files)
        discover_available: If True, runs a short simulation to discover all available variables. 
                          If False, returns currently configured variables in the IDF (default: False)
        run_days: Number of days to run for discovery simulation (default: 1, only used if discover_available=True)
    
    Returns:
        JSON string with output variables information. When discover_available=True, includes
        all possible variables with units, frequencies, and ready-to-use Output:Variable lines.
        When discover_available=False, shows only currently configured Output:Variable and Output:Meter objects.
    """
    try:
        logger.info(f"Getting output variables: {idf_path} (discover_available={discover_available})")
        result = ep_manager.get_output_variables(idf_path, discover_available, run_days)
        
        mode = "available variables discovery" if discover_available else "configured variables"
        return f"Output variables ({mode}) for {idf_path}:\n{result}"
        
    except FileNotFoundError as e:
        logger.warning(f"IDF file not found: {idf_path}")
        return f"File not found: {str(e)}"
    except Exception as e:
        logger.error(f"Error getting output variables for {idf_path}: {str(e)}")
        return f"Error getting output variables for {idf_path}: {str(e)}"


@expose_output_tool()
async def get_output_meters(idf_path: str, discover_available: bool = False, run_days: int = 1) -> str:
    """
    Get output meters from the model - either configured meters or discover all available ones
    
    Args:
        idf_path: Path to the IDF file (can be absolute, relative, or just filename for sample files)
        discover_available: If True, runs a short simulation to discover all available meters.
                          If False, returns currently configured meters in the IDF (default: False)
        run_days: Number of days to run for discovery simulation (default: 1, only used if discover_available=True)
    
    Returns:
        JSON string with meter information. When discover_available=True, includes
        all possible meters with units, frequencies, and ready-to-use Output:Meter lines.
        When discover_available=False, shows only currently configured Output:Meter objects.
    """
    try:
        logger.info(f"Getting output meters: {idf_path} (discover_available={discover_available})")
        result = ep_manager.get_output_meters(idf_path, discover_available, run_days)
        
        mode = "available meters discovery" if discover_available else "configured meters"
        return f"Output meters ({mode}) for {idf_path}:\n{result}"
        
    except FileNotFoundError as e:
        logger.warning(f"IDF file not found: {idf_path}")
        return f"File not found: {str(e)}"
    except Exception as e:
        logger.error(f"Error getting output meters for {idf_path}: {str(e)}")
        return f"Error getting output meters for {idf_path}: {str(e)}"


@expose_modify_tool()
async def add_output_variables(
    idf_path: str,
    variables: List,  # Can be List[Dict], List[str], or mixed
    validation_level: str = "moderate",
    allow_duplicates: bool = False,
    output_path: Optional[str] = None
) -> str:
    """
    Add output variables to an EnergyPlus IDF file with intelligent validation
    
    Args:
        idf_path: Path to the input IDF file (can be absolute, relative, or filename for sample files)
        variables: List of variable specifications. Can be:
                  - Simple strings: ["Zone Air Temperature", "Surface Inside Face Temperature"] 
                  - [name, frequency] pairs: [["Zone Air Temperature", "hourly"], ["Surface Temperature", "daily"]]
                  - Full specifications: [{"key_value": "*", "variable_name": "Zone Air Temperature", "frequency": "hourly"}]
                  - Mixed formats in the same list
        validation_level: Validation strictness level:
                         - "strict": Full validation with model checking (recommended for beginners)
                         - "moderate": Basic validation with helpful warnings (default)
                         - "lenient": Minimal validation (for advanced users)
        allow_duplicates: Whether to allow duplicate output variable specifications (default: False)
        output_path: Optional path for output file (if None, creates one with _with_outputs suffix)
    
    Returns:
        JSON string with detailed results including validation report, added variables, and performance metrics
        
    Examples:
        # Simple usage
        add_output_variables("model.idf", ["Zone Air Temperature", "Zone Air Relative Humidity"])
        
        # With custom frequencies  
        add_output_variables("model.idf", [["Zone Air Temperature", "daily"], ["Surface Temperature", "hourly"]])
        
        # Full control
        add_output_variables("model.idf", [
            {"key_value": "Zone1", "variable_name": "Zone Air Temperature", "frequency": "hourly"},
            {"key_value": "*", "variable_name": "Surface Inside Face Temperature", "frequency": "daily"}
        ], validation_level="strict")
    """
    try:
        logger.info(f"Adding output variables: {idf_path} ({len(variables)} variables, {validation_level} validation)")
        
        result = ep_manager.add_output_variables(
            idf_path=idf_path,
            variables=variables,
            validation_level=validation_level,
            allow_duplicates=allow_duplicates,
            output_path=output_path
        )
        
        return f"Output variables addition results:\n{result}"
        
    except FileNotFoundError as e:
        logger.warning(f"IDF file not found: {idf_path}")
        return f"File not found: {str(e)}"
    except ValueError as e:
        logger.warning(f"Invalid arguments for add_output_variables: {str(e)}")
        return f"Invalid arguments: {str(e)}"
    except Exception as e:
        logger.error(f"Error adding output variables: {str(e)}")
        return f"Error adding output variables: {str(e)}"


@expose_modify_tool()
async def add_output_meters(
    idf_path: str,
    meters: List,  # Can be List[Dict], List[str], or mixed
    validation_level: str = "moderate",
    allow_duplicates: bool = False,
    output_path: Optional[str] = None
) -> str:
    """
    Add output meters to an EnergyPlus IDF file with intelligent validation
    
    Args:
        idf_path: Path to the input IDF file (can be absolute, relative, or filename for sample files)
        meters: List of meter specifications. Can be:
               - Simple strings: ["Electricity:Facility", "NaturalGas:Facility"] 
               - [name, frequency] pairs: [["Electricity:Facility", "hourly"], ["NaturalGas:Facility", "daily"]]
               - [name, frequency, type] triplets: [["Electricity:Facility", "hourly", "Output:Meter"]]
               - Full specifications: [{"meter_name": "Electricity:Facility", "frequency": "hourly", "meter_type": "Output:Meter"}]
               - Mixed formats in the same list
        validation_level: Validation strictness level:
                         - "strict": Full validation with model checking (recommended for beginners)
                         - "moderate": Basic validation with helpful warnings (default)
                         - "lenient": Minimal validation (for advanced users)
        allow_duplicates: Whether to allow duplicate output meter specifications (default: False)
        output_path: Optional path for output file (if None, creates one with _with_meters suffix)
    
    Returns:
        JSON string with detailed results including validation report, added meters, and performance metrics
        
    Examples:
        # Simple usage
        add_output_meters("model.idf", ["Electricity:Facility", "NaturalGas:Facility"])
        
        # With custom frequencies  
        add_output_meters("model.idf", [["Electricity:Facility", "daily"], ["NaturalGas:Facility", "hourly"]])
        
        # Full control with meter types
        add_output_meters("model.idf", [
            {"meter_name": "Electricity:Facility", "frequency": "hourly", "meter_type": "Output:Meter"},
            {"meter_name": "NaturalGas:Facility", "frequency": "daily", "meter_type": "Output:Meter:Cumulative"}
        ], validation_level="strict")
    """
    try:
        logger.info(f"Adding output meters: {idf_path} ({len(meters)} meters, {validation_level} validation)")
        
        result = ep_manager.add_output_meters(
            idf_path=idf_path,
            meters=meters,
            validation_level=validation_level,
            allow_duplicates=allow_duplicates,
            output_path=output_path
        )
        
        return f"Output meters addition results:\n{result}"
        
    except FileNotFoundError as e:
        logger.warning(f"IDF file not found: {idf_path}")
        return f"File not found: {str(e)}"
    except ValueError as e:
        logger.warning(f"Invalid arguments for add_output_meters: {str(e)}")
        return f"Invalid arguments: {str(e)}"
    except Exception as e:
        logger.error(f"Error adding output meters: {str(e)}")
        return f"Error adding output meters: {str(e)}"


@expose_file_tool()
async def list_available_files(
    include_example_files: bool = False,
    include_weather_data: bool = False
) -> str:
    """
    List available files in specified directories
    
    Args:
        include_example_files: Whether to include EnergyPlus example files directory (default: False)
        include_weather_data: Whether to include EnergyPlus weather data directory (default: False)
    
    Returns:
        JSON string with available files organized by source and type. Always includes sample_files directory.
    """
    try:
        logger.info(f"Listing available files (legacy wrapper)")
        return await file_utils(action="list", include_example_files=include_example_files, include_weather_data=include_weather_data)
    except Exception as e:
        logger.error(f"Error listing available files: {str(e)}")
        return f"Error listing available files: {str(e)}"


@expose_server_tool()
async def get_server_configuration() -> str:
    """
    Get current server configuration information
    
    Returns:
        JSON string with configuration details
    """
    try:
        # Delegate to unified housekeeping tool with detailed config
        return await server_manager(action="status", include_config=True, detail="detailed")
    except Exception as e:
        logger.error(f"Error getting configuration: {str(e)}")
        return f"Error getting configuration: {str(e)}"


@expose_server_tool()
async def get_server_status() -> str:
    """
    Get current server status and health information
    
    Returns:
        JSON string with server status
    """
    try:
        # Delegate to unified tool
        return await server_manager(action="status")
        
    except Exception as e:
        logger.error(f"Error getting server status: {str(e)}")
        return f"Error getting server status: {str(e)}"


@expose_hvac_tool()
async def discover_hvac_loops(idf_path: str) -> str:
    """
    Discover all HVAC loops (Plant, Condenser, Air) in the EnergyPlus model
    
    Args:
        idf_path: Path to the IDF file
    
    Returns:
        JSON string with all HVAC loops found, organized by type
    """
    try:
        logger.info(f"Discovering HVAC loops (wrapper): {idf_path}")
        return await hvac_loop_inspect(idf_path=idf_path, action="discover", types="all")
    except FileNotFoundError as e:
        logger.warning(f"IDF file not found: {idf_path}")
        return f"File not found: {str(e)}"
    except Exception as e:
        logger.error(f"Error discovering HVAC loops for {idf_path}: {str(e)}")
        return f"Error discovering HVAC loops for {idf_path}: {str(e)}"


@expose_hvac_tool()
async def get_loop_topology(idf_path: str, loop_name: str) -> str:
    """
    Get detailed topology information for a specific HVAC loop
    
    Args:
        idf_path: Path to the IDF file
        loop_name: Name of the specific loop to analyze
    
    Returns:
        JSON string with detailed loop topology including supply/demand sides, branches, and components
    """
    try:
        logger.info(f"Getting loop topology (wrapper) for '{loop_name}': {idf_path}")
        return await hvac_loop_inspect(idf_path=idf_path, action="topology", loop_name=loop_name)
    except FileNotFoundError as e:
        logger.warning(f"IDF file not found: {idf_path}")
        return f"File not found: {str(e)}"
    except ValueError as e:
        logger.warning(f"Loop not found: {loop_name}")
        return f"Loop not found: {str(e)}"
    except Exception as e:
        logger.error(f"Error getting loop topology for {idf_path}: {str(e)}")
        return f"Error getting loop topology for {idf_path}: {str(e)}"


@expose_hvac_tool()
async def visualize_loop_diagram(
    idf_path: str, 
    loop_name: Optional[str] = None,
    output_path: Optional[str] = None,
    format: str = "png",
    show_legend: bool = True
) -> str:
    """
    Generate and save a visual diagram of HVAC loop(s)
    
    Args:
        idf_path: Path to the IDF file
        loop_name: Optional specific loop name (if None, shows all loops)
        output_path: Optional custom output path (if None, creates one automatically)
        format: Image format for the diagram (png, jpg, pdf, svg)
        show_legend: Whether to include a legend in the diagram (default: True)
    
    Returns:
        JSON string with diagram generation results and file path
    """
    try:
        logger.info(f"Creating loop diagram (wrapper) for '{loop_name or 'all loops'}': {idf_path} (show_legend={show_legend})")
        # Delegate to unified tool for consistency
        # Here we call the manager directly to preserve return shape, but keep wrapper gated
        result = ep_manager.visualize_loop_diagram(idf_path, loop_name, output_path, format, show_legend)
        return f"Loop diagram created:\n{result}"
    except FileNotFoundError as e:
        logger.warning(f"IDF file not found: {idf_path}")
        return f"File not found: {str(e)}"
    except Exception as e:
        logger.error(f"Error creating loop diagram for {idf_path}: {str(e)}")
        return f"Error creating loop diagram for {idf_path}: {str(e)}"


@expose_master_tool()
async def simulation_manager(
    action: Literal["run", "update_settings", "update_run_period", "status", "capabilities"],
    idf_path: Optional[str] = None,
    # Run args
    weather_file: Optional[str] = None,
    output_directory: Optional[str] = None,
    annual: bool = True,
    design_day: bool = False,
    readvars: bool = True,
    expandobjects: bool = True,
    # Update settings args
    settings: Optional[Dict[str, Any]] = None,
    # Update run period args
    run_period: Optional[Dict[str, Any]] = None,
    run_period_index: int = 0,
    # Status/capabilities
    run_id: Optional[str] = None,
    detail: Literal["summary", "detailed"] = "summary",
) -> str:
    """
    Manage simulation execution and configuration in one place.

    Args:
        action: One of "run", "update_settings", "update_run_period", "status", "capabilities".
        idf_path: Path to the IDF file (required for all except pure capabilities).

        For action="run":
          - weather_file: Path or city name, optional
          - output_directory: Where to write results (auto if omitted)
          - annual, design_day, readvars, expandobjects: Standard flags

        For action="update_settings":
          - settings: Dict of SimulationControl fields to update

        For action="update_run_period":
          - run_period: Dict of RunPeriod fields to update
          - run_period_index: Which RunPeriod to modify (default 0)

        For action="status":
          - run_id: Optional placeholder for future async support

        For action="capabilities":
          - detail: "summary" or "detailed"

    Returns:
        JSON string describing result for the requested action.
    """
    try:
        if action == "capabilities":
            payload = {
                "tool": "simulation_manager",
                "actions": [
                    {
                        "name": "run",
                        "required": ["idf_path"],
                        "optional": [
                            "weather_file", "output_directory", "annual",
                            "design_day", "readvars", "expandobjects"
                        ],
                    },
                    {
                        "name": "update_settings",
                        "required": ["idf_path", "settings"],
                        "notes": "Updates SimulationControl fields",
                    },
                    {
                        "name": "update_run_period",
                        "required": ["idf_path", "run_period"],
                        "optional": ["run_period_index"],
                        "notes": "Updates RunPeriod fields",
                    },
                    {
                        "name": "status",
                        "optional": ["run_id"],
                        "notes": "Synchronous server; returns static status for now",
                    },
                ],
                "detail": detail,
            }
            return json.dumps(payload, indent=2)

        if action == "run":
            if not idf_path:
                return "Missing required parameter: idf_path"
            logger.info(f"simulation_manager.run: {idf_path}")
            if weather_file:
                logger.info(f"With weather file: {weather_file}")
            result = ep_manager.run_simulation(
                idf_path=idf_path,
                weather_file=weather_file,
                output_directory=output_directory,
                annual=annual,
                design_day=design_day,
                readvars=readvars,
                expandobjects=expandobjects,
            )
            return f"Simulation run complete:\n{result}"

        if action == "update_settings":
            if not idf_path:
                return "Missing required parameter: idf_path"
            if not isinstance(settings, dict) or not settings:
                return "Missing required parameter: settings (dict)"
            logger.info(f"simulation_manager.update_settings: {idf_path}")
            result = ep_manager.modify_simulation_settings(
                idf_path=idf_path,
                object_type="SimulationControl",
                field_updates=settings,
                output_path=None,
            )
            return f"SimulationControl updated:\n{result}"

        if action == "update_run_period":
            if not idf_path:
                return "Missing required parameter: idf_path"
            if not isinstance(run_period, dict) or not run_period:
                return "Missing required parameter: run_period (dict)"
            logger.info(f"simulation_manager.update_run_period: {idf_path} idx={run_period_index}")
            result = ep_manager.modify_simulation_settings(
                idf_path=idf_path,
                object_type="RunPeriod",
                field_updates=run_period,
                run_period_index=int(run_period_index or 0),
                output_path=None,
            )
            return f"RunPeriod updated:\n{result}"

        if action == "status":
            payload = {
                "run_id": run_id or None,
                "mode": "synchronous",
                "queueing": False,
                "message": "Runs execute synchronously; inspect output_directory from 'run' result.",
            }
            return json.dumps(payload, indent=2)

        return f"Unsupported action: {action}"

    except FileNotFoundError as e:
        logger.warning(f"File not found in simulation_manager: {str(e)}")
        return f"File not found: {str(e)}"
    except Exception as e:
        logger.error(f"simulation_manager error: {str(e)}")
        return f"Error in simulation_manager: {str(e)}"


# --- Post-processing (unified) ---
@expose_master_tool()
async def post_processing(
    action: Literal["interactive_plot", "capabilities"],
    output_directory: Optional[str] = None,
    idf_name: Optional[str] = None,
    file_type: Literal["auto", "meter", "variable"] = "auto",
    custom_title: Optional[str] = None,
) -> str:
    """
    Unified post-processing entry point.

    - interactive_plot: Create interactive HTML plot from time-series outputs
    - capabilities: Enumerate supported actions and parameters
    """
    try:
        if action == "capabilities":
            return json.dumps({
                "tool": "post_processing",
                "actions": [
                    {
                        "name": "interactive_plot",
                        "required": ["output_directory"],
                        "optional": ["idf_name", "file_type", "custom_title"],
                    }
                ]
            }, indent=2)

        if action == "interactive_plot":
            if not output_directory:
                return "Missing required parameter: output_directory"
            logger.info(f"post_processing.interactive_plot from: {output_directory}")
            result = ep_manager.create_interactive_plot(output_directory, idf_name, file_type, custom_title)
            return f"Interactive plot created:\n{result}"

        return f"Unsupported action: {action}"
    except FileNotFoundError as e:
        logger.warning(f"Post-processing file not found: {str(e)}")
        return f"Files not found: {str(e)}"
    except Exception as e:
        logger.error(f"post_processing error: {str(e)}")
        return f"Error in post_processing: {str(e)}"


# --- Simulation wrappers (optional exposure) ---
@expose_sim_tool()
async def run_simulation(
    idf_path: str,
    weather_file: Optional[str] = None,
    output_directory: Optional[str] = None,
    annual: bool = True,
    design_day: bool = False,
    readvars: bool = True,
    expandobjects: bool = True,
) -> str:
    return json.dumps({"error": "run_simulation wrapper removed; use simulation_manager(action='run')"}, indent=2)


@expose_sim_tool()
async def run_energyplus_simulation(
    idf_path: str,
    weather_file: Optional[str] = None,
    output_directory: Optional[str] = None,
    annual: bool = True,
    design_day: bool = False,
    readvars: bool = True,
    expandobjects: bool = True,
) -> str:
    return json.dumps({"error": "Deprecated; use simulation_manager(action='run')"}, indent=2)


@expose_post_tool()
async def create_interactive_plot(
    output_directory: str,
    idf_name: Optional[str] = None,
    file_type: str = "auto",
    custom_title: Optional[str] = None
) -> str:
    """Deprecated wrapper. Prefer post_processing(action="interactive_plot")."""
    return json.dumps({"error": "create_interactive_plot wrapper removed; use post_processing(action='interactive_plot')"}, indent=2)


@expose_server_tool()
async def get_server_logs(lines: int = 50) -> str:
    """
    Get recent server log entries
    
    Args:
        lines: Number of recent log lines to return (default 50)
    
    Returns:
        Recent log entries as text
    """
    return json.dumps({"error": "get_server_logs wrapper removed; use server_manager(action='logs')"}, indent=2)


@expose_server_tool()
async def get_error_logs(lines: int = 20) -> str:
    """
    Get recent error log entries
    
    Args:
        lines: Number of recent error lines to return (default 20)
    
    Returns:
        Recent error log entries as text
    """
    return json.dumps({"error": "get_error_logs wrapper removed; use server_manager(action='logs', type='error')"}, indent=2)


@expose_server_tool()
async def clear_logs() -> str:
    """
    Clear/rotate current log files (creates backup)
    
    Returns:
        Status of log clearing operation
    """
    return json.dumps({"error": "clear_logs wrapper removed; use server_manager(action='clear_logs')"}, indent=2)


if __name__ == "__main__":
    logger.info(f"Starting {config.server.name} v{config.server.version}")
    logger.info(f"EnergyPlus version: {config.energyplus.version}")
    logger.info(f"Sample files path: {config.paths.sample_files_path}")
    
    try:
        # Use FastMCP's built-in run method with stdio transport
        mcp.run(transport="stdio")
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    except Exception as e:
        logger.error(f"Server error: {str(e)}")
        raise
    finally:
        logger.info("Server stopped")
