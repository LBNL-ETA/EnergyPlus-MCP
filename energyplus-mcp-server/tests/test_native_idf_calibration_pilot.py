import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_native_idf_calibration_pilot.py"
SPEC = importlib.util.spec_from_file_location("native_idf_calibration_pilot", SCRIPT)
pilot = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pilot)


def test_load_manifest_accepts_qualified_blind_inputs(tmp_path):
    model = tmp_path / "model.idf"
    weather = tmp_path / "weather.epw"
    model.write_text("Version,26.1;\n")
    weather.write_text("LOCATION,test\n")
    manifest = {
        "building": {"building_type": "office", "hvac_system_type": "Packaged system"},
        "model": {"pilot_idf": str(model), "pilot_sha256": pilot.sha256(model)},
        "weather": {"path": str(weather), "sha256": pilot.sha256(weather), "calendar_year": 2019},
        "utility_bills": {
            "calendar_year": 2019,
            "electricity_unit": "kWh",
            "gas_unit": "therm",
            "electricity_january_to_december": [1.0] * 12,
            "gas_january_to_december": [2.0] * 12,
        },
        "calibration": {"native_parameters_expected": sorted(pilot.REQUIRED_PARAMETERS)},
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))

    loaded = pilot.load_manifest(path)

    assert loaded["_manifest_path"] == str(path.resolve())


def test_load_manifest_rejects_year_and_hash_mismatch(tmp_path):
    model = tmp_path / "model.idf"
    weather = tmp_path / "weather.epw"
    model.write_text("Version,26.1;\n")
    weather.write_text("LOCATION,test\n")
    manifest = {
        "building": {"building_type": "office", "hvac_system_type": "Packaged system"},
        "model": {"pilot_idf": str(model), "pilot_sha256": "bad"},
        "weather": {"path": str(weather), "sha256": pilot.sha256(weather), "calendar_year": 2018},
        "utility_bills": {
            "calendar_year": 2019,
            "electricity_unit": "kWh",
            "gas_unit": "therm",
            "electricity_january_to_december": [1.0] * 12,
            "gas_january_to_december": [2.0] * 12,
        },
        "calibration": {"native_parameters_expected": sorted(pilot.REQUIRED_PARAMETERS)},
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))

    try:
        pilot.load_manifest(path)
    except ValueError as error:
        assert "calendar years do not match" in str(error)
        assert "SHA-256" in str(error)
    else:
        raise AssertionError("invalid manifest was accepted")


def test_convergence_and_pattern_selection_follow_methodology_priority():
    strict = {
        "nmbe_elec": 1.0,
        "nmbe_gas": -2.0,
        "cvrmse_elec": 10.0,
        "cvrmse_gas": 12.0,
        "nmbe_source": 1.0,
        "cvrmse_source": 8.0,
    }
    assert pilot.convergence_branch(strict, "strict") == "strict"
    assert pilot.convergence_branch({**strict, "cvrmse_gas": 16.0}, "strict") == "not_converged"

    elec = {"ub": 1, "ub_index": 0.2, "sb": 0}
    gas = {"ub": -1, "ub_index": 0.7, "sb": 0}
    assert pilot.select_pattern(elec, gas) == ("Gas universal bias", -1, gas)

    elec = {"ub": 0, "sb": 1, "sb_index": 30.0}
    gas = {"ub": 0, "sb": -1, "sb_index": 20.0}
    assert pilot.select_pattern(elec, gas) == ("Electricity seasonal bias", 1, elec)


def test_run_period_calendar_must_match_measured_year():
    valid = {"simulation_settings": {"RunPeriod": {"current_values": [{
        "index": 0,
        "Begin_Month": 1,
        "Begin_Day_of_Month": 1,
        "Begin_Year": 2019,
        "End_Month": 12,
        "End_Day_of_Month": 31,
        "End_Year": 2019,
        "Treat_Weather_as_Actual": "No",
    }]}}}
    assert pilot.validate_run_period_calendar(valid, 2019)[0]["Begin_Year"] == 2019

    invalid = json.loads(json.dumps(valid))
    invalid["simulation_settings"]["RunPeriod"]["current_values"][0]["Begin_Year"] = ""
    try:
        pilot.validate_run_period_calendar(invalid, 2019)
    except ValueError as error:
        assert "not aligned" in str(error)
    else:
        raise AssertionError("blank RunPeriod year was accepted")


