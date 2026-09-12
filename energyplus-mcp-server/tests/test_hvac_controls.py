from __future__ import annotations

from hashlib import sha256

import pytest

from energyplus_mcp_server.utils.hvac_controls import (
    control_capabilities,
    execute_control_operation,
    inspect_hvac_controls,
    plan_control_operation,
)
from energyplus_mcp_server.utils.schedule_graph import GraphScheduleControlAdapter


class Record:
    def __init__(self, name, **fields):
        self.Name = name
        for field, value in fields.items():
            setattr(self, field, value)


class FakeIDF:
    def __init__(self, **idfobjects):
        self.idfobjects = idfobjects

    def newidfobject(self, object_type):
        result = Record("")
        self.idfobjects.setdefault(object_type, []).append(result)
        return result

    def save(self, path):
        lines = []
        for object_type, objects in sorted(self.idfobjects.items()):
            for obj in objects:
                fields = sorted((key, value) for key, value in obj.__dict__.items())
                lines.append(f"{object_type}:{fields}")
        with open(path, "w", encoding="utf-8") as stream:
            stream.write("\n".join(lines))


class ScheduleAdapter:
    def __init__(self, profiles):
        self.profiles = profiles
        self.calls = []
        self.applied = []

    def inspect_consumers(self, *, idf, consumer_refs):
        self.calls.append(("inspect", [ref["consumer_id"] for ref in consumer_refs]))
        return {"profiles": self.profiles, "skipped": []}

    def plan_delta(self, **kwargs):
        self.calls.append(("delta", kwargs))
        changes = [
            {
                "target_id": target_id,
                "field": "schedule_values",
                "before": [20.0],
                "after": [20.0 + kwargs["delta_c"]],
            }
            for target_id in kwargs["target_ids"]
        ]
        return {
            "changes": changes,
            "clone_on_write": [{"decision": "clone", "protected_consumer_ids": [ref["consumer_id"] for ref in kwargs["protected_consumer_refs"]]}],
        }

    def plan_scale(self, **kwargs):
        self.calls.append(("scale", kwargs))
        return {
            "changes": [
                {"target_id": target_id, "field": "schedule_values", "before": [1.0], "after": [kwargs["factor"]]}
                for target_id in kwargs["target_ids"]
            ]
        }

    def apply_schedule_plan(self, **kwargs):
        self.applied.append(kwargs)
        return {"success": True}


def model(*, two_zones=False, shared_dsoa=False):
    zones = [Record("Zone 1")]
    sizing = [Record("Sizing 1", Zone_or_ZoneList_Name="Zone 1", Design_Specification_Outdoor_Air_Object_Name="OA")]
    if two_zones:
        zones.append(Record("Zone 2"))
        sizing.append(Record("Sizing 2", Zone_or_ZoneList_Name="Zone 2", Design_Specification_Outdoor_Air_Object_Name="OA"))
    dual = Record(
        "Dual", Heating_Setpoint_Temperature_Schedule_Name="Heat Schedule",
        Cooling_Setpoint_Temperature_Schedule_Name="Cool Schedule",
    )
    thermostat = Record(
        "Thermostat", Zone_or_ZoneList_Name="Zone 1",
        Control_1_Object_Type="ThermostatSetpoint:DualSetpoint", Control_1_Name="Dual",
    )
    if two_zones:
        zonelist = Record("Both Zones", Zone_1_Name="Zone 1", Zone_2_Name="Zone 2")
        thermostat.Zone_or_ZoneList_Name = "Both Zones"
    else:
        zonelist = None
    availability = Record("Supply Fan", Availability_Schedule_Name="Available")
    dsoa = Record(
        "OA", Outdoor_Air_Method="Sum", Outdoor_Air_Flow_per_Person=0.005,
        Outdoor_Air_Flow_per_Zone_Floor_Area=0.0003, Outdoor_Air_Flow_per_Zone=0.0,
        Outdoor_Air_Flow_Air_Changes_per_Hour=0.0,
    )
    controller = Record("OA Controller", Economizer_Control_Type="NoEconomizer")
    idfobjects = {
        "Zone": zones,
        "Sizing:Zone": sizing,
        "ZoneControl:Thermostat": [thermostat],
        "ThermostatSetpoint:DualSetpoint": [dual],
        "Fan:ConstantVolume": [availability],
        "DesignSpecification:OutdoorAir": [dsoa],
        "Controller:OutdoorAir": [controller],
    }
    if zonelist:
        idfobjects["ZoneList"] = [zonelist]
    return FakeIDF(**idfobjects), dsoa, controller


