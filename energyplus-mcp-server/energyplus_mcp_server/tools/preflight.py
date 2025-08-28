from typing import Any, Dict, Optional, Literal
import json
import os
import logging

logger = logging.getLogger(__name__)


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    @mcp.tool()
    async def model_preflight(
        action: Literal["load", "validate", "info", "resolve_paths", "readiness", "capabilities"],
        idf_path: Optional[str] = None,
        weather_file: Optional[str] = None,
        detail: Literal["summary", "detailed"] = "summary",
    ) -> str:
        try:
            if action == "capabilities":
                return json.dumps({
                    "tool": "model_preflight",
                    "actions": [
                        {"name": "load", "required": ["idf_path"]},
                        {"name": "validate", "required": ["idf_path"]},
                        {"name": "info", "required": ["idf_path"]},
                        {"name": "resolve_paths", "required": ["idf_path"], "optional": ["weather_file"]},
                        {"name": "readiness", "required": ["idf_path"], "optional": ["weather_file"]},
                    ],
                    "detail": detail,
                }, indent=2)

            if not idf_path:
                return "Missing required parameter: idf_path"

            if action == "load":
                result = ep_manager.load_idf(idf_path)
                return json.dumps(result, indent=2)

            if action == "validate":
                result = ep_manager.validate_idf(idf_path)
                return f"Validation results for {idf_path}:\n{result}"

            if action == "info":
                result = ep_manager.get_model_basics(idf_path)
                return f"Model basics for {idf_path}:\n{result}"

            if action == "resolve_paths":
                idf_resolved = ep_manager._resolve_idf_path(idf_path)
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
                issues = []
                verdict = True
                idd_path = config.energyplus.idd_path
                idd_ok = bool(idd_path and os.path.exists(idd_path))
                if not idd_ok:
                    issues.append(f"IDD not found at configured path: {idd_path}")
                    verdict = False
                try:
                    idf_resolved = ep_manager._resolve_idf_path(idf_path)
                    if not os.path.exists(idf_resolved):
                        issues.append(f"Resolved IDF does not exist: {idf_resolved}")
                        verdict = False
                except Exception as e:
                    issues.append(f"Failed to resolve IDF: {str(e)}")
                    verdict = False
                    idf_resolved = None
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
                try:
                    validation = ep_manager.validate_idf(idf_path)
                    validation_obj = json.loads(validation) if isinstance(validation, str) else validation
                    err_cnt = validation_obj.get("errors_count") if isinstance(validation_obj, dict) else None
                    if isinstance(err_cnt, int) and err_cnt > 0:
                        issues.append(f"Validation errors: {err_cnt}")
                        verdict = False
                except Exception as e:
                    issues.append(f"Validation failed: {str(e)}")
                    verdict = False
                return json.dumps({
                    "verdict": verdict,
                    "idf": {"input": idf_path, "resolved": idf_resolved},
                    "weather": {"input": weather_file, "resolved": weather_resolved},
                    "idd": {"path": idd_path, "exists": idd_ok},
                    "issues": issues,
                }, indent=2)

            return f"Unsupported action: {action}"
        except FileNotFoundError as e:
            return f"File not found: {str(e)}"
        except Exception as e:
            return f"Error in model_preflight: {str(e)}"

