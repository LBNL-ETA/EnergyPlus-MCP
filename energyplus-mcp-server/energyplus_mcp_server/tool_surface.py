"""Tool-surface configuration and duplicate-safe registration.

The default surface is organized by EnergyPlus/modeling domains. Historical
calibration and retrofit workflow managers are available only through the
explicit compatibility switch and delegate to the same domain implementation.
"""

from __future__ import annotations

import importlib
import logging
import os
from pathlib import Path
from typing import Any, Mapping

from energyplus_mcp_server.utils.output_guard import GuardedMCP

logger = logging.getLogger(__name__)

SUPPORTED_MODES = frozenset({"domains", "masters", "hybrid"})
DOMAIN_TOOLS = {
    "envelope": "envelope_manager",
    "internal_loads": "internal_load_manager",
    "schedules": "schedule_manager",
    "hvac": "hvac_manager",
    "service_water": "service_water_manager",
    "outputs": "outputs_manager",
    "geometry": "geometry_manager",
}
MASTER_TOOLS = (
    "inspect_model",
    "get_outputs",
    "modify_basic_parameters",
    "hvac_loop_inspect",
)
CORE_MODULES = (
    ("server", "server_manager"),
    ("preflight", "model_preflight"),
    ("model_upgrade", "model_upgrade"),
    ("simulation", "simulation_manager"),
    ("files", "file_utils"),
    ("post", "post_processing"),
    ("idf_modification", "idf_modification"),
    ("example_library", "example_library"),
    ("reference_docs", "reference_docs"),
    ("skills", ("list_skills", "get_skill")),
)
WORKFLOW_COMPAT_MODULES = (
    ("calibration", "calibration_manager"),
    ("energyplus_mcp_server.domains.retrofit", "retrofit_manager"),
)
LEGACY_WRAPPER_FLAGS = (
    "MCP_EXPOSE_INSPECT_WRAPPERS",
    "MCP_EXPOSE_OUTPUT_WRAPPERS",
    "MCP_EXPOSE_SUMMARY_WRAPPER",
    "MCP_EXPOSE_MODIFY_WRAPPERS",
    "MCP_EXPOSE_SERVER_WRAPPERS",
    "MCP_EXPOSE_HVAC_WRAPPERS",
    "MCP_EXPOSE_FILE_WRAPPERS",
    "MCP_EXPOSE_SIM_WRAPPERS",
    "MCP_EXPOSE_MODEL_WRAPPERS",
    "MCP_EXPOSE_POST_WRAPPERS",
)


def _as_names(tools: str | tuple[str, ...]) -> tuple[str, ...]:
    """A core module registers one tool name or a tuple of names."""
    return (tools,) if isinstance(tools, str) else tools


def _bool(value: Any, *, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}:
        return True
    if value is None or (isinstance(value, str) and value.strip().lower() in {"0", "false", "no", "off", ""}):
        return False
    raise ValueError(f"{name} must be a boolean")


