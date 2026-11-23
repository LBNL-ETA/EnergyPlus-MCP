from types import SimpleNamespace

import pytest

from energyplus_mcp_server.utils.calibration_loads import PARAMETERS, plan


def _idf(**objects):
    return SimpleNamespace(idfobjects=objects)


def test_parameters_and_active_load_fields_are_planned_without_mutating_objects():
    equipment = SimpleNamespace(
        Name="Office plugs",
        Design_Level_Calculation_Method="watts/area",
        Watts_per_Floor_Area=8.0,
    )
    people = SimpleNamespace(
        Name="Office occupants",
        Number_of_People_Calculation_Method="Area/Person",
        Floor_Area_per_Person=10.0,
    )
    infiltration = SimpleNamespace(
        Name="Office infiltration",
        Design_Flow_Rate_Calculation_Method="Flow/ExteriorArea",
        Flow_Rate_per_Exterior_Surface_Area=0.002,
    )
    idf = _idf(
        ElectricEquipment=[equipment],
        People=[people],
        **{"ZoneInfiltration:DesignFlowRate": [infiltration]},
    )

    epd, epd_skipped = plan(idf, "EPD", 20)
    ocd, ocd_skipped = plan(idf, "OCD", 25)
    inf, inf_skipped = plan(idf, "INF", -10)

    assert PARAMETERS == ("EPD", "OCD", "INF", "WIN-U", "WIN-SHGC")
    assert not epd_skipped and epd[0]["field"] == "Watts_per_Floor_Area"
    assert epd[0]["before"] == 8.0 and epd[0]["after"] == 9.6
    assert not ocd_skipped and ocd[0]["field"] == "Floor_Area_per_Person"
    assert ocd[0]["before"] == 10.0 and ocd[0]["after"] == 8.0
    assert not inf_skipped and inf[0]["field"] == "Flow_Rate_per_Exterior_Surface_Area"
    assert inf[0]["before"] == 0.002 and inf[0]["after"] == pytest.approx(0.0018)
    assert equipment.Watts_per_Floor_Area == 8.0
    assert people.Floor_Area_per_Person == 10.0
    assert infiltration.Flow_Rate_per_Exterior_Surface_Area == 0.002


def test_area_per_person_rejects_minus_100_with_a_skip_instead_of_dividing_by_zero():
    people = SimpleNamespace(
        Name="Office occupants",
        Number_of_People_Calculation_Method="People/Area",
        People_per_Floor_Area=0.1,
    )
    inverse_people = SimpleNamespace(
        Name="Lobby occupants",
        Number_of_People_Calculation_Method="Area/Person",
        Floor_Area_per_Person=10.0,
    )

    planned, skipped = plan(_idf(People=[people, inverse_people]), "OCD", -100)

    assert planned[0]["object"] is people
    assert planned[0]["after"] == 0.0
    assert skipped == [{
        "object_type": "People",
        "object_name": "Lobby occupants",
        "reason": "percentage -100 is invalid for Area/Person because its field scales inversely",
        "field": "Floor_Area_per_Person",
        "calculation_method": "Area/Person",
    }]
    assert inverse_people.Floor_Area_per_Person == 10.0


def test_invalid_load_sources_and_alternate_infiltration_objects_prevent_complete_coverage():
    invalid_equipment = SimpleNamespace(
        Name="Invalid equipment",
        Design_Level_Calculation_Method="EquipmentLevel",
        Design_Level=-1.0,
    )
    ite = SimpleNamespace(Name="Server rack")
    exterior_wall_infiltration = SimpleNamespace(
        Name="Wall infiltration",
        Design_Flow_Rate_Calculation_Method="Flow/ExteriorWallArea",
        Flow_Rate_per_Exterior_Surface_Area=0.002,
    )
    effective_leakage_area = SimpleNamespace(Name="ELA infiltration")
    idf = _idf(**{
        "ElectricEquipment": [invalid_equipment],
        "ElectricEquipment:ITE:AirCooled": [ite],
        "ZoneInfiltration:DesignFlowRate": [exterior_wall_infiltration],
        "ZoneInfiltration:EffectiveLeakageArea": [effective_leakage_area],
    })

    epd_planned, epd_skipped = plan(idf, "EPD", 0)
    inf_planned, inf_skipped = plan(idf, "INF", 0)

    assert epd_planned == []
    assert {item["object_name"] for item in epd_skipped} == {"Invalid equipment", "Server rack"}
    assert inf_planned[0]["field"] == "Flow_Rate_per_Exterior_Surface_Area"
    assert inf_planned[0]["after"] == 0.002
    assert inf_skipped == [{
        "object_type": "ZoneInfiltration:EffectiveLeakageArea",
        "object_name": "ELA infiltration",
        "reason": "only ZoneInfiltration:DesignFlowRate is supported by the INF MVP",
    }]