def test_generic_domain_capability_smoke_uses_provider_recipes_and_hashes(tmp_path, monkeypatch):
    """The pilot never revives the deprecated calibration facade to tune an IDF."""
    source = tmp_path / "baseline.idf"
    source.write_text("Version,26.1;\n")
    candidate = tmp_path / "candidate.idf"
    source_hash = pilot.sha256(source)
    calls = []

    capabilities = {
        "internal_load_manager": {
            "LPD": {"supported": True, "coverage": "complete", "action": "adjust_percentage"},
            "EPD": {"supported": True, "coverage": "complete", "action": "adjust_percentage"},
            "OCD": {"supported": True, "coverage": "complete", "action": "adjust_percentage"},
            "coupled_occupancy": {
                "supported": True, "coverage": "complete", "action": "set_occupancy_ratio",
            },
        },
        "envelope_manager": {
            parameter: {"supported": True, "coverage": "complete", "action": "adjust_percentage"}
            for parameter in ("INF", "WIN-U", "WIN-SHGC")
        },
        "schedule_manager": {
            "lighting_schedule": {
                "supported": True, "coverage": "complete", "action": "adjust_percentage",
            },
            "equipment_schedule": {
                "supported": True, "coverage": "complete", "action": "adjust_percentage",
            },
            "hvac_availability_schedule": {
                "supported": True, "coverage": "complete", "action": "adjust_percentage",
            },
        },
        "hvac_manager": {
            parameter: {"supported": True, "coverage": "complete", "action": action}
            for parameter, action in {
                "COP": "adjust_percentage",
                "HE": "adjust_percentage",
                "FAN": "adjust_percentage",
                "heating_setpoint": "heating_setpoint_delta",
                "cooling_setpoint": "cooling_setpoint_delta",
                "outdoor_air_flow": "outdoor_air_flow_adjustment",
                "economizer_control": "economizer_control",
            }.items()
        },
        "service_water_manager": {
            "service_water_efficiency": {
                "supported": True,
                "coverage": "complete",
                "action": "adjust_efficiency_percentage",
            },
        },
    }

    async def mock_call(_session, _audit, server, tool, **arguments):
        calls.append((server, tool, arguments))
        if (
            server == "energyplus"
            and tool in capabilities
            and arguments["action"] == "parameter_capabilities"
        ):
            return {
                "success": True,
                "tool": tool,
                "manager": tool,
                "action": "parameter_capabilities",
                "model_format": "idf",
                "parameters": capabilities[tool],
            }
        if server == "energyplus" and tool == "internal_load_manager":
            if arguments["action"] == "inspect_parameter":
                return {
                    "success": True,
                    "parameter": "LPD",
                    "model_sha256": source_hash,
                    "coverage": "complete",
                    "targets": [],
                    "skipped": [],
                }
            return {"success": True, "changed": True, "changes": [{"field": "Lighting_Level"}]}
        if server == "energyplus" and tool == "schedule_manager":
            return {"success": True, "changed": True, "changes": [{"field": "Schedule"}]}
        if server == "energyplus" and tool == "simulation_manager":
            return {"success": True, "run_id": arguments["run_id"]}
        if server == "calibration" and tool == "get_measure_recipe":
            return {
                "ok": True,
                "recipes": [{
                    "tool_name": "internal_load_manager",
                    "arguments": {
                        "action": "adjust_percentage", "parameter": "LPD", "value": -10,
                    },
                    "required_args": ["idf_path", "parameter", "value", "output_path"],
                }],
            }
        raise AssertionError(f"unexpected mocked MCP call: {server} {tool} {arguments}")

    monkeypatch.setattr(pilot, "call", mock_call)

    async def exercise():
        audit = pilot.Audit(tmp_path / "audit.jsonl")
        aggregate = await pilot.collect_domain_capabilities(object(), audit, source)
        assert {
            tool for server, tool, arguments in calls
            if server == "energyplus" and arguments["action"] == "parameter_capabilities"
        } == set(pilot.GENERIC_CAPABILITY_MANAGERS)
        assert pilot.capability_for_parameter(
            aggregate, "lighting_schedule", tool_name="schedule_manager",
        )["action"] == "adjust_percentage"
        assert pilot.capability_for_parameter(
            aggregate, "heating_setpoint", tool_name="hvac_manager",
        )["action"] == "heating_setpoint_delta"
        assert pilot.capability_for_parameter(
            aggregate, "coupled_occupancy", tool_name="internal_load_manager",
        )["action"] == "set_occupancy_ratio"
        assert pilot.capability_for_parameter(
            aggregate, "service_water_efficiency", tool_name="service_water_manager",
        )["action"] == "adjust_efficiency_percentage"

        inspection = await pilot.inspect_parameter_from_capabilities(
            object(), audit, aggregate, source, "LPD",
        )
        recipe = (await pilot.call(
            object(), audit, "calibration", "get_measure_recipe", parameter="LPD", value=-10,
        ))["recipes"][0]
        await pilot.execute_provider_recipe(
            object(), audit, recipe,
            input_path=source,
            output_path=candidate,
            source_sha256=inspection["model_sha256"],
        )
        schedule_recipe = {
            "tool_name": "schedule_manager",
            "arguments": {
                "action": "adjust_percentage",
                "scope": "lighting",
                "percentage_change": -5,
                "mode": "apply",
                "expected_model_sha256": "{{input_sha256}}",
            },
            "required_args": ["idf_path", "scope", "percentage_change", "output_path"],
        }
        await pilot.execute_provider_recipe(
            object(), audit, schedule_recipe,
            input_path=source,
            output_path=candidate,
            source_sha256=source_hash,
        )
        await pilot.call(
            object(), audit, "energyplus", "simulation_manager",
            action="run", idf_path=str(candidate), weather_file="test.epw",
            runs_dir=str(tmp_path / "runs"), run_id="smoke", readvars=False,
        )
        return aggregate

    aggregate = __import__("asyncio").run(exercise())
    schedule_calls = [arguments for server, tool, arguments in calls if tool == "schedule_manager"]
    assert schedule_calls[-1]["expected_model_sha256"] == source_hash
    assert any(
        tool == "simulation_manager" and arguments["runs_dir"] == str(tmp_path / "runs")
        for _, tool, arguments in calls
    )

    partial = pilot.capability_for_parameter(aggregate, "LPD")
    partial["coverage"] = "partial"
    partial["supported"] = False
    for group in aggregate["domain_capabilities"]:
        if group["tool"] == "internal_load_manager":
            group["parameters"]["LPD"] = partial
    with pytest.raises(RuntimeError, match="coverage: partial"):
        pilot.require_complete_capability(aggregate, "LPD")
