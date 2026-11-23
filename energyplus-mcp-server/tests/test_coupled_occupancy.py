"""Focused no-simulation coverage for atomic coupled occupancy semantics."""

from __future__ import annotations

from energyplus_mcp_server.utils import coupled_occupancy


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
    return FakeIDF(
        Zone=[Record("Office", Floor_Area=100.0)],
        People=[Record(
            "Office people",
            Zone_or_ZoneList_or_Space_or_SpaceList_Name="Office",
            Number_of_People_Calculation_Method="People",
            Number_of_People=20.0,
        )],
        Lights=[
            Record(
                "Office density lights",
                Zone_or_ZoneList_or_Space_or_SpaceList_Name="Office",
                Design_Level_Calculation_Method="Watts/Area",
                Watts_per_Floor_Area=10.0,
            ),
            Record(
                "Office per-person lights",
                Zone_or_ZoneList_or_Space_or_SpaceList_Name="Office",
                Design_Level_Calculation_Method="Watts/Person",
                Watts_per_Person=7.0,
            ),
        ],
        ElectricEquipment=[Record(
            "Office plug loads",
            Zone_or_ZoneList_or_Space_or_SpaceList_Name="Office",
            Design_Level_Calculation_Method="EquipmentLevel",
            Design_Level=400.0,
        )],
    )


def test_coupled_occupancy_scales_people_and_nonperperson_loads_only():
    idf = _complete_idf()

    inspection = coupled_occupancy.inspect(idf)
    planned = coupled_occupancy.plan(idf, 0.5)

    assert inspection["coverage"] == "complete"
    assert inspection["supported"]
    assert inspection["applicable_targets"][0]["target_id"].startswith("OCC-RATIO:coupled:")
    assert coupled_occupancy.inspect(idf)["applicable_targets"] == inspection["applicable_targets"]
    assert planned["success"]
    assert planned["requested_value"] == planned["effective_value"] == 0.5
    changed = {(item["object_type"], item["field"]): item["after"] for item in planned["changes"]}
    assert all("object" not in item for item in planned["changes"])
    assert changed == {
        ("People", "Number_of_People"): 10.0,
        ("Lights", "Watts_per_Floor_Area"): 5.0,
        ("ElectricEquipment", "Design_Level"): 200.0,
    }
    assert planned["preserved_per_person_loads"] == [{
        "object_type": "Lights",
        "object_name": "Office per-person lights",
        "scope": "Office",
        "reason": "per-person load remains unchanged because People is scaled",
    }]
    assert idf.idfobjects["People"][0].Number_of_People == 20.0
    assert idf.idfobjects["Lights"][0].Watts_per_Floor_Area == 10.0
    assert idf.idfobjects["Lights"][1].Watts_per_Person == 7.0
    assert idf.idfobjects["ElectricEquipment"][0].Design_Level == 400.0


def test_incomplete_or_ambiguous_scope_precloses_the_atomic_operation(tmp_path):
    idf = _complete_idf()
    idf.idfobjects["ElectricEquipment"].append(Record(
        "Unresolved plug loads",
        Zone_or_ZoneList_or_Space_or_SpaceList_Name="Space 101",
        Design_Level_Calculation_Method="EquipmentLevel",
        Design_Level=100.0,
    ))
    source = tmp_path / "source.idf"
    source.write_text("source")
    output = tmp_path / "candidate.idf"

    result = coupled_occupancy.execute(
        idf,
        input_path=str(source),
        output_path=str(output),
        ratio=0.5,
        mode="apply",
    )

    assert result["coverage"] == "ambiguous"
    assert not result["success"] and not result["changed"]
    assert not output.exists()
    assert idf.idfobjects["People"][0].Number_of_People == 20.0
    assert idf.idfobjects["ElectricEquipment"][0].Design_Level == 400.0


def test_geometry_derived_floor_area_closes_absolute_people_density_bounds():
    idf = _complete_idf()
    idf.idfobjects["Zone"][0].Floor_Area = ""
    idf.idfobjects["BuildingSurface:Detailed"] = [Record(
        "Office floor",
        Zone_Name="Office",
        Surface_Type="Floor",
        Vertices=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0), (0.0, 10.0, 0.0)],
    )]

    planned = coupled_occupancy.plan(idf, 0.5)

    assert planned["coverage"] == "complete"
    assert planned["success"]
    people_change = next(item for item in planned["changes"] if item["object_type"] == "People")
    assert people_change["before"] == 20.0
    assert people_change["after"] == 10.0


def test_unproven_floor_area_keeps_absolute_people_density_bounds_ambiguous():
    idf = _complete_idf()
    idf.idfobjects["Zone"][0].Floor_Area = ""

    inspection = coupled_occupancy.inspect(idf)

    assert inspection["coverage"] == "ambiguous"
    assert any(
        item["reason"] == "absolute people requires a positive resolved zone floor area for density bounds"
        for item in inspection["ambiguous"]
    )


def test_apply_binds_source_hash_writes_distinct_output_and_preserves_audit_evidence(tmp_path):
    idf = _complete_idf()
    source = tmp_path / "source.idf"
    source.write_text("source")
    output = tmp_path / "candidate.idf"
    expected_hash = __import__("hashlib").sha256(source.read_bytes()).hexdigest()

    result = coupled_occupancy.execute(
        idf,
        input_path=str(source),
        output_path=str(output),
        ratio=0.5,
        mode="apply",
        expected_model_sha256=expected_hash,
    )

    assert result["success"] and result["changed"] and result["mode"] == "apply"
    assert result["input_sha256"] == expected_hash
    assert output.exists() and idf.saved_paths == [str(output)]
    assert result["before"][0]["before"] == 20.0
    assert result["after"][0]["after"] == 10.0
    assert idf.idfobjects["People"][0].Number_of_People == 10.0
    assert idf.idfobjects["Lights"][0].Watts_per_Floor_Area == 5.0


def test_failed_save_rolls_back_all_in_memory_field_changes(tmp_path):
    idf = _complete_idf()
    idf.fail_save = True
    source = tmp_path / "source.idf"
    source.write_text("source")

    result = coupled_occupancy.execute(
        idf,
        input_path=str(source),
        output_path=str(tmp_path / "candidate.idf"),
        ratio=0.5,
        mode="apply",
    )

    assert not result["success"]
    assert "failed to save" in result["error"]
    assert idf.idfobjects["People"][0].Number_of_People == 20.0
    assert idf.idfobjects["Lights"][0].Watts_per_Floor_Area == 10.0
    assert idf.idfobjects["ElectricEquipment"][0].Design_Level == 400.0