def test_energyplus_92_schema_aliases_select_the_field_present_on_the_idf_object():
    equipment = SimpleNamespace(
        Name="Office plugs",
        Design_Level_Calculation_Method="Watts/Area",
        Watts_per_Zone_Floor_Area=8.0,
    )
    people_per_area = SimpleNamespace(
        Name="Office occupants",
        Number_of_People_Calculation_Method="People/Area",
        People_per_Zone_Floor_Area=0.1,
    )
    area_per_person = SimpleNamespace(
        Name="Lobby occupants",
        Number_of_People_Calculation_Method="Area/Person",
        Zone_Floor_Area_per_Person=10.0,
    )
    flow_per_area = SimpleNamespace(
        Name="Floor-area infiltration",
        Design_Flow_Rate_Calculation_Method="Flow/Area",
        Flow_per_Zone_Floor_Area=0.002,
    )
    flow_per_exterior = SimpleNamespace(
        Name="Exterior-area infiltration",
        Design_Flow_Rate_Calculation_Method="Flow/ExteriorArea",
        Flow_per_Exterior_Surface_Area=0.003,
    )
    idf = _idf(**{
        "ElectricEquipment": [equipment],
        "People": [people_per_area, area_per_person],
        "ZoneInfiltration:DesignFlowRate": [flow_per_area, flow_per_exterior],
    })

    epd, epd_skipped = plan(idf, "EPD", 10)
    ocd, ocd_skipped = plan(idf, "OCD", 10)
    inf, inf_skipped = plan(idf, "INF", 10)

    assert not epd_skipped and epd[0]["field"] == "Watts_per_Zone_Floor_Area"
    assert {item["field"] for item in ocd} == {
        "People_per_Zone_Floor_Area",
        "Zone_Floor_Area_per_Person",
    }
    assert not ocd_skipped
    assert {item["field"] for item in inf} == {
        "Flow_per_Zone_Floor_Area",
        "Flow_per_Exterior_Surface_Area",
    }
    assert not inf_skipped


def test_window_plan_targets_only_actual_simple_glazing_windows_and_flags_layered_windows():
    simple_glazing = SimpleNamespace(
        Name="Simple glazing",
        UFactor=2.5,
        Solar_Heat_Gain_Coefficient=0.4,
    )
    simple_construction = SimpleNamespace(Name="Simple window", Outside_Layer="Simple glazing", Layer_2="")
    layered_construction = SimpleNamespace(Name="Layered window", Outside_Layer="Outer glass", Layer_2="Air gap")
    idf = _idf(**{
        "WindowMaterial:SimpleGlazingSystem": [simple_glazing],
        "Construction": [simple_construction, layered_construction],
        "FenestrationSurface:Detailed": [
            SimpleNamespace(Name="Office window", Surface_Type="Window", Construction_Name="Simple window"),
            SimpleNamespace(Name="Layered office window", Surface_Type="Window", Construction_Name="Layered window"),
            SimpleNamespace(Name="Door", Surface_Type="GlassDoor", Construction_Name="Layered window"),
        ],
    })

    planned, skipped = plan(idf, "WIN-U", 20)

    assert len(planned) == 1
    assert planned[0]["object"] is simple_glazing
    assert planned[0]["field"] == "UFactor"
    assert planned[0]["before"] == 2.5 and planned[0]["after"] == 3.0
    assert skipped == [{
        "object_type": "Construction",
        "object_name": "Layered window",
        "reason": "window construction is layered or does not use a single WindowMaterial:SimpleGlazingSystem",
    }]
    assert simple_glazing.UFactor == 2.5


def test_window_shgc_candidate_outside_its_physical_range_is_reported_as_a_skip():
    glazing = SimpleNamespace(Name="Simple glazing", UFactor=2.5, Solar_Heat_Gain_Coefficient=0.95)
    construction = SimpleNamespace(Name="Window", Outside_Layer="Simple glazing", Layer_2="")
    idf = _idf(**{
        "WindowMaterial:SimpleGlazingSystem": [glazing],
        "Construction": [construction],
        "FenestrationSurface:Detailed": [
            SimpleNamespace(Name="Window", Surface_Type="Window", Construction_Name="Window"),
        ],
    })

    planned, skipped = plan(idf, "WIN-SHGC", 10)

    assert planned == []
    assert skipped[0]["object_type"] == "WindowMaterial:SimpleGlazingSystem"
    assert skipped[0]["field"] == "Solar_Heat_Gain_Coefficient"
    assert "SHGC must be greater than 0 and no more than 1" in skipped[0]["reason"]
