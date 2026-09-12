"""Focused no-simulation tests for generic service-water semantic targets."""

from __future__ import annotations

import hashlib

from energyplus_mcp_server.domains import service_water as service_water_domain
from energyplus_mcp_server.utils import service_water


class Record:
    def __init__(self, name: str, **fields):
        self.Name = name
        for key, value in fields.items():
            setattr(self, key, value)


class FakeIDF:
    def __init__(self, **objects):
        self.idfobjects = objects
        self.saved_paths = []
        self.fail_save = False

    def save(self, path):
        if self.fail_save:
            raise RuntimeError("synthetic save failure")
        self.saved_paths.append(path)
        with open(path, "w") as handle:
            handle.write("candidate")


def _complete_idf():
    equipment = Record(
        "Restroom fixtures",
        Peak_Flow_Rate=0.0002,
        Flow_Rate_Fraction_Schedule_Name="DHW flow fraction",
        Target_Temperature_Schedule_Name="DHW target temp",
    )
    connection = Record(
        "DHW connection",
        Water_Use_Equipment_1_Name="Restroom fixtures",
        Hot_Water_Supply_Temperature_Schedule_Name="DHW supply temp",
    )
    heater = Record(
        "DHW tank",
        Heater_Thermal_Efficiency=0.8,
        Heater_Fuel_Type="NaturalGas",
        On_Cycle_Loss_Coefficient_to_Ambient_Temperature=2.0,
        Off_Cycle_Loss_Coefficient_to_Ambient_Temperature=1.5,
        On_Cycle_Parasitic_Fuel_Consumption_Rate=10.0,
        Off_Cycle_Parasitic_Fuel_Consumption_Rate=5.0,
    )
    return FakeIDF(
        **{
            "WaterUse:Equipment": [equipment],
            "WaterUse:Connections": [connection],
            "WaterHeater:Mixed": [heater],
        }
    )


def _id_for(inspection, semantic):
    return next(
        target["target_id"]
        for target in inspection["applicable_targets"]
        if target["semantic"] == semantic
    )


def test_service_water_inspects_typed_targets_and_preserves_schedule_relationships():
    idf = _complete_idf()

    result = service_water.inspect(idf)

    assert result["coverage"] == "complete" and result["supported"]
    targets = result["applicable_targets"]
    assert {target["semantic"] for target in targets} == {
        "combustion_efficiency", "heater_fuel", "peak_flow_rate",
        "loss_coefficient", "parasitic_power",
    }
    peak_flow = next(target for target in targets if target["semantic"] == "peak_flow_rate")
    assert peak_flow["units"] == "m3/s"
    assert peak_flow["schedules"] == [
        {"field": "Flow_Rate_Fraction_Schedule_Name", "schedule_name": "DHW flow fraction"},
        {"field": "Target_Temperature_Schedule_Name", "schedule_name": "DHW target temp"},
    ]
    assert any(item["relationship"] == "water_use_connection" for item in result["shared_relationships"])
    assert any(item["relationship"] == "shared_schedule" for item in result["shared_relationships"])
    assert service_water.inspect(idf)["applicable_targets"] == targets


def test_service_water_plan_keeps_efficiency_fuel_and_flow_unit_families_separate():
    idf = _complete_idf()
    inspection = service_water.inspect(idf)
    assignments = {
        _id_for(inspection, "combustion_efficiency"): 0.9,
        _id_for(inspection, "heater_fuel"): "Electricity",
        _id_for(inspection, "peak_flow_rate"): 0.0003,
    }

    plan = service_water.plan_set(idf, assignments)

    assert plan["success"] and plan["changed"]
    assert all("object" not in change for change in plan["changes"])
    assert {item["units"] for item in plan["requested"]} == {"fraction", "fuel", "m3/s"}
    assert {item["semantic"] for item in plan["requested"]} == {
        "combustion_efficiency", "heater_fuel", "peak_flow_rate"
    }
    assert idf.idfobjects["WaterHeater:Mixed"][0].Heater_Thermal_Efficiency == 0.8
    assert idf.idfobjects["WaterUse:Equipment"][0].Peak_Flow_Rate == 0.0002


def test_missing_connection_is_ambiguous_and_prevents_all_edits():
    idf = _complete_idf()
    idf.idfobjects["WaterUse:Connections"][0].Water_Use_Equipment_1_Name = "Missing fixtures"

    inspection = service_water.inspect(idf)
    plan = service_water.plan_set(idf, {"not-a-target": 1.0})

    assert inspection["coverage"] == "ambiguous"
    assert not inspection["supported"]
    assert not plan["success"]
    assert plan["error"] == "service-water edits require complete, unambiguous coverage"


def test_service_water_apply_hash_binding_and_save_failure_are_atomic(tmp_path):
    idf = _complete_idf()
    inspection = service_water.inspect(idf)
    efficiency_id = _id_for(inspection, "combustion_efficiency")
    source = tmp_path / "source.idf"
    source.write_text("source")
    output = tmp_path / "candidate.idf"
    expected_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    result = service_water.execute(
        idf,
        input_path=str(source),
        output_path=str(output),
        assignments={efficiency_id: 0.9},
        mode="apply",
        expected_model_sha256=expected_hash,
    )

    assert result["success"] and result["changed"]
    assert result["input_sha256"] == expected_hash and output.exists()
    assert result["before"][0]["before"] == 0.8
    assert result["after"][0]["after"] == 0.9
    assert idf.idfobjects["WaterHeater:Mixed"][0].Heater_Thermal_Efficiency == 0.9

    failing = _complete_idf()
    failing.fail_save = True
    failed = service_water.execute(
        failing,
        input_path=str(source),
        output_path=str(tmp_path / "failed.idf"),
        assignments={efficiency_id: 0.9},
        mode="apply",
    )
    assert not failed["success"] and "failed to save" in failed["error"]
    assert failing.idfobjects["WaterHeater:Mixed"][0].Heater_Thermal_Efficiency == 0.8


def test_proposed_unregistered_domain_exposes_no_calibration_naming():
    contract = service_water_domain.operation_contract()

    assert contract["tool"] == "service_water_manager"
    assert [action["name"] for action in contract["actions"]] == [
        "capabilities", "parameter_capabilities", "inspect", "set_parameters",
        "adjust_efficiency_percentage",
    ]
    assert "calibration" not in str(contract).casefold()
