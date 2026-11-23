import pytest

from energyplus_mcp_server.utils.calibration_hvac_setters import PARAMETERS, inspect, plan_set


class Record:
    def __init__(self, name, **fields):
        self.Name = name
        for field, value in fields.items():
            setattr(self, field, value)


class FakeIDF:
    def __init__(self, **idfobjects):
        self.idfobjects = idfobjects


def test_cop_inspection_exposes_two_speed_auxiliary_and_set_preserves_ratio():
    two_speed = Record(
        "two-speed",
        High_Speed_Gross_Rated_Cooling_COP=4.0,
        Low_Speed_Gross_Rated_Cooling_COP=3.0,
    )
    idf = FakeIDF(**{"COIL:COOLING:DX:TWOSPEED": [two_speed]})

    targets, skipped = inspect(idf, "COP")
    target = targets[0]
    planned, set_skipped = plan_set(idf, "COP", 5.0, [target["target_id"]])

    assert PARAMETERS == ("COP", "HE", "FAN")
    assert skipped == set_skipped == []
    assert target["value"] == 4.0
    assert target["units"] == "COP"
    assert target["auxiliary_fields"] == [{
        "field": "Low_Speed_Gross_Rated_Cooling_COP",
        "value": 3.0,
        "units": "COP",
        "preserve_ratio": True,
    }]
    assert target["low_to_high_ratio"] == 0.75
    assert [(change["field"], change["before"], change["after"]) for change in planned] == [
        ("High_Speed_Gross_Rated_Cooling_COP", 4.0, 5.0),
        ("Low_Speed_Gross_Rated_Cooling_COP", 3.0, 3.75),
    ]
    assert all(change["object"] is two_speed for change in planned)
    assert two_speed.High_Speed_Gross_Rated_Cooling_COP == 4.0
    assert two_speed.Low_Speed_Gross_Rated_Cooling_COP == 3.0


def test_he_targets_expose_mixed_units_and_require_explicit_unit_subsets():
    fuel = Record("fuel coil", Burner_Efficiency=0.8)
    heat_pump = Record("heat pump", Gross_Rated_Heating_COP=3.2)
    idf = FakeIDF(**{
        "COIL:HEATING:FUEL": [fuel],
        "COIL:HEATING:DX:SINGLESPEED": [heat_pump],
    })

    targets, skipped = inspect(idf, "HE")
    target_by_name = {target["object_name"]: target for target in targets}

    assert skipped == []
    assert target_by_name["fuel coil"]["units"] == "fraction"
    assert target_by_name["heat pump"]["units"] == "COP"
    with pytest.raises(ValueError, match="mix COP and fraction"):
        plan_set(idf, "HE", 0.9)

    fuel_plan, _ = plan_set(idf, "HE", 0.9, [target_by_name["fuel coil"]["target_id"]])
    hp_plan, _ = plan_set(idf, "HE", 4.0, [target_by_name["heat pump"]["target_id"]])

    assert [(change["field"], change["before"], change["after"]) for change in fuel_plan] == [
        ("Burner_Efficiency", 0.8, 0.9)
    ]
    assert [(change["field"], change["before"], change["after"]) for change in hp_plan] == [
        ("Gross_Rated_Heating_COP", 3.2, 4.0)
    ]


def test_fan_set_uses_total_efficiency_and_reports_unsupported_fan_types():
    fan = Record("supply fan", Fan_Total_Efficiency=0.7, Motor_Efficiency=0.9)
    system_fan = Record("system fan", Fan_Total_Efficiency=0.75)
    exhaust = Record("exhaust fan", Fan_Total_Efficiency=0.6)
    idf = FakeIDF(**{
        "FAN:VARIABLEVOLUME": [fan],
        "FAN:SYSTEMMODEL": [system_fan],
        "FAN:ZONEEXHAUST": [exhaust],
    })

    targets, skipped = inspect(idf, "FAN")
    planned, set_skipped = plan_set(idf, "FAN", 0.8)

    assert targets[0]["units"] == "fraction"
    assert [(change["field"], change["before"], change["after"]) for change in planned] == [
        ("Fan_Total_Efficiency", 0.7, 0.8)
    ]
    assert fan.Motor_Efficiency == 0.9
    assert skipped == set_skipped == [{
        "target_id": "FAN:FAN:SYSTEMMODEL:system fan:1",
        "object_type": "FAN:SYSTEMMODEL",
        "object_name": "system fan",
        "reason": "unsupported direct FAN tuning object type in the native-IDF MVP",
    }]


def test_set_rejects_unknown_targets_and_invalid_fractional_values():
    fan = Record("fan", Fan_Total_Efficiency=0.7)
    idf = FakeIDF(**{"FAN:ONOFF": [fan]})

    with pytest.raises(ValueError, match="unknown or unavailable"):
        plan_set(idf, "FAN", 0.8, ["FAN:FAN:ONOFF:missing:1"])
    with pytest.raises(ValueError, match=r"in \(0, 1\]"):
        plan_set(idf, "FAN", 1.01)

    assert fan.Fan_Total_Efficiency == 0.7
