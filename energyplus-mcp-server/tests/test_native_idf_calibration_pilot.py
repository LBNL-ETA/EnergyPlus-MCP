import importlib.util
import json
from pathlib import Path


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
