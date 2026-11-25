"""The generic object editor refuses unsafe edits instead of applying them partly or broadly."""

import asyncio
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from energyplus_mcp_server.utils.idf_modifier import IDFModifier, TargetError

REAL_IDD = os.getenv("EPLUS_IDD_PATH", "/app/software/EnergyPlusV26-1-0/Energy+.idd")
SAMPLE = Path(__file__).resolve().parents[1] / "sample_files" / "basic" / "5ZoneAirCooled.idf"
needs_idd = pytest.mark.skipif(not os.path.isfile(REAL_IDD), reason="EnergyPlus IDD not installed")


# -- targets (no IDD needed) -------------------------------------------------------------------


@pytest.mark.parametrize("target, expected", [
    ("all", ("all", "")), ("ALL", ("all", "")), (None, ("all", "")),
    ("name:SPACE1-1 Lights 1", ("name", "SPACE1-1 Lights 1")),
    ("Name: Foo:Bar ", ("name", "Foo:Bar")),
    ("zone:SPACE2-1", ("zone", "SPACE2-1")),
])
def test_targets_are_parsed(target, expected):
    assert IDFModifier.parse_target(target) == expected


@pytest.mark.parametrize("target", ["SPACE1-1 Lights 1", "name:", "space:SPACE1-1", "zone: ", "Lights*"])
def test_unrecognised_targets_are_refused(target):
    with pytest.raises(TargetError, match="Nothing was changed"):
        IDFModifier.parse_target(target)


# -- edits on a real model ---------------------------------------------------------------------


@pytest.fixture
def model(tmp_path):
    if not os.path.isfile(REAL_IDD):
        pytest.skip("EnergyPlus IDD not installed")
    from eppy.modeleditor import IDF

    if IDF.getiddname() is None:
        IDF.setiddname(REAL_IDD)
    path = tmp_path / "model.idf"
    shutil.copyfile(SAMPLE, path)
    return path


def _lights(path):
    from eppy.modeleditor import IDF

    return {o.Name: o for o in IDF(str(path)).idfobjects["LIGHTS"]}


def _modify(model, tmp_path, target, fields, **kwargs):
    out = tmp_path / "out.idf"
    result = IDFModifier().modify_objects(
        str(model), "Lights", [{"field": k, "value": v} for k, v in fields.items()],
        target=target, output_path=str(out), **kwargs)
    return result, out


@needs_idd
def test_unknown_target_changes_nothing(model, tmp_path):
    result, out = _modify(model, tmp_path, "SPACE1-1 Lights 1", {"Watts_per_Floor_Area": 1.0})

    assert result["success"] is False and "Unrecognised target" in result["error"]
    assert not out.exists()


@needs_idd
def test_names_and_zones_match_case_insensitively(model, tmp_path):
    by_name, _ = _modify(model, tmp_path, "name:space1-1 lights 1", {"Watts_per_Floor_Area": 1.0})
    by_zone = IDFModifier().modify_objects(
        str(model), "People", [{"field": "Fraction_Radiant", "value": 0.25}],
        target="zone:space2-1", output_path=str(tmp_path / "zone.idf"))

    assert by_name["success"] is True and by_name["matched_count"] == 1
    assert by_zone["success"] is True and by_zone["matched_count"] == 1


@needs_idd
def test_field_names_match_case_insensitively(model, tmp_path):
    result, out = _modify(model, tmp_path, "name:SPACE1-1 Lights 1", {"watts_per_floor_area": 4.5})

    assert result["success"] is True
    assert float(_lights(out)["SPACE1-1 Lights 1"].Watts_per_Floor_Area) == 4.5


@needs_idd
def test_one_invalid_field_saves_nothing(model, tmp_path):
    result, out = _modify(model, tmp_path, "name:SPACE1-1 Lights 1",
                          {"Watts_per_Floor_Area": 7.0, "Fraction_Radiant": 5.0})

    assert result["success"] is False and result["saved"] is False
    assert "Nothing was saved" in result["error"] and "out of range" in result["errors"][0]["error"]
    assert not out.exists()


@needs_idd
def test_invalid_choice_is_refused_even_with_force(model, tmp_path):
    result, out = _modify(model, tmp_path, "name:SPACE1-1 Lights 1",
                          {"Design_Level_Calculation_Method": "Bogus/Method"}, force=True)

    assert result["success"] is False and "not an allowed value" in result["errors"][0]["error"]
    assert "Watts/Area" in result["errors"][0]["error"] and not out.exists()


@needs_idd
def test_choices_compare_case_insensitively(model, tmp_path):
    result, _ = _modify(model, tmp_path, "name:SPACE1-1 Lights 1", {"Design_Level_Calculation_Method": "watts/area"})

    assert result["success"] is True


@needs_idd
def test_missing_reference_is_refused_unless_forced(model, tmp_path):
    refused, out = _modify(model, tmp_path, "name:SPACE1-1 Lights 1", {"Schedule_Name": "NO SUCH SCHEDULE"})
    assert refused["success"] is False and "ScheduleNames" in refused["errors"][0]["error"] and not out.exists()

    forced, out = _modify(model, tmp_path, "name:SPACE1-1 Lights 1", {"Schedule_Name": "NO SUCH SCHEDULE"}, force=True)
    assert forced["success"] is True and forced["warnings"]
    assert _lights(out)["SPACE1-1 Lights 1"].Schedule_Name == "NO SUCH SCHEDULE"


