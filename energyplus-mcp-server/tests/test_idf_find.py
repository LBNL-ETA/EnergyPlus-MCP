"""Read-only object lookup: idf_modification(action="find")."""

import asyncio
import hashlib
import json
import os
from types import SimpleNamespace

import pytest

from energyplus_mcp_server.utils.idf_modifier import IDFModifier

REAL_IDD = os.getenv("EPLUS_IDD_PATH", "/app/software/EnergyPlusV26-1-0/Energy+.idd")
pytestmark = pytest.mark.skipif(not os.path.isfile(REAL_IDD), reason="EnergyPlus IDD not installed")

# Trimmed from ExampleFiles/5ZoneAirCooled.idf (EnergyPlus 26.1).
MODEL = """
Version,26.1;
Zone, SPACE1-1;
Schedule:Compact, Seasonal Reset Supply Air Temp Sch, Temperature, Through: 12/31, For: AllDays, Until: 24:00, 13.0;
Schedule:Compact, CW Loop Temp Schedule, Temperature, Through: 12/31, For: AllDays, Until: 24:00, 6.67;
Schedule:Compact, OCCUPY-1, Fraction, Through: 12/31, For: AllDays, Until: 24:00, 1.0;
Lights, SPACE1-1 Lights 1, SPACE1-1, OCCUPY-1, LightingLevel, 1584;
NodeList, Main Branch SetPoint Node List, Mixed Air Node 1, Main Cooling Coil 1 Outlet Node, Main Heating Coil 1 Outlet Node;
SetpointManager:Scheduled, Supply Air Temp Manager 1, Temperature, Seasonal Reset Supply Air Temp Sch, VAV Sys 1 Outlet Node;
SetpointManager:Scheduled, Chilled Water Loop Setpoint Manager, Temperature, CW Loop Temp Schedule, CW Supply Outlet Node;
SetpointManager:MixedAir, Mixed Air Temp Manager 1, Temperature, VAV Sys 1 Outlet Node, Main Heating Coil 1 Outlet Node, VAV Sys 1 Outlet Node, Main Branch SetPoint Node List;
"""


@pytest.fixture(scope="module", autouse=True)
def idd():
    from eppy.modeleditor import IDF

    if IDF.getiddname() is None:
        IDF.setiddname(REAL_IDD)


@pytest.fixture
def model(tmp_path):
    path = tmp_path / "model.idf"
    path.write_text(MODEL)
    return str(path)


def digest(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def test_find_by_wildcard_type(model):
    before = digest(model)
    result = IDFModifier().find_objects(model, object_type="setpointmanager:*")
    assert result["success"] and result["total_matches"] == 3
    assert result["type_counts"] == {"SetpointManager:Scheduled": 2, "SetpointManager:MixedAir": 1}
    first = result["objects"][0]
    assert first["type"] == "SetpointManager:Scheduled"
    # eppy field names, as idf_modification(action="modify") accepts them.
    assert first["fields"]["Setpoint_Node_or_NodeList_Name"] == "VAV Sys 1 Outlet Node"
    assert digest(model) == before  # read only


def test_find_by_reference_is_case_insensitive(model):
    result = IDFModifier().find_objects(model, references="cw supply outlet node")
    assert [(o["type"], o["name"]) for o in result["objects"]] == [
        ("SetpointManager:Scheduled", "Chilled Water Loop Setpoint Manager"),
    ]
    assert result["objects"][0]["matched_fields"] == ["Setpoint_Node_or_NodeList_Name"]
    assert result["objects"][0]["role"] == "references"

    schedule = IDFModifier().find_objects(model, references="OCCUPY-1")
    assert [(o["type"], o["role"], o["matched_fields"]) for o in schedule["objects"]] == [
        ("Schedule:Compact", "defines", ["Name"]),
        ("Lights", "references", ["Schedule_Name"]),
    ]


def test_reference_follows_node_lists_even_with_type_filter(model):
    result = IDFModifier().find_objects(
        model, object_type="SetpointManager:*", references="Main Cooling Coil 1 Outlet Node"
    )
    assert result["total_matches"] == 1
    hit = result["objects"][0]
    assert hit["name"] == "Mixed Air Temp Manager 1"
    assert hit["via"] == "Main Branch SetPoint Node List"

    unfiltered = IDFModifier().find_objects(model, references="Main Cooling Coil 1 Outlet Node")
    assert unfiltered["type_counts"] == {"NodeList": 1, "SetpointManager:MixedAir": 1}


def test_name_filter_limit_and_empty_results(model):
    modifier = IDFModifier()
    named = modifier.find_objects(model, object_type="Schedule:Compact", name_contains="loop")
    assert [o["name"] for o in named["objects"]] == ["CW Loop Temp Schedule"]

    limited = modifier.find_objects(model, object_type="Schedule:Compact", limit=2)
    assert limited["total_matches"] == 3 and limited["returned"] == 2 and limited["truncated"]

    none = modifier.find_objects(model, object_type="SetpointManager:*", references="No Such Node")
    assert none["success"] and none["total_matches"] == 0 and "not changed" in none["note"]


def test_bad_queries(model):
    modifier = IDFModifier()
    typo = modifier.find_objects(model, object_type="SetpointManagr:Coldst")
    assert not typo["success"] and "SetpointManager:Coldest" in typo["error"]
    assert not modifier.find_objects(model)["success"]


def test_tool_find_action(model, tmp_path):
    from energyplus_mcp_server.tools import idf_modification as tool_module

    tools = {}

    class FakeMCP:
        def tool(self, *args, **kwargs):
            def decorator(fn):
                tools[fn.__name__] = fn
                return fn
            return decorator

    config = SimpleNamespace(paths=SimpleNamespace(
        workspace_root=str(tmp_path), sample_files_path=str(tmp_path / "sample_files"),
        work_dir=str(tmp_path / "work"), uploads_dir=str(tmp_path / "work" / "models" / "uploads"),
        derived_models_dir=str(tmp_path / "work" / "models" / "derived"),
    ), energyplus=SimpleNamespace(example_files_path=str(tmp_path / "none")))
    tool_module.register(FakeMCP(), object(), config)
    tool = tools["idf_modification"]

    found = json.loads(asyncio.run(tool(action="find", idf_path=model, references="CW Supply Outlet Node")))
    assert found["action"] == "find" and found["total_matches"] == 1
    caps = json.loads(asyncio.run(tool(action="capabilities")))
    assert caps["actions"][0]["name"] == "find"
    missing = json.loads(asyncio.run(tool(action="find", idf_path=model)))
    assert "error" in missing
