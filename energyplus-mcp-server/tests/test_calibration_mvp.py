import json

from energyplus_mcp_server.energyplus_tools import EnergyPlusManager


def test_lpd_perturbation_scales_the_active_field_case_insensitively(monkeypatch, tmp_path):
    class Lights:
        Name = "Office lights"
        Design_Level_Calculation_Method = "watts/area"
        Watts_per_Floor_Area = 10.0

        def checkrange(self, field):
            assert field == "Watts_per_Floor_Area"

    class FakeIDF:
        def __init__(self, _path):
            self.idfobjects = {"Lights": [Lights()]}

        def save(self, path):
            with open(path, "w") as stream:
                stream.write("saved")

    manager = EnergyPlusManager.__new__(EnergyPlusManager)
    input_idf = tmp_path / "input.idf"
    input_idf.write_text("Version, 25.1;")
    output_idf = tmp_path / "candidate.idf"
    monkeypatch.setattr(manager, "_resolve_idf_path", lambda path: str(input_idf))
    monkeypatch.setattr("energyplus_mcp_server.energyplus_tools.IDF", FakeIDF)

    result = manager.adjust_lighting_power_percentage(str(input_idf), -10, str(output_idf))

    assert result["success"] is True
    assert result["changes"] == [{
        "object_name": "Office lights",
        "calculation_method": "watts/area",
        "field": "Watts_per_Floor_Area",
        "before": 10.0,
        "after": 9.0,
    }]
    assert output_idf.exists()


def test_calibration_run_record_uses_the_directory_identity(tmp_path):
    manager = EnergyPlusManager.__new__(EnergyPlusManager)

    context = manager._start_calibration_run(str(tmp_path), "candidate-1", "candidate.idf")
    manager._finish_calibration_run(context, "failed", error="simulator failed")

    record = json.loads((tmp_path / "candidate-1" / "run_record.json").read_text())
    assert record["run_id"] == "candidate-1"
    assert record["status"] == "failed"
    assert isinstance(record["started_at"], float)