@needs_idd
def test_existing_reference_is_accepted(model, tmp_path):
    result, out = _modify(model, tmp_path, "name:SPACE1-1 Lights 1", {"Schedule_Name": "equip-1"})

    assert result["success"] is True and result["warnings"] == []


@needs_idd
def test_duplicate_name_is_refused(model, tmp_path):
    out = tmp_path / "added.idf"
    result = IDFModifier().add_object(str(model), "Lights", {
        "Name": "space1-1 LIGHTS 1", "Zone_or_ZoneList_or_Space_or_SpaceList_Name": "SPACE1-1",
        "Schedule_Name": "LIGHTS-1", "Design_Level_Calculation_Method": "Watts/Area", "Watts_per_Floor_Area": 3.0,
    }, output_path=str(out), force=True)

    assert result["success"] is False and "already exists" in result["errors"][0]["error"] and not out.exists()


@needs_idd
def test_add_with_a_bad_field_saves_nothing(model, tmp_path):
    out = tmp_path / "added.idf"
    result = IDFModifier().add_object(str(model), "Lights", {
        "Name": "SPACE1-1 Task Lights", "Zone_or_ZoneList_or_Space_or_SpaceList_Name": "SPACE1-1",
        "Schedule_Name": "LIGHTS-1", "Design_Level_Calculation_Method": "Watts/Area", "Fraction_Radiant": 9.0,
    }, output_path=str(out))

    assert result["success"] is False and not out.exists()


@needs_idd
def test_delete_of_an_object_in_use_is_refused_with_its_users(model, tmp_path):
    out = tmp_path / "deleted.idf"
    refused = IDFModifier().delete_objects(str(model), "Schedule:Compact", "name:LIGHTS-1", output_path=str(out))

    assert refused["success"] is False and not out.exists()
    entry = refused["errors"][0]
    assert entry["used_by_count"] == 5
    assert {(u["object_type"].upper(), u["field"]) for u in entry["used_by"]} == {("LIGHTS", "Schedule_Name")}

    forced = IDFModifier().delete_objects(str(model), "Schedule:Compact", "name:LIGHTS-1",
                                          output_path=str(out), force=True)
    assert forced["success"] is True and forced["warnings"][0]["used_by_count"] == 5 and out.exists()


@needs_idd
def test_rename_of_an_object_in_use_is_refused(model, tmp_path):
    out = tmp_path / "renamed.idf"
    result = IDFModifier().modify_objects(
        str(model), "Schedule:Compact", [{"field": "Name", "value": "LIGHTS-RENAMED"}],
        target="name:LIGHTS-1", output_path=str(out))

    assert result["success"] is False and "would break 5 reference" in result["errors"][0]["error"]
    assert not out.exists()


@needs_idd
def test_dry_run_reports_without_writing(model, tmp_path):
    result, out = _modify(model, tmp_path, "all", {"Watts_per_Floor_Area": 8.0}, dry_run=True)

    assert result["success"] is True and result["saved"] is False and result["mode"] == "dry_run"
    assert result["modified_count"] == 5 and not out.exists()


@needs_idd
def test_tool_never_overwrites_the_source(model):
    from energyplus_mcp_server.tools import idf_modification

    class FakeMCP:
        def tool(self, *args, **kwargs):
            def capture(fn):
                self.fn = fn
                return fn
            return capture

    config = SimpleNamespace(
        paths=SimpleNamespace(workspace_root=str(model.parent), sample_files_path=str(model.parent / "samples"),
                              work_dir=str(model.parent / "work"), uploads_dir=str(model.parent / "up"),
                              derived_models_dir=str(model.parent / "derived")),
        energyplus=SimpleNamespace(example_files_path=str(model.parent / "none")),
        transport=SimpleNamespace(transport="stdio"),
    )
    mcp = FakeMCP()
    idf_modification.register(mcp, object(), config)
    before = model.read_bytes()

    reply = json.loads(asyncio.run(mcp.fn(
        action="modify", idf_path=str(model), object_type="Lights", target="name:SPACE1-1 Lights 1",
        fields={"Watts_per_Floor_Area": 2.0}, output_path=str(model))))

    assert reply["success"] is False and "never overwritten" in reply["error"]
    assert model.read_bytes() == before


@needs_idd
def test_a_working_copy_in_derived_can_be_edited_in_place(model, tmp_path):
    from energyplus_mcp_server.tools import idf_modification

    derived = tmp_path / "work" / "models" / "derived"
    derived.mkdir(parents=True)
    copy = derived / "working.idf"
    shutil.copyfile(model, copy)

    class FakeMCP:
        def tool(self, *args, **kwargs):
            def capture(fn):
                self.fn = fn
                return fn
            return capture

    config = SimpleNamespace(
        paths=SimpleNamespace(workspace_root=str(tmp_path), sample_files_path=str(tmp_path / "samples"),
                              work_dir=str(tmp_path / "work"), uploads_dir=str(tmp_path / "work/models/uploads"),
                              derived_models_dir=str(derived)),
        energyplus=SimpleNamespace(example_files_path=str(tmp_path / "none")),
        transport=SimpleNamespace(transport="stdio"),
    )
    mcp = FakeMCP()
    idf_modification.register(mcp, object(), config)

    reply = json.loads(asyncio.run(mcp.fn(
        action="modify", idf_path=str(copy), object_type="Lights", target="name:SPACE1-1 Lights 1",
        fields={"Watts_per_Floor_Area": 2.5}, output_path=str(copy))))

    assert reply["success"] is True and reply["output_file"] == str(copy)
    assert float(_lights(copy)["SPACE1-1 Lights 1"].Watts_per_Floor_Area) == 2.5
