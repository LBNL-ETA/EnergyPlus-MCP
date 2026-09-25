"""Focused contract tests for native calibration dispatch."""

import asyncio
import json
from types import SimpleNamespace
import pytest

from energyplus_mcp_server.energyplus_tools import EnergyPlusManager
from energyplus_mcp_server.tools.calibration import register
from energyplus_mcp_server.utils import model_parameters as calibration


def test_numeric_range_handles_eppy_glazing_bound_lists():
    obj = SimpleNamespace(getrange=lambda field: {"minimum>": ["0"], "maximum": ["7"]})
    calibration.check_numeric_range(obj, "UFactor", 2.5)
    with pytest.raises(ValueError, match="IDD"):
        calibration.check_numeric_range(obj, "UFactor", 0)
    with pytest.raises(ValueError, match="IDD"):
        calibration.check_numeric_range(obj, "UFactor", 7.1)


def test_lpd_uses_native_92_density_field():
    lights = SimpleNamespace(Name="old-schema lights", Design_Level_Calculation_Method="Watts/Area",
                             Watts_per_Zone_Floor_Area=10)
    planned, skipped = calibration.plan(SimpleNamespace(idfobjects={"Lights": [lights]}), "LPD", 10)
    assert not skipped
    assert planned[0]["field"] == "Watts_per_Zone_Floor_Area"
    assert planned[0]["after"] == 11


def test_capabilities_require_model_and_complete_coverage(monkeypatch):
    assert all(not item["supported"] for item in calibration.capabilities().values())
    monkeypatch.setattr(calibration, "plan", lambda *args: ([{}], [{"reason": "unsupported"}]))
    monkeypatch.setattr(calibration, "inspect_absolute", lambda *args: {
        "coverage": "none", "targets": [], "skipped": [],
    })
    result = calibration.capabilities(object())
    assert all(item["coverage"] == "partial" and not item["supported"] for item in result.values())


def test_partial_plan_does_not_save_candidate(monkeypatch, tmp_path):
    source = tmp_path / "source.idf"
    source.write_text("Version,25.1;")
    candidate = tmp_path / "candidate.idf"
    manager = EnergyPlusManager.__new__(EnergyPlusManager)
    monkeypatch.setattr(manager, "_resolve_idf_path", lambda path: str(source))
    monkeypatch.setattr(manager, "_assert_simulation_version_matches", lambda path: {})
    monkeypatch.setattr("energyplus_mcp_server.energyplus_tools.IDF", lambda path: object())
    monkeypatch.setattr(calibration, "plan", lambda *args: ([{}], [{"reason": "unsupported"}]))
    result = manager.adjust_calibration_percentage(str(source), "COP", 10, str(candidate))
    assert not result["success"] and result["skipped"]
    assert not candidate.exists()
    assert source.read_text() == "Version,25.1;"


def test_registered_dispatch_passes_parameter_and_reports_errors():
    class Registry:
        def tool(self):
            def capture(fn):
                self.call = fn
                return fn
            return capture

    registry = Registry()
    calls = []
    manager = SimpleNamespace(adjust_calibration_percentage=lambda *args: calls.append(args) or {"success": True})
    register(registry, manager, None)
    result = json.loads(asyncio.run(registry.call("perturb", "source.idf", "COP", 10, "candidate.idf")))
    assert result["success"]
    assert calls == [("source.idf", "COP", 10, "candidate.idf")]


def test_absolute_batch_rejects_conflicting_shared_fields(monkeypatch):
    shared = object()
    fake = SimpleNamespace(plan_set=lambda idf, parameter, value, ids: ([{
        "object": shared, "field": "Efficiency", "before": 0.5, "after": value,
    }], []))
    monkeypatch.setattr(calibration, "_setter", lambda parameter: fake)
    with pytest.raises(ValueError, match="conflict"):
        calibration.plan_absolute(object(), "FAN", assignments={"a": 0.6, "b": 0.7})


def test_absolute_set_refuses_stale_inspection_before_loading(monkeypatch, tmp_path):
    source = tmp_path / "source.idf"
    source.write_text("Version,25.1;")
    manager = EnergyPlusManager.__new__(EnergyPlusManager)
    monkeypatch.setattr(manager, "_resolve_idf_path", lambda path: str(source))
    with pytest.raises(ValueError, match="changed since inspection"):
        manager.set_calibration_values(str(source), "FAN", 0.7, str(tmp_path / "out.idf"),
                                       expected_model_sha256="wrong")
    assert not (tmp_path / "out.idf").exists()
