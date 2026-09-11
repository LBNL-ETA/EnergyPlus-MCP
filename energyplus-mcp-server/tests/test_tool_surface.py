from pathlib import Path
from types import SimpleNamespace

import pytest

from energyplus_mcp_server.tool_surface import (
    expected_tool_names,
    load_tool_surface,
    register_tool_surface,
)


class FakeMCP:
    def __init__(self):
        self._tool_manager = SimpleNamespace(_tools={})

    def tool(self, *args, **kwargs):
        def decorate(fn):
            self._tool_manager._tools[kwargs.get("name") or fn.__name__] = fn
            return fn

        return decorate


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text)
    return path


@pytest.mark.parametrize(
    ("mode", "expected_count"),
    [("domains", 12), ("masters", 11), ("hybrid", 16)],
)
def test_supported_surfaces_register_exactly_once(tmp_path, mode, expected_count):
    path = write_config(
        tmp_path,
        f"tool_surface:\n  mode: {mode}\n  domains:\n    envelope: true\n"
        "    internal_loads: true\n    hvac: true\n    outputs: true\n    geometry: true\n",
    )
    surface = load_tool_surface(path, {})
    mcp = FakeMCP()

    names = register_tool_surface(mcp, object(), object(), surface)

    assert names == expected_tool_names(surface)
    assert len(names) == expected_count
    assert "calibration_manager" not in names
    assert "retrofit_manager" not in names


def test_workflow_compatibility_is_explicit_and_adds_only_facades(tmp_path):
    path = write_config(
        tmp_path,
        "tool_surface:\n  mode: domains\n  compatibility:\n"
        "    workflow_managers: true\n",
    )
    surface = load_tool_surface(path, {})
    names = register_tool_surface(FakeMCP(), object(), object(), surface)

    assert {"calibration_manager", "retrofit_manager"} <= names
    assert len(names) == 14


def test_geometry_toggle_is_loaded(tmp_path):
    path = write_config(
        tmp_path,
        "tool_surface:\n  mode: domains\n  domains:\n    geometry: false\n",
    )
    surface = load_tool_surface(path, {})

    assert surface["domains"]["geometry"] is False
    assert "geometry_manager" not in expected_tool_names(surface)


def test_removed_retrofit_domain_has_actionable_error(tmp_path):
    path = write_config(
        tmp_path,
        "tool_surface:\n  mode: domains\n  domains:\n    retrofit: true\n",
    )
    with pytest.raises(ValueError, match="workflow_managers"):
        load_tool_surface(path, {})


def test_never_implemented_wrapper_switch_fails_closed(tmp_path):
    path = write_config(
        tmp_path,
        "tool_surface:\n  mode: domains\n  enable_wrappers: true\n",
    )
    with pytest.raises(ValueError, match="never implemented"):
        load_tool_surface(path, {})


def test_env_defaults_to_domain_surface():
    surface = load_tool_surface(None, {})

    assert surface["mode"] == "domains"
    assert all(surface["domains"].values())
    assert surface["compatibility"]["workflow_managers"] is False


def test_duplicate_registration_is_rejected(tmp_path):
    path = write_config(tmp_path, "tool_surface:\n  mode: masters\n")
    surface = load_tool_surface(path, {})
    mcp = FakeMCP()
    mcp._tool_manager._tools["inspect_model"] = object()

    with pytest.raises(RuntimeError, match="duplicate MCP tool"):
        register_tool_surface(mcp, object(), object(), surface)