def adapter():
    return ScheduleAdapter({
        "Heat Schedule": {"values": [20.0, 21.0]},
        "Cool Schedule": {"values": [24.0, 25.0]},
        "Available": {"values": [0.0, 1.0]},
    })


def test_capabilities_and_inspection_cover_supported_hvac_control_families():
    idf, _dsoa, _controller = model()

    inspection = inspect_hvac_controls(idf, schedule_adapter=adapter())
    capabilities = control_capabilities(idf, schedule_adapter=adapter())

    assert {target["role"] for target in inspection["thermostats"]["targets"]} == {"heating", "cooling"}
    assert inspection["outdoor_air"]["targets"][0]["method"] == "Sum"
    assert inspection["economizers"]["targets"][0]["control_type"] == "NoEconomizer"
    assert all(detail["coverage"] == "complete" and detail["supported"]
               for detail in capabilities["operations"].values())


def test_heating_plan_checks_deadband_and_passes_clone_safe_adapter_contract():
    idf, _dsoa, _controller = model()
    schedules = adapter()

    planned = plan_control_operation(
        idf, "heating_setpoint_delta", 1.0, schedule_adapter=schedules,
        expected_model_sha256="source-hash", output_path="candidate.idf",
    )

    assert planned["success"] is True
    assert planned["coverage"] == "complete"
    assert planned["units"] == "C"
    delta_kwargs = next(item[1] for item in schedules.calls if item[0] == "delta")
    assert delta_kwargs["bounds"] == {"minimum": -60.0, "maximum": 60.0}
    assert delta_kwargs["clone_on_write"] is True
    assert delta_kwargs["expected_model_sha256"] == "source-hash"
    assert planned["clone_on_write"][0]["decision"] == "clone"

    invalid = plan_control_operation(idf, "heating_setpoint_delta", 5.0, schedule_adapter=adapter())

    assert invalid["success"] is False
    assert invalid["coverage"] == "partial"
    assert "deadband" in invalid["ambiguous"][0]["reason"]


def test_multi_control_thermostat_and_zone_scope_are_explicitly_ambiguous():
    idf, _dsoa, _controller = model(two_zones=True)
    thermostat = idf.idfobjects["ZoneControl:Thermostat"][0]

    scoped = plan_control_operation(
        idf, "cooling_setpoint_delta", 1.0, schedule_adapter=adapter(),
        scope="zones", zone_names=["Zone 1"],
    )
    assert scoped["coverage"] == "ambiguous"
    assert "non-selected zones" in scoped["ambiguous"][0]["reason"]

    thermostat.Control_2_Object_Type = "ThermostatSetpoint:SingleCooling"
    thermostat.Control_2_Name = "Other"
    ambiguous = plan_control_operation(idf, "heating_setpoint_delta", 1.0, schedule_adapter=adapter())
    assert ambiguous["coverage"] == "ambiguous"
    assert "exactly one control" in ambiguous["ambiguous"][0]["reason"]


def test_outdoor_air_sum_preserves_components_and_plans_clone_for_selected_consumer():
    idf, dsoa, _controller = model(two_zones=True)

    planned = plan_control_operation(
        idf, "outdoor_air_flow_adjustment", 20.0, scope="zones", zone_names=["Zone 1"],
    )

    assert planned["coverage"] == "complete"
    assert planned["applicable_targets"][0]["method"] == "Sum"
    assert {change["field"] for change in planned["changes"]} == {
        "Outdoor_Air_Flow_per_Person", "Outdoor_Air_Flow_per_Zone_Floor_Area",
    }
    assert sorted(change["after"] for change in planned["changes"]) == pytest.approx([0.00036, 0.006])
    assert planned["clone_on_write"] == [{
        "target_id": planned["applicable_targets"][0]["target_id"],
        "object_type": "DesignSpecification:OutdoorAir", "object_name": "OA", "decision": "clone",
        "protected_consumer_ids": [
            planned["clone_on_write"][0]["protected_consumer_ids"][0]
        ],
    }]
    assert dsoa.Outdoor_Air_Flow_per_Person == 0.005


