from typing import Any, Dict, List, Optional, Literal
import json
from pathlib import Path
from datetime import datetime
import os

STARTUP_TIME: datetime  # imported from boot module if needed


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    @mcp.tool()
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

