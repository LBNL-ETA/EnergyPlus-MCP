"""Curated sample_files stay read-only; everything the server writes goes to work/."""

import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from energyplus_mcp_server.config import PathConfig
from energyplus_mcp_server.tool_surface import load_tool_surface, register_tool_surface
from energyplus_mcp_server.utils.idf_modifier import IDFModifier
from energyplus_mcp_server.utils.output_guard import guard_tool
from energyplus_mcp_server.utils.path_utils import (
    check_writable_path,
    derived_model_path,
    list_files,
    report_path,
    resolve_idf_path,
    resolve_weather_file_path,
)

SERVER_ROOT = Path(__file__).resolve().parents[1]
SIMULATION_OUTPUT_SUFFIXES = {
    ".audit", ".bnd", ".csv", ".eio", ".end", ".err", ".eso", ".htm", ".html",
    ".mdd", ".mtd", ".mtr", ".png", ".rdd", ".rvaudit", ".shd", ".sql", ".wrl",
}


class FakeMCP:
    def __init__(self):
        self._tool_manager = SimpleNamespace(_tools={})

    def tool(self, *args, **kwargs):
        def decorate(fn):
            self._tool_manager._tools[kwargs.get("name") or fn.__name__] = fn
            return fn

        return decorate


def _config(tmp_path):
    workspace = tmp_path / "server"
    paths = SimpleNamespace(
        workspace_root=str(workspace),
        sample_files_path=str(workspace / "sample_files"),
        uploads_dir=str(workspace / "work" / "models" / "uploads"),
        derived_models_dir=str(workspace / "work" / "models" / "derived"),
        output_dir=str(workspace / "work" / "runs"),
        reports_dir=str(workspace / "work" / "reports"),
    )
    install = tmp_path / "EnergyPlus-26-1-0"
    energyplus = SimpleNamespace(
        installation_path=str(install),
        example_files_path=str(install / "ExampleFiles"),
        weather_data_path=str(install / "WeatherData"),
    )
    for directory in (paths.sample_files_path, paths.uploads_dir, paths.derived_models_dir,
                      energyplus.example_files_path, energyplus.weather_data_path):
        Path(directory).mkdir(parents=True)
    return SimpleNamespace(paths=paths, energyplus=energyplus)


