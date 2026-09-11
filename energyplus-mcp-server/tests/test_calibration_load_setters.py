from types import SimpleNamespace

import pytest

from energyplus_mcp_server.utils.calibration_load_setters import (
    PARAMETERS,
    inspect,
    plan_set,
)


class Record:
    def __init__(self, name, **fields):
        self.Name = name
        for field, value in fields.items():
            setattr(self, field, value)


def _idf(**objects):
    return SimpleNamespace(idfobjects=objects)


def _zone(name="Office", area=100.0):
    return Record(name, Floor_Area=area, Multiplier=1)


def test_lpd_target_is_an_aggregate_density_and_zero_is_still_inspectable():
    density = Record(
        "density lights",
        Design_Level_Calculation_Method="Watts/Area",
        Zone_or_ZoneList_or_Space_or_SpaceList_Name="Office",
        Watts_per_Zone_Floor_Area=2.0,
    )
    fixed = Record(
        "fixed lights",
        Design_Level_Calculation_Method="LightingLevel",
        Zone_or_ZoneList_or_Space_or_SpaceList_Name="Office",
        Lighting_Level=300.0,
    )
    idf = _idf(Zone=[_zone()], Lights=[density, fixed])

    targets, skipped = inspect(idf, "LPD")
    planned, rejected = plan_set(idf, "LPD", 10.0, [targets[0]["target_id"]])

    assert PARAMETERS == ("LPD", "EPD", "OCD", "INF", "WIN-U", "WIN-SHGC")
    assert skipped == rejected == []
    assert targets[0]["value"] == 5.0
    assert targets[0]["units"] == "W/m2"
    assert targets[0]["basis"]["floor_area_m2"] == 100.0
    assert [(item["field"], item["after"]) for item in planned] == [
        ("Watts_per_Zone_Floor_Area", 4.0),
        ("Lighting_Level", 600.0),
    ]
    assert density.Watts_per_Zone_Floor_Area == 2.0
    assert fixed.Lighting_Level == 300.0

    zero = Record(
        "zero lights",
        Design_Level_Calculation_Method="Watts/Area",
        Zone_or_ZoneList_or_Space_or_SpaceList_Name="Office",
        Watts_per_Zone_Floor_Area=0.0,
    )
    zero_idf = _idf(Zone=[_zone()], Lights=[zero])
    zero_target = inspect(zero_idf, "LPD")[0][0]
    zero_plan, zero_rejected = plan_set(zero_idf, "LPD", 0.0)
    positive_plan, positive_rejected = plan_set(zero_idf, "LPD", 1.0)

    assert zero_target["value"] == 0.0 and zero_target["limitations"]
    assert zero_rejected == [] and zero_plan[0]["after"] == 0.0
    assert positive_plan == []
    assert "cannot be set to a nonzero" in positive_rejected[0]["reason"]


def test_epd_alias_and_ocd_inverse_zero_normalization_are_planned_without_mutation():
    equipment = Record(
        "plug load",
        Design_Level_Calculation_Method="Watts/Area",
        Zone_or_ZoneList_or_Space_or_SpaceList_Name="Office",
        Watts_per_Zone_Floor_Area=8.0,
    )
    people = Record(
        "occupants",
        Number_of_People_Calculation_Method="Area/Person",
        Zone_or_ZoneList_or_Space_or_SpaceList_Name="Office",
        Zone_Floor_Area_per_Person=10.0,
        People_per_Zone_Floor_Area="",
    )
    idf = _idf(Zone=[_zone()], ElectricEquipment=[equipment], People=[people])

    epd_target = inspect(idf, "EPD")[0][0]
    epd_plan, epd_rejected = plan_set(idf, "EPD", 16.0, [epd_target["target_id"]])
    ocd_target = inspect(idf, "OCD")[0][0]
    ocd_plan, ocd_rejected = plan_set(idf, "OCD", 0.0, [ocd_target["target_id"]])

    assert epd_target["value"] == 8.0 and epd_target["units"] == "W/m2"
    assert epd_rejected == []
    assert [(item["field"], item["after"]) for item in epd_plan] == [
        ("Watts_per_Zone_Floor_Area", 16.0),
    ]
    assert ocd_target["value"] == pytest.approx(0.1)
    assert ocd_target["units"] == "people/m2"
    assert ocd_rejected == []
    assert [(item["field"], item["after"]) for item in ocd_plan] == [
        ("Number_of_People_Calculation_Method", "People/Area"),
        ("People_per_Zone_Floor_Area", 0.0),
    ]
    assert equipment.Watts_per_Zone_Floor_Area == 8.0
    assert people.Zone_Floor_Area_per_Person == 10.0


