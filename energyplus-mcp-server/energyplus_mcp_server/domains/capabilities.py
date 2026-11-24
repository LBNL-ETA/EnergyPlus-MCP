"""One-call parameter capabilities across the semantic domain managers.

Each domain manager reports ``action="parameter_capabilities"`` for the
parameters it owns. A consumer that needs all of them (for example a
calibration service's meter and measure-reach gates) previously had to call
five managers and assemble their responses by hand. This tool returns that
aggregate directly: the model identity, monthly meters, and simulation
evidence contract at the top level, and each manager's response unchanged in
structure under ``domain_capabilities``.

``detail="summary"`` (the default) drops per-object listings that only
describe *which* objects a parameter reaches. Coverage, support, skipped and
ambiguous objects, bounds, and operation contracts are always kept, so the
summary is a complete capability statement. ``detail="full"`` returns every
field.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, Sequence, Tuple

from ..utils.model_cache import with_shared_models

# (tool_surface domain name, manager tool name, module name)
PARAMETER_DOMAINS: Tuple[Tuple[str, str, str], ...] = (
    ("internal_loads", "internal_load_manager", "internal_loads"),
    ("envelope", "envelope_manager", "envelope"),
    ("schedules", "schedule_manager", "schedules"),
    ("hvac", "hvac_manager", "hvac"),
    ("service_water", "service_water_manager", "service_water"),
)
TOOL_NAME = "parameter_capabilities"

# Per-object listings: large on real models (hundreds of KB for an HVAC
# availability schedule graph) and not part of the capability decision.
BULKY_FIELDS = (
    "applicable_targets",
    "shared_object_relationships",
    "consumer_references",
    "all_service_water_targets",
)
# Top-level fields repeated by every manager that this tool states once.
SHARED_FIELDS = (
    "model_format", "idf_path", "model_sha256", "energyplus_version", "model_version",
    "monthly_meters", "simulation_evidence",
)
# Folder under a calibration runs_dir; run counters only look for
# <runs_dir>/*/run_record.json, which this folder never contains.
CAPABILITIES_SUBDIR = "capabilities"


def _model_sha256(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _domain_capability_function(module_name: str) -> Callable[[Any, Optional[str]], Dict[str, Any]]:
    import importlib

    module = importlib.import_module(f"energyplus_mcp_server.domains.{module_name}")
    return module._parameter_capabilities


def _compact_parameter(declaration: Dict[str, Any]) -> Dict[str, Any]:
    compact = dict(declaration)
    omitted: Dict[str, int] = {}
    for field in BULKY_FIELDS:
        value = compact.get(field)
        if isinstance(value, list):
            omitted[field] = len(value)
            del compact[field]
    if "applicable_targets" in omitted and "applicable_target_count" not in compact:
        compact["applicable_target_count"] = omitted["applicable_targets"]
    if omitted:
        compact["omitted_counts"] = omitted
    return compact


def _compact_domain(response: Dict[str, Any]) -> Dict[str, Any]:
    compact = {
        key: value for key, value in response.items()
        if key not in SHARED_FIELDS and key not in ("applicability", "ready", "input_file", "input_sha256")
    }
    compact["parameters"] = {
        key: _compact_parameter(value) if isinstance(value, dict) else value
        for key, value in response.get("parameters", {}).items()
    }
    return compact


@with_shared_models
def combined_capabilities(
    ep_manager: Any,
    idf_path: str,
    managers: Sequence[str],
    detail: str = "summary",
) -> Dict[str, Any]:
    """Collect the enabled managers' parameter capabilities for one IDF."""
    from ..energyplus_tools import MONTHLY_FACILITY_METERS, simulation_evidence_contract

    if detail not in ("summary", "full"):
        raise ValueError("detail must be 'summary' or 'full'")
    if not isinstance(idf_path, str) or not idf_path.strip():
        raise ValueError("idf_path is required")
    # Resolve and version-check once: a missing file or a model the installed
    # EnergyPlus cannot run is one clear error, not one per manager.
    try:
        resolved = ep_manager._resolve_idf_path(idf_path)
        versions = ep_manager._assert_simulation_version_matches(resolved)
        model_sha256 = _model_sha256(resolved)
    except Exception as error:
        failure = {"success": False, "ready": False, "tool": TOOL_NAME,
                   "action": "parameter_capabilities", "model_format": "idf",
                   "idf_path": idf_path, "error": str(error)}
        if "does not match model Version" in str(error):
            failure["next_action"] = (
                "Copy-upgrade the model with model_upgrade(action='run', idf_path=..., "
                "output_directory=<new folder>) and pass the upgraded IDF."
            )
        return failure
    responses: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    for _, manager, module_name in PARAMETER_DOMAINS:
        if manager not in managers:
            continue
        try:
            response = _domain_capability_function(module_name)(ep_manager, resolved)
        except Exception as error:  # report per manager; never hide a failed domain
            errors.append({"manager": manager, "error": str(error)})
            continue
        if response.get("success") is False:
            errors.append({
                "manager": manager,
                "error": response.get("model_error") or response.get("runtime_error")
                or response.get("error") or "capabilities unavailable",
            })
            continue
        response.setdefault("tool", manager)
        response.setdefault("manager", manager)
        response["action"] = "parameter_capabilities"
        responses.append(response)

    # Stated by this tool, not borrowed from whichever manager reports them:
    # schedules and service water alone do not repeat these fields.
    shared: Dict[str, Any] = {
        "model_format": "idf",
        "idf_path": resolved,
        "model_sha256": model_sha256,
        "energyplus_version": versions.get("runtime_version"),
        "model_version": versions.get("model_version"),
        "monthly_meters": list(MONTHLY_FACILITY_METERS),
        "simulation_evidence": simulation_evidence_contract(),
    }

    coverage = {
        key: {
            "manager": response["tool"],
            "coverage": value.get("coverage"),
            "supported": value.get("supported"),
        }
        for response in responses
        for key, value in response.get("parameters", {}).items()
        if isinstance(value, dict)
    }
    groups = responses if detail == "full" else [_compact_domain(r) for r in responses]
    result: Dict[str, Any] = {
        "success": not errors,
        "ready": not errors,
        "tool": TOOL_NAME,
        "action": "parameter_capabilities",
        **shared,
        "detail": detail,
        "managers": [response["tool"] for response in responses],
        "coverage": coverage,
        "domain_capabilities": groups,
        "usage": (
            "This is the aggregate of every enabled domain manager's "
            "parameter_capabilities. Pass the whole response unchanged as "
            "`capabilities` to a consumer gate (for example calibration "
            "check_model_meters and check_measure_reach); do not rebuild it."
        ),
    }
    if detail == "summary":
        result["omitted_fields"] = list(BULKY_FIELDS)
    if errors:
        result["errors"] = errors
    return result