def test_economizer_validation_and_apply_binds_source_hash_and_saves_new_idf(tmp_path):
    idf, _dsoa, controller = model()
    source = tmp_path / "source.idf"
    source.write_text("original", encoding="utf-8")
    output = tmp_path / "candidate.idf"
    expected_hash = sha256(source.read_bytes()).hexdigest()

    result = execute_control_operation(
        source, output, "economizer_control",
        {"control_type": "DifferentialDryBulb", "maximum_limit_dry_bulb_c": 22.0},
        idf_loader=lambda _path: idf, expected_model_sha256=expected_hash,
    )

    assert result["success"] is True
    assert result["mode"] == "apply"
    assert result["input_sha256"] == expected_hash
    assert result["output_sha256"] == sha256(output.read_bytes()).hexdigest()
    assert output.exists()
    assert controller.Economizer_Control_Type == "DifferentialDryBulb"
    assert controller.Economizer_Maximum_Limit_DryBulb_Temperature == 22.0
    assert all("_object" not in change for change in result["changes"])

    with pytest.raises(ValueError, match="inspect again"):
        execute_control_operation(
            source, tmp_path / "wrong.idf", "economizer_control", "NoEconomizer",
            idf_loader=lambda _path: idf, expected_model_sha256="not-the-source",
        )
    with pytest.raises(ValueError, match="unsupported economizer"):
        plan_control_operation(idf, "economizer_control", "NotAnEconomizer")


def test_water_coil_controller_is_not_an_economizer_coverage_gap():
    idf, _dsoa, _controller = model()
    idf.idfobjects["Controller:WaterCoil"] = [Record("Heating coil controller")]

    inspection = inspect_hvac_controls(idf, schedule_adapter=adapter())
    capabilities = control_capabilities(idf, schedule_adapter=adapter())

    assert inspection["economizers"]["skipped"] == []
    assert capabilities["operations"]["economizer_control"]["coverage"] == "complete"


def test_apply_clones_shared_outdoor_air_and_rewires_only_selected_zone(tmp_path):
    idf, source_dsoa, _controller = model(two_zones=True)
    source = tmp_path / "source.idf"
    source.write_text("original", encoding="utf-8")
    output = tmp_path / "candidate.idf"

    result = execute_control_operation(
        source, output, "outdoor_air_flow_adjustment", 20.0,
        idf_loader=lambda _path: idf, scope="zones", zone_names=["Zone 1"],
    )

    clone = idf.idfobjects["DesignSpecification:OutdoorAir"][1]
    first, second = idf.idfobjects["Sizing:Zone"]
    assert result["success"] is True
    assert output.exists()
    assert source_dsoa.Outdoor_Air_Flow_per_Person == 0.005
    assert clone.Outdoor_Air_Flow_per_Person == pytest.approx(0.006)
    assert first.Design_Specification_Outdoor_Air_Object_Name == clone.Name
    assert second.Design_Specification_Outdoor_Air_Object_Name == "OA"


def test_real_schedule_graph_adapter_applies_setpoint_delta_to_candidate(tmp_path):
    idf, _dsoa, _controller = model()
    heat = Record("Heat Schedule", Hourly_Value=20.0)
    cool = Record("Cool Schedule", Hourly_Value=24.0)
    available = Record("Available", Hourly_Value=1.0)
    idf.idfobjects["Schedule:Constant"] = [heat, cool, available]
    # Eppy preserves the active IDD's raw object-key spelling.  The HVAC
    # planner emits the canonical mixed-case ThermostatSetpoint identity.
    idf.idfobjects["THERMOSTATSETPOINT:DUALSETPOINT"] = idf.idfobjects.pop(
        "ThermostatSetpoint:DualSetpoint"
    )
    source = tmp_path / "source.idf"
    source.write_text("original", encoding="utf-8")
    output = tmp_path / "candidate.idf"

    blocked = plan_control_operation(
        idf,
        "heating_setpoint_delta",
        5.0,
        schedule_adapter=GraphScheduleControlAdapter(),
    )

    assert blocked["coverage"] == "partial"
    assert "deadband" in blocked["ambiguous"][0]["reason"]

    result = execute_control_operation(
        source,
        output,
        "heating_setpoint_delta",
        1.0,
        idf_loader=lambda _path: idf,
        schedule_adapter=GraphScheduleControlAdapter(),
    )

    assert result["success"] is True
    assert result["coverage"] == "complete"
    assert heat.Hourly_Value == pytest.approx(21.0)
    assert cool.Hourly_Value == pytest.approx(24.0)
    assert output.exists()