def _write(path: Path, text: str = "Version,26.1;\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_path_config_puts_every_output_under_work(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    paths = PathConfig()

    assert paths.sample_files_path == str(tmp_path / "sample_files")
    assert paths.output_dir == str(tmp_path / "work" / "runs")
    assert paths.uploads_dir == str(tmp_path / "work" / "models" / "uploads")
    assert paths.derived_models_dir == str(tmp_path / "work" / "models" / "derived")
    assert paths.reports_dir == str(tmp_path / "work" / "reports")


def test_repository_samples_are_categorized_and_free_of_simulation_outputs():
    sample_files = SERVER_ROOT / "sample_files"
    loose = [p.name for p in sample_files.iterdir() if p.is_file() and p.name != "README.md"]
    outputs = [
        str(p.relative_to(sample_files)) for p in sample_files.rglob("*")
        if p.is_file() and p.suffix.lower() in SIMULATION_OUTPUT_SUFFIXES
    ]

    assert loose == []
    assert outputs == []
    assert {"basic", "weather"} <= {p.name for p in sample_files.iterdir() if p.is_dir()}


def test_bare_and_legacy_sample_paths_resolve_into_categories(tmp_path):
    config = _config(tmp_path)
    model = _write(Path(config.paths.sample_files_path) / "basic" / "Box.idf")
    weather = _write(Path(config.paths.sample_files_path) / "weather" / "USA_CA_Fresno_TMY3.epw", "LOCATION")

    assert resolve_idf_path(config, "Box.idf") == str(model)
    assert resolve_idf_path(config, "sample_files/Box.idf") == str(model)
    assert resolve_idf_path(config, "sample_files/basic/Box.idf") == str(model)
    assert resolve_weather_file_path(config, "Fresno") == str(weather)


def test_curated_sample_wins_over_energyplus_example_with_same_name(tmp_path):
    config = _config(tmp_path)
    sample = _write(Path(config.paths.sample_files_path) / "basic" / "1ZoneUncontrolled.idf")
    _write(Path(config.energyplus.example_files_path) / "1ZoneUncontrolled.idf")

    assert resolve_idf_path(config, "1ZoneUncontrolled.idf") == str(sample)


def test_derived_models_resolve_by_bare_name(tmp_path):
    config = _config(tmp_path)
    derived = _write(Path(config.paths.derived_models_dir) / "Box_modified.idf")

    assert resolve_idf_path(config, "Box_modified.idf") == str(derived)


def test_list_files_reports_categories_and_work_models(tmp_path):
    config = _config(tmp_path)
    _write(Path(config.paths.sample_files_path) / "basic" / "Box.idf")
    _write(Path(config.paths.sample_files_path) / ".DS_Store", "")
    _write(Path(config.paths.uploads_dir) / "Client.idf")
    _write(Path(config.paths.derived_models_dir) / "Box_modified.idf")

    files = {(f["source"], f["category"], f["name"]) for f in list_files(config, extensions=["idf"])}
    assert files == {
        ("sample", "basic", "Box.idf"),
        ("upload", "", "Client.idf"),
        ("derived", "", "Box_modified.idf"),
    }


@pytest.mark.parametrize(
    "target",
    [
        "sample_files/basic/Box.idf",
        "sample_files",
        "{sample}/basic/Box_modified.idf",
        "{install}/ExampleFiles/Copy.idf",
        "{install}/WeatherData/run",
    ],
)
def test_read_only_inputs_reject_outputs(tmp_path, target):
    config = _config(tmp_path)
    path = target.format(sample=config.paths.sample_files_path, install=config.energyplus.installation_path)

    with pytest.raises(ValueError, match="read-only"):
        check_writable_path(config, path)


@pytest.mark.parametrize("target", ["work/models/derived/Box_v2.idf", "work/runs/box", "/elsewhere/Box.idf"])
def test_work_area_and_external_paths_are_writable(tmp_path, target):
    check_writable_path(_config(tmp_path), target)


def test_installation_that_contains_the_workspace_is_not_protected(tmp_path):
    config = _config(tmp_path)
    config.energyplus.installation_path = str(tmp_path)

    check_writable_path(config, "work/models/derived/Box_v2.idf")


def test_default_outputs_land_in_work(tmp_path):
    config = _config(tmp_path)
    source = str(Path(config.paths.sample_files_path) / "basic" / "Box.idf")

    assert derived_model_path(config, source) == str(Path(config.paths.derived_models_dir) / "Box_modified.idf")
    assert derived_model_path(config, source, "_with_meters").endswith("derived/Box_with_meters.idf")
    assert report_path(config, "Box_hvac_diagram.png") == str(Path(config.paths.reports_dir) / "Box_hvac_diagram.png")
    assert Path(config.paths.reports_dir).is_dir()

    generated = IDFModifier(output_dir=config.paths.derived_models_dir)._generate_output_path(source)
    assert Path(generated).parent == Path(config.paths.derived_models_dir)


def test_guard_preserves_signature_and_checks_output_arguments(tmp_path):
    config = _config(tmp_path)

    async def edit(idf_path: str, output_path: str | None = None) -> str:
        """Edit a model."""
        return output_path or "default"

    guarded = guard_tool(edit, config)

    assert inspect.signature(guarded) == inspect.signature(edit)
    assert guarded.__doc__ == "Edit a model."
    assert asyncio.run(guarded("Box.idf")) == "default"
    assert asyncio.run(guarded("Box.idf", output_path="work/models/derived/B.idf")) == "work/models/derived/B.idf"
    with pytest.raises(ValueError, match="read-only"):
        asyncio.run(guarded("Box.idf", "sample_files/basic/Box.idf"))


def test_registered_tools_are_guarded(tmp_path):
    config = _config(tmp_path)
    surface = load_tool_surface(None, {})
    mcp = FakeMCP()
    register_tool_surface(mcp, object(), config, surface)
    tools = mcp._tool_manager._tools

    with pytest.raises(ValueError, match="read-only"):
        asyncio.run(tools["file_utils"](action="copy", source_path="Box.idf",
                                        target_path="sample_files/basic/Box.idf"))
    with pytest.raises(ValueError, match="read-only"):
        asyncio.run(tools["simulation_manager"](action="run", idf_path="Box.idf",
                                                output_directory="sample_files/runs"))

