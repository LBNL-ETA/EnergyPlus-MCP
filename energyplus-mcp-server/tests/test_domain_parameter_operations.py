"""Contract tests for workflow-neutral semantic parameter domain actions."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from energyplus_mcp_server.domains import envelope, hvac, internal_loads, retrofit
from energyplus_mcp_server.energyplus_tools import EnergyPlusManager


class Registry:
    def tool(self):
        def capture(function):
            self.call = function
            return function
        return capture


class ParameterManager:
    def __init__(self):
        self.calls = []

    def parameter_capabilities(self, idf_path, parameters):
        self.calls.append(("parameter_capabilities", idf_path, tuple(parameters)))
        return {
            "success": True,
            "parameters": {
                parameter: {
                    "coverage": "complete",
                    "absolute_set_supported": True,
                    "absolute_set": {},
                }
                for parameter in parameters
            },
        }

    def inspect_parameter(self, idf_path, parameter):
        self.calls.append(("inspect_parameter", idf_path, parameter))
        return {"success": True, "parameter": parameter, "targets": []}

    def adjust_parameter_percentage(
        self, idf_path, parameter, value, output_path, expected_model_sha256=None,
        mode="apply",
    ):
        self.calls.append((
            "adjust_percentage", idf_path, parameter, value, output_path,
            expected_model_sha256, mode,
        ))
        return {"success": True, "parameter": parameter, "output_file": output_path}

    def set_parameter(
        self, idf_path, parameter, value, output_path, target_ids, assignments,
        model_hash, mode="apply",
    ):
        self.calls.append((
            "set_parameter", idf_path, parameter, value, output_path,
            target_ids, assignments, model_hash, mode,
        ))
        return {"success": True, "parameter": parameter, "output_file": output_path}


@pytest.mark.parametrize(
    ("module", "parameters", "parameter"),
    [
        (internal_loads, ("LPD", "EPD", "OCD"), "LPD"),
        (envelope, ("INF", "WIN-U", "WIN-SHGC"), "INF"),
        (hvac, ("COP", "HE", "FAN"), "COP"),
    ],
)
def test_domain_managers_expose_and_route_owned_semantic_parameters(module, parameters, parameter):
    registry = Registry()
    manager = ParameterManager()
    module.register(registry, manager, None)

    capability = json.loads(asyncio.run(registry.call(
        action="parameter_capabilities", idf_path="source.idf"
    )))
    assert set(parameters) <= set(capability["parameters"])
    assert capability["tool"] == capability["manager"]
    for owned_parameter in parameters:
        detail = capability["parameters"][owned_parameter]
        assert detail["tool"] == capability["tool"]
        assert detail["action"] == "adjust_percentage"
        assert detail["absolute_set"]["action"] == "set_parameter"

    inspection = json.loads(asyncio.run(
        registry.call(action="inspect_parameter", idf_path="source.idf", parameter=parameter)
    ))
    assert inspection["parameter"] == parameter
    assert inspection["action"] == "inspect_parameter"

    adjusted = json.loads(asyncio.run(
        registry.call(
            action="adjust_percentage", idf_path="source.idf", parameter=parameter,
            value=10, output_path="candidate.idf", expected_model_sha256="hash", mode="apply",
        )
    ))
    assert adjusted["output_file"] == "candidate.idf"
    assert adjusted["action"] == "adjust_percentage"

    absolute = json.loads(asyncio.run(registry.call(
        action="set_parameter", idf_path="source.idf", parameter=parameter,
        value=None, output_path="candidate.idf", target_ids=None,
        assignments={"target-1": 1.0}, expected_model_sha256="hash", mode="apply",
    )))
    assert absolute["action"] == "set_parameter"
    assert manager.calls == [
        ("parameter_capabilities", "source.idf", parameters),
        ("inspect_parameter", "source.idf", parameter),
        ("adjust_percentage", "source.idf", parameter, 10, "candidate.idf", "hash", "apply"),
        ("set_parameter", "source.idf", parameter, None, "candidate.idf", None, {"target-1": 1.0}, "hash", "apply"),
    ]


def test_domain_manager_rejects_parameter_owned_by_another_domain():
    registry = Registry()
    manager = ParameterManager()
    envelope.register(registry, manager, None)

    result = json.loads(asyncio.run(
        registry.call(action="inspect_parameter", idf_path="source.idf", parameter="LPD")
    ))

    assert "supports semantic parameters" in result["error"]
    assert manager.calls == []


def test_generic_manager_capabilities_do_not_leak_a_workflow_tool_name(monkeypatch):
    manager = EnergyPlusManager.__new__(EnergyPlusManager)
    monkeypatch.setattr(manager, "_runtime_energyplus_version", lambda: "26.1.0")

    payload = manager.parameter_capabilities(parameters=["LPD"])

    detail = payload["parameters"]["LPD"]
    assert detail["tool"] == "domain_manager"
    assert detail["action"] == "adjust_percentage"
    assert detail["absolute_set"]["tool"] == "domain_manager"
    assert detail["absolute_set"]["action"] == "set_parameter"


def test_envelope_generic_compound_helpers_and_master_helper_share_implementation():
    calls = []
    manager = SimpleNamespace(
        add_window_film_outside=lambda *args: calls.append(("film", args)) or "film-result",
        add_coating_outside=lambda *args: calls.append(("coating", args)) or "coating-result",
        change_infiltration_by_mult=lambda *args: calls.append(("infiltration", args)) or "infiltration-result",
        get_surfaces=lambda path: {"path": path, "surfaces": []},
        get_materials=lambda path: {"path": path, "materials": []},
    )

    assert envelope.modify_envelope(manager, "a.idf", "envelope.add_window_film", {}, None) == "film-result"
    assert envelope.modify_envelope(
        manager, "a.idf", "envelope.add_coating", {"surface_type": "roof"}, None
    ) == "coating-result"
    assert envelope.modify_envelope(
        manager, "a.idf", "infiltration.scale", {"multiplier": 0.7}, None
    ) == "infiltration-result"
    assert retrofit.apply_window_film(manager, "a.idf") == "film-result"
    assert envelope.inspect_envelope_data(manager, "a.idf", ["surfaces", "materials"]) == {
        "surfaces": {"path": "a.idf", "surfaces": []},
        "materials": {"path": "a.idf", "materials": []},
    }
    assert [name for name, _args in calls] == ["film", "coating", "infiltration", "film"]