def load_tool_surface(path: str | Path | None, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Load and validate the public tool surface without importing the server."""
    environ = os.environ if env is None else env
    raw: dict[str, Any] = {}
    if path and Path(path).is_file():
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover - production dependency
            raise RuntimeError("PyYAML is required to read MCP tool-surface configuration") from exc
        raw = yaml.safe_load(Path(path).read_text()) or {}
        if not isinstance(raw, dict):
            raise ValueError("MCP configuration root must be a mapping")
    surface = raw.get("tool_surface") or {}
    if not isinstance(surface, dict):
        raise ValueError("tool_surface must be a mapping")

    mode = str(surface.get("mode") or "").strip().lower()
    if not mode:
        masters = _bool(environ.get("MCP_EXPOSE_MASTERS"), name="MCP_EXPOSE_MASTERS")
        domains = _bool(environ.get("MCP_EXPOSE_DOMAIN_MANAGERS", "true"), name="MCP_EXPOSE_DOMAIN_MANAGERS")
        mode = "hybrid" if masters and domains else "masters" if masters else "domains"
    if mode not in SUPPORTED_MODES:
        raise ValueError(f"tool_surface.mode must be one of {sorted(SUPPORTED_MODES)}, got {mode!r}")

    configured_domains = surface.get("domains") or {}
    if not isinstance(configured_domains, dict):
        raise ValueError("tool_surface.domains must be a mapping")
    unknown = sorted(set(configured_domains) - set(DOMAIN_TOOLS))
    if unknown:
        if "retrofit" in unknown:
            raise ValueError(
                "tool_surface.domains.retrofit was removed; enable the deprecated "
                "compatibility.workflow_managers façade or use envelope_manager"
            )
        raise ValueError(f"unknown tool-surface domain(s): {', '.join(unknown)}")
    domains = {
        name: _bool(configured_domains.get(name, True), name=f"tool_surface.domains.{name}")
        for name in DOMAIN_TOOLS
    }

    compatibility = surface.get("compatibility") or {}
    if not isinstance(compatibility, dict):
        raise ValueError("tool_surface.compatibility must be a mapping")
    unknown_compat = sorted(set(compatibility) - {"workflow_managers"})
    if unknown_compat:
        raise ValueError(f"unknown tool-surface compatibility option(s): {', '.join(unknown_compat)}")
    workflow_compat = _bool(
        compatibility.get(
            "workflow_managers",
            environ.get("MCP_ENABLE_WORKFLOW_COMPATIBILITY", "false"),
        ),
        name="tool_surface.compatibility.workflow_managers",
    )

    if _bool(surface.get("enable_wrappers"), name="tool_surface.enable_wrappers"):
        raise ValueError(
            "tool_surface.enable_wrappers was never implemented and is removed; "
            "use domains, masters, hybrid, or compatibility.workflow_managers"
        )
    enabled_legacy_flags = [
        flag for flag in LEGACY_WRAPPER_FLAGS
        if _bool(environ.get(flag), name=flag)
    ]
    if enabled_legacy_flags:
        raise ValueError(
            "legacy wrapper flags were never implemented and are removed: "
            + ", ".join(enabled_legacy_flags)
        )

    return {
        "mode": mode,
        "domains": domains,
        "compatibility": {"workflow_managers": workflow_compat},
    }


def expected_tool_names(surface: Mapping[str, Any]) -> set[str]:
    """Return the exact tool set expected for a validated surface."""
    names = {tool for _, tools in CORE_MODULES for tool in _as_names(tools)}
    mode = surface["mode"]
    if mode in {"domains", "hybrid"}:
        names.update(
            DOMAIN_TOOLS[name]
            for name, enabled in surface["domains"].items()
            if enabled
        )
    if mode in {"masters", "hybrid"}:
        names.update(MASTER_TOOLS)
    if surface["compatibility"]["workflow_managers"]:
        names.update(tool for _, tool in WORKFLOW_COMPAT_MODULES)
    return names


def _tool_names(mcp: Any) -> set[str]:
    manager = getattr(mcp, "_tool_manager", None)
    tools = getattr(manager, "_tools", None)
    if not isinstance(tools, dict):
        raise RuntimeError("installed MCP SDK does not expose the registered-tool registry")
    return set(tools)


def _register_checked(register: Any, expected: set[str], mcp: Any, ep_manager: Any, config: Any) -> None:
    before = _tool_names(mcp)
    duplicates = before & expected
    if duplicates:
        raise RuntimeError(f"duplicate MCP tool registration attempted: {sorted(duplicates)}")
    register(GuardedMCP(mcp, config), ep_manager, config)
    added = _tool_names(mcp) - before
    if added != expected:
        raise RuntimeError(
            f"tool registration mismatch: expected {sorted(expected)}, added {sorted(added)}"
        )


def register_tool_surface(mcp: Any, ep_manager: Any, config: Any, surface: Mapping[str, Any]) -> set[str]:
    """Register a validated surface exactly once and return its public names."""
    if surface["mode"] in {"domains", "hybrid"}:
        from energyplus_mcp_server.domains import register_all as register_domains

        enabled = {name for name, value in surface["domains"].items() if value}
        _register_checked(
            lambda target, manager, cfg: register_domains(
                target,
                manager,
                cfg,
                **{name: name in enabled for name in DOMAIN_TOOLS},
            ),
            {DOMAIN_TOOLS[name] for name in enabled},
            mcp,
            ep_manager,
            config,
        )

    if surface["mode"] in {"masters", "hybrid"}:
        from energyplus_mcp_server.tools import register_all as register_masters

        _register_checked(register_masters, set(MASTER_TOOLS), mcp, ep_manager, config)

    for module_name, tools in CORE_MODULES:
        module = importlib.import_module(f"energyplus_mcp_server.tools.{module_name}")
        _register_checked(module.register, set(_as_names(tools)), mcp, ep_manager, config)

    if surface["compatibility"]["workflow_managers"]:
        for module_name, tool_name in WORKFLOW_COMPAT_MODULES:
            qualified = module_name if "." in module_name else f"energyplus_mcp_server.tools.{module_name}"
            module = importlib.import_module(qualified)
            _register_checked(module.register, {tool_name}, mcp, ep_manager, config)
        logger.warning(
            "Deprecated workflow-manager compatibility façade enabled; migrate to domain managers"
        )

    actual = _tool_names(mcp)
    expected = expected_tool_names(surface)
    if actual != expected:
        raise RuntimeError(
            f"public MCP tool surface mismatch: expected {sorted(expected)}, got {sorted(actual)}"
        )
    return actual