def test_inf_uses_exterior_surface_area_even_for_the_92_alias():
    exterior_wall = Record(
        "Office exterior wall",
        Zone_Name="Office",
        Surface_Type="Wall",
        Outside_Boundary_Condition="Outdoors",
        Vertices=[[0, 0, 0], [10, 0, 0], [10, 0, 5], [0, 0, 5]],
    )
    interior_wall = Record(
        "Interior zone wall",
        Zone_Name="Interior",
        Surface_Type="Wall",
        Outside_Boundary_Condition="Surface",
        Vertices=[[0, 0, 0], [8, 0, 0], [8, 0, 4], [0, 0, 4]],
    )
    infiltration = Record(
        "Office infiltration",
        Design_Flow_Rate_Calculation_Method="Flow/ExteriorArea",
        Zone_or_ZoneList_Name="Both zones",
        Flow_per_Exterior_Surface_Area=0.002,
    )
    idf = _idf(
        Zone=[_zone(), _zone("Interior", 80.0)],
        ZoneList=[
            Record(
                "Both zones",
                fieldvalues=["ZoneList", "Both zones", "Office", "Interior"],
            )
        ],
        **{
            "BuildingSurface:Detailed": [exterior_wall, interior_wall],
            "ZoneInfiltration:DesignFlowRate": [infiltration],
        },
    )

    targets, skipped = inspect(idf, "INF")
    planned, rejected = plan_set(idf, "INF", 0.003, [targets[0]["target_id"]])

    assert skipped == rejected == []
    assert targets[0]["value"] == 0.002
    assert targets[0]["units"] == "m3/s/m2"
    assert targets[0]["basis"]["exterior_surface_area_m2"] == 50.0
    assert targets[0]["nonapplicable_zone_names"] == ["Interior"]
    assert planned[0]["field"] == "Flow_per_Exterior_Surface_Area"
    assert planned[0]["after"] == 0.003

    _, missing_geometry_skipped = inspect(
        _idf(
            Zone=[_zone(), _zone("Interior", 80.0)],
            ZoneList=[
                Record(
                    "Both zones",
                    fieldvalues=["ZoneList", "Both zones", "Office", "Interior"],
                )
            ],
            **{"ZoneInfiltration:DesignFlowRate": [infiltration]},
        ),
        "INF",
    )
    assert (
        "missing positive exterior_surface_area_m2"
        in missing_geometry_skipped[0]["reason"]
    )


def test_shared_zonelist_must_have_complete_equal_zone_density():
    shared = Record("Shared", fieldvalues=["ZoneList", "Shared", "A", "B"])
    shared_lights = Record(
        "shared lights",
        Design_Level_Calculation_Method="Watts/Area",
        Zone_or_ZoneList_or_Space_or_SpaceList_Name="Shared",
        Watts_per_Zone_Floor_Area=2.0,
    )
    idf = _idf(
        Zone=[_zone("A", 100), _zone("B", 200)],
        ZoneList=[shared],
        Lights=[shared_lights],
    )

    targets, skipped = inspect(idf, "LPD")
    assert skipped == [] and targets[0]["value"] == 2.0

    direct = Record(
        "A only",
        Design_Level_Calculation_Method="LightingLevel",
        Zone_or_ZoneList_or_Space_or_SpaceList_Name="A",
        Lighting_Level=100.0,
    )
    _, unequal_skipped = inspect(
        _idf(
            Zone=[_zone("A", 100), _zone("B", 200)],
            ZoneList=[shared],
            Lights=[shared_lights, direct],
        ),
        "LPD",
    )
    bad_list = Record("Bad", fieldvalues=["ZoneList", "Bad", "A", "Missing"])
    bad_lights = Record(
        "bad scope",
        Design_Level_Calculation_Method="Watts/Area",
        Zone_or_ZoneList_or_Space_or_SpaceList_Name="Bad",
        Watts_per_Zone_Floor_Area=2.0,
    )
    _, incomplete_skipped = inspect(
        _idf(Zone=[_zone("A")], ZoneList=[bad_list], Lights=[bad_lights]), "LPD"
    )

    assert "different canonical densities" in unequal_skipped[0]["reason"]
    assert "missing Zone member" in incomplete_skipped[0]["reason"]


def test_window_set_uses_safe_simple_glazing_and_rejects_unknown_target():
    glazing = Record("Simple glazing", UFactor=2.5, Solar_Heat_Gain_Coefficient=0.4)
    construction = Record("Window", Outside_Layer="Simple glazing", Layer_2="")
    idf = _idf(
        **{
            "WindowMaterial:SimpleGlazingSystem": [glazing],
            "Construction": [construction],
            "FenestrationSurface:Detailed": [
                Record(
                    "Office window", Surface_Type="Window", Construction_Name="Window"
                ),
            ],
        }
    )

    targets, skipped = inspect(idf, "WIN-U")
    planned, rejected = plan_set(idf, "WIN-U", 3.0, [targets[0]["target_id"]])
    unknown_plan, unknown_rejected = plan_set(
        idf, "WIN-U", 3.0, ["WIN-U:zones:missing"]
    )

    assert skipped == rejected == []
    assert targets[0]["value"] == 2.5 and targets[0]["units"] == "W/m2-K"
    assert planned[0]["field"] == "UFactor" and planned[0]["after"] == 3.0
    assert unknown_plan == [] and unknown_rejected == [
        {
            "target_id": "WIN-U:zones:missing",
            "reason": "unknown target_id",
        }
    ]
    assert glazing.UFactor == 2.5
