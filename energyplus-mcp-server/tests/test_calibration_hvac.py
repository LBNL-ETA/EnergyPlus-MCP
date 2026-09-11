import pytest

from energyplus_mcp_server.utils.calibration_hvac import PARAMETERS, plan


class Record:
    def __init__(self, name, **fields):
        self.Name = name
        for field, value in fields.items():
            setattr(self, field, value)


class FakeIDF:
    def __init__(self, **idfobjects):
        self.idfobjects = idfobjects


def test_cop_plan_scales_single_two_speed_and_chiller_without_mutating():
    single = Record("single", Gross_Rated_Cooling_COP=3.0)
    two_speed = Record(
        "two-speed",
        High_Speed_Gross_Rated_Cooling_COP=3.2,
        Low_Speed_Gross_Rated_Cooling_COP=2.8,
    )
    chiller = Record("plant chiller", Reference_COP=5.0)
    idf = FakeIDF(
        **{
            "coil:cooling:dx:singlespeed": [single],
            "COIL:COOLING:DX:TWOSPEED": [two_speed],
            "Chiller:Electric:EIR": [chiller],
        }
    )

    planned, skipped = plan(idf, "cop", 10)

    assert PARAMETERS == ("COP", "HE", "FAN")
    assert skipped == []
    assert [(change["object_name"], change["field"], change["before"]) for change in planned] == [
        ("single", "Gross_Rated_Cooling_COP", 3.0),
        ("two-speed", "High_Speed_Gross_Rated_Cooling_COP", 3.2),
        ("two-speed", "Low_Speed_Gross_Rated_Cooling_COP", 2.8),
        ("plant chiller", "Reference_COP", 5.0),
    ]
    assert [change["after"] for change in planned] == pytest.approx([3.3, 3.52, 3.08, 5.5])
    assert all(change["object"] in (single, two_speed, chiller) for change in planned)
    assert single.Gross_Rated_Cooling_COP == 3.0
    assert two_speed.Low_Speed_Gross_Rated_Cooling_COP == 2.8
    assert chiller.Reference_COP == 5.0


def test_two_speed_requires_both_cops_and_reports_invalid_source_without_partial_plan():
    two_speed = Record(
        "incomplete two-speed",
        High_Speed_Gross_Rated_Cooling_COP=3.2,
        Low_Speed_Gross_Rated_Cooling_COP="Autosize",
    )
    water_to_air_hp = Record("water-to-air heat pump")
    vrf = Record("vrf fluid temperature control")

    planned, skipped = plan(FakeIDF(**{
        "COIL:COOLING:DX:TWOSPEED": [two_speed],
        "COIL:COOLING:WATERTOAIRHEATPUMP:PARAMETERESTIMATION": [water_to_air_hp],
        "AIRCONDITIONER:VARIABLEREFRIGERANTFLOW:FLUIDTEMPERATURECONTROL": [vrf],
    }), "COP", 0)

    assert planned == []
    assert skipped == [
        {
            "object_type": "COIL:COOLING:WATERTOAIRHEATPUMP:PARAMETERESTIMATION",
            "object_name": "water-to-air heat pump",
            "reason": "unsupported direct COP tuning object type in the native-IDF MVP",
        },
        {
            "object_type": "AIRCONDITIONER:VARIABLEREFRIGERANTFLOW:FLUIDTEMPERATURECONTROL",
            "object_name": "vrf fluid temperature control",
            "reason": "unsupported direct COP tuning object type in the native-IDF MVP",
        },
        {
            "object_type": "Coil:Cooling:DX:TwoSpeed",
            "object_name": "incomplete two-speed",
            "fields": ["High_Speed_Gross_Rated_Cooling_COP", "Low_Speed_Gross_Rated_Cooling_COP"],
            "reason": (
                "invalid source field(s) Low_Speed_Gross_Rated_Cooling_COP; "
                "expected a finite value greater than zero"
            ),
        },
    ]
    assert two_speed.High_Speed_Gross_Rated_Cooling_COP == 3.2


def test_he_and_fan_plan_supported_fields_and_make_unsupported_types_visible():
    fuel = Record("gas coil", Burner_Efficiency=0.8)
    electric = Record("electric coil", Efficiency=0.95)
    dx = Record("heat pump", Gross_Rated_Heating_COP=3.0)
    boiler = Record("boiler", Nominal_Thermal_Efficiency=0.9)
    water = Record("water coil", UFactorTimesAreaValue=20.0)
    fan = Record("supply fan", Fan_Total_Efficiency=0.7, Motor_Efficiency=0.9)
    system_fan = Record("modern fan", Fan_Total_Efficiency=0.75)
    idf = FakeIDF(
        **{
            "COIL:HEATING:FUEL": [fuel],
            "COIL:HEATING:ELECTRIC": [electric],
            "COIL:HEATING:DX:SINGLESPEED": [dx],
            "BOILER:HOTWATER": [boiler],
            "COIL:HEATING:WATER": [water],
            "FAN:CONSTANTVOLUME": [fan],
            "FAN:SYSTEMMODEL": [system_fan],
        }
    )

    heating_planned, heating_skipped = plan(idf, "HE", -10)
    fan_planned, fan_skipped = plan(idf, "FAN", 10)

    heating_after = {(change["object_name"], change["field"]): change["after"] for change in heating_planned}
    assert heating_after == pytest.approx({
        ("gas coil", "Burner_Efficiency"): 0.72,
        ("electric coil", "Efficiency"): 0.855,
        ("heat pump", "Gross_Rated_Heating_COP"): 2.7,
        ("boiler", "Nominal_Thermal_Efficiency"): 0.81,
    })
    assert heating_skipped == []  # Water coils are intentionally not HE tuning targets.
    assert [(change["object_name"], change["field"], change["after"]) for change in fan_planned] == [
        ("supply fan", "Fan_Total_Efficiency", 0.77)
    ]
    assert fan_skipped == [{
        "object_type": "FAN:SYSTEMMODEL",
        "object_name": "modern fan",
        "reason": "unsupported direct FAN tuning object type in the native-IDF MVP",
    }]
    assert fan.Motor_Efficiency == 0.9


def test_invalid_fractional_result_fails_instead_of_being_clipped():
    fan = Record("efficient fan", Fan_Total_Efficiency=0.95)

    with pytest.raises(ValueError, match=r"expected a finite value \(0, 1\]"):
        plan(FakeIDF(**{"FAN:ONOFF": [fan]}), "FAN", 10)

    assert fan.Fan_Total_Efficiency == 0.95
