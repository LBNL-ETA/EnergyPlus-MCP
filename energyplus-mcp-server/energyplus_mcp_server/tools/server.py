from typing import Any, Dict, List, Optional, Literal
import json
from pathlib import Path
from datetime import datetime
import os

from energyplus_mcp_server.scope import ScopeError, require_admin
from energyplus_mcp_server.utils.tool_threads import eppy_free

STARTUP_TIME: datetime  # imported from boot module if needed


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    @mcp.tool()
    @eppy_free
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
        """Server status, logs, and log rotation.

        Actions and the parameters each one uses:
        - status: server, EnergyPlus, and log-file status. include_config=True
          with detail="detailed" adds the full server configuration.
        - logs: recent log lines. type picks the server log, the error log, or
          both; lines, contains, and since (ISO datetime) filter the output;
          format is "summary" or "raw".
        - clear_logs: rotate log files to timestamped backups. select picks
          which logs; mode="dry_run" (default) only previews, mode="apply"
          rotates.

        Over the HTTP transport, logs, clear_logs, and status with the full
        configuration require a token listed in MCP_ADMIN_LABELS. Stdio callers
        are always allowed.
        """
        log_dir = Path(config.paths.workspace_root) / "logs"
        now = datetime.utcnow().isoformat()

        # Logs and configuration are server-wide, so over HTTP they can expose
        # other users' paths and errors. Check per action: plain status stays
        # open to every token.
        admin_operation = None
        if action in ("logs", "clear_logs"):
            admin_operation = f"server_manager action '{action}'"
        elif action == "status" and include_config and detail == "detailed":
            admin_operation = "server_manager status with include_config"
        if admin_operation:
            try:
                require_admin(config, admin_operation)
            except ScopeError as e:
                return json.dumps({"meta": {"action": action, "timestamp": now}, "error": str(e)}, indent=2)

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
                uptime_seconds = int((datetime.utcnow() - STARTUP_TIME).total_seconds()) if 'STARTUP_TIME' in globals() else None
                import sys, platform
                data = {
                    "server": {
                        "name": config.server.name,
                        "version": config.server.version,
                        "log_level": config.server.log_level,
                        "startup_time": STARTUP_TIME.isoformat() if uptime_seconds is not None else None,
                        "uptime_seconds": uptime_seconds,
                        "debug_mode": config.debug_mode,
                    },
                    "system": {"python_version": sys.version, "platform": platform.platform(), "architecture": platform.architecture()[0]},
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

                def _parse_line_ts(line: str):
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
                    if p.exists():
                        with open(p, "r", errors="ignore") as f:
                            lines_buf = f.readlines()[-max(1, lines):]
                            if contains:
                                lines_buf = [ln for ln in lines_buf if contains in ln]
                            if since_dt:
                                lines_buf = [ln for ln in lines_buf if (_parse_line_ts(ln) or datetime.min) >= since_dt]
                            content_parts.append("".join(lines_buf))
                data = {"files": files_meta, "showing": {"type": type, "lines": lines, "filtered_contains": contains or None, "since": since}, "truncated": truncated}
                if content_parts:
                    data["content"] = "\n\n".join(content_parts)
                return json.dumps({"meta": {"action": action, "detail": format, "timestamp": now}, "data": data}, indent=2)
            except Exception as e:
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
                    return json.dumps({"meta": {"action": action, "mode": mode, "timestamp": now}, "data": {"will_rotate": plan, "backup_dir": str(log_dir)}}, indent=2)
                rotated = []
                for item in plan:
                    src = Path(item["from"])
                    dst = Path(item["to"])
                    try:
                        if src.exists():
                            src.rename(dst)
                            rotated.append({"from": str(src), "to": str(dst)})
                    except Exception:
                        pass
                return json.dumps({"meta": {"action": action, "mode": mode, "timestamp": now}, "data": {"rotated": rotated, "backup_dir": str(log_dir), "message": "Log files rotated"}}, indent=2)
            except Exception as e:
                return f"Error clearing logs: {str(e)}"

        return json.dumps({"error": f"Unknown action '{action}'"}, indent=2)