def write_capabilities_file(result: Dict[str, Any], path: Path) -> Dict[str, Any]:
    """Write the full response atomically; return where it is and its sha256."""
    text = json.dumps(result, indent=1, sort_keys=True) + "\n"
    data = text.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return {
        "capabilities_path": str(path),
        "capabilities_sha256": hashlib.sha256(data).hexdigest(),
        "capabilities_bytes": len(data),
    }


def file_reply(result: Dict[str, Any], written: Dict[str, Any]) -> Dict[str, Any]:
    """Short reply naming the file instead of repeating the response."""
    keys = ("success", "ready", "tool", "action", "model_format", "idf_path", "model_sha256",
            "energyplus_version", "model_version", "detail", "managers", "coverage", "errors")
    reply = {key: result[key] for key in keys if key in result}
    reply.update(written)
    reply["usage"] = (
        "The full capability response is in capabilities_path. Give a consumer gate "
        "capabilities_path and capabilities_sha256 instead of copying the response; if the "
        "consumer cannot read this server's files, call again without runs_dir/output_path "
        "to get the response inline."
    )
    return reply


def capabilities_target(
    result: Dict[str, Any], runs_dir: Optional[str], output_path: Optional[str]
) -> Optional[Path]:
    """Where to write the response, or None to reply inline."""
    if output_path:
        return Path(output_path).expanduser().resolve()
    if runs_dir:
        return Path(runs_dir).expanduser().resolve() / CAPABILITIES_SUBDIR / f"{result['model_sha256']}.json"
    return None


def register(mcp: Any, ep_manager: Any, config: Any, managers: Sequence[str]) -> None:
    """Register the aggregate tool for the enabled parameter-domain managers."""
    enabled = tuple(managers)

    @mcp.tool(name=TOOL_NAME)
    async def parameter_capabilities(
        idf_path: str,
        detail: Optional[Literal["summary", "full"]] = None,
        runs_dir: Optional[str] = None,
        output_path: Optional[str] = None,
    ) -> str:
        """All semantic-parameter capabilities of one IDF in a single response.

        Runs parameter_capabilities on every enabled domain manager
        (internal loads, envelope, schedules, HVAC, service water) and returns
        model_format, idf_path, energyplus_version, monthly_meters,
        simulation_evidence, a per-parameter `coverage` index, and each
        manager's response under `domain_capabilities`. Pass the whole result
        unchanged to a consumer that asks for domain capability results.
        detail="summary" (default) omits per-object target and relationship
        lists but keeps coverage, skipped/ambiguous objects, and bounds;
        detail="full" includes everything.

        To avoid copying a large response through the conversation, pass
        runs_dir (writes <runs_dir>/capabilities/<model_sha256>.json) or
        output_path: the full response (detail="full" unless given) goes to
        that file, and the reply carries capabilities_path,
        capabilities_sha256, model_sha256 and the coverage index. A calibration
        gate can then read the file directly. Without either argument the
        response is returned inline (detail="summary" unless given).
        """
        try:
            to_file = bool(runs_dir or output_path)
            chosen = detail or ("full" if to_file else "summary")
            result = combined_capabilities(ep_manager, idf_path, enabled, chosen)
            target = capabilities_target(result, runs_dir, output_path) if "model_sha256" in result else None
            if target is None:
                return json.dumps(result, indent=1)
            return json.dumps(file_reply(result, write_capabilities_file(result, target)), indent=1)
        except Exception as error:
            return json.dumps({"success": False, "tool": TOOL_NAME, "error": str(error)})
