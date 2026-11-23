"""Focused schedule graph/editor contracts using synthetic IDF-shaped objects."""

from __future__ import annotations

from pathlib import Path

from energyplus_mcp_server.utils.schedule_graph import ScheduleEditor, ScheduleGraph


class Record:
    def __init__(self, **fields):
        object.__setattr__(self, "fieldnames", list(fields))
        for name, value in fields.items():
            object.__setattr__(self, name, value)

    def __setattr__(self, name, value):
        if name != "fieldnames" and name not in self.fieldnames:
            self.fieldnames.append(name)
        object.__setattr__(self, name, value)


class FakeIDF:
    """Small eppy-shaped model; ``save`` makes candidate output inspectable."""

    def __init__(self, **objects):
        self.idfobjects = objects

    def newidfobject(self, raw_key):
        for key in self.idfobjects:
            if key.casefold() == str(raw_key).casefold():
                record = Record(Name="")
                self.idfobjects[key].append(record)
                return record
        record = Record(Name="")
        self.idfobjects.setdefault(raw_key, []).append(record)
        return record

    def save(self, path):
        rows = []
        for key in sorted(self.idfobjects):
            for obj in self.idfobjects[key]:
                values = ", ".join(f"{field}={getattr(obj, field, '')}" for field in obj.fieldnames)
                rows.append(f"{key}: {values}")
        Path(path).write_text("\n".join(rows))


def _hourly(name, values=None):
    values = values or [0.0] * 8 + [1.0] * 8 + [0.0] * 8
    return Record(
        Name=name,
        **{f"Hour_{hour}_Value": value for hour, value in enumerate(values, start=1)},
    )


def _graph_idf():
    weekday = _hourly("Weekday day")
    weekend = Record(
        Name="Weekend day",
        Minutes_per_Item=60,
        **{f"Value_{index}": 0.2 for index in range(1, 25)},
    )
    week = Record(
        Name="Week pattern",
        Sunday_ScheduleDay_Name="Weekend day",
        Monday_ScheduleDay_Name="Weekday day",
        Tuesday_ScheduleDay_Name="Weekday day",
        Wednesday_ScheduleDay_Name="Weekday day",
        Thursday_ScheduleDay_Name="Weekday day",
        Friday_ScheduleDay_Name="Weekday day",
        Saturday_ScheduleDay_Name="Weekend day",
        Holiday_ScheduleDay_Name="Weekend day",
    )
    compact_week = Record(
        Name="Compact week",
        DayType_List_1="AllDays",
        ScheduleDay_Name_1="Weekday day",
    )
    annual = Record(
        Name="Annual lights",
        ScheduleWeek_Name_1="Week pattern",
        Start_Month_1=1,
        Start_Day_1=1,
        End_Month_1=12,
        End_Day_1=31,
    )
    return FakeIDF(
        **{
            "Schedule:Day:Hourly": [weekday],
            "Schedule:Day:List": [weekend],
            "Schedule:Week:Daily": [week],
            "Schedule:Week:Compact": [compact_week],
            "Schedule:Year": [annual],
            "Lights": [Record(Name="Open office lights", Schedule_Name="Annual lights")],
            "ElectricEquipment": [Record(Name="Open office plug", Schedule_Name="Annual lights")],
            "AirLoopHVAC": [Record(Name="Main air loop", Availability_Schedule_Name="Compact week")],
        }
    )


def test_graph_resolves_nested_year_week_day_references_and_semantic_consumers():
    idf = _graph_idf()
    graph = ScheduleGraph(idf)
    inspection = graph.inspect()

    annual = graph.entry_for_name("Annual lights")
    assert annual is not None
    names = {graph.entries[target_id].name for target_id in graph.descendants(annual.target_id)}
    assert names == {"Annual lights", "Week pattern", "Weekday day", "Weekend day"}
    assert {consumer.role for consumer in graph.consumers.values()} == {
        "lighting", "electric_equipment", "hvac_availability"
    }
    assert graph.normalized_profile(graph.entry_for_name("Week pattern"))["references"]
    assert graph.normalized_profile(graph.entry_for_name("Weekday day"))["valid"] is True
    assert len(inspection["schedules"]) == 5

    hvac = graph.inspect("hvac_availability")
    assert [consumer["object_name"] for consumer in hvac["consumers"]] == ["Main air loop"]
    assert {item["schedule_name"] for item in hvac["schedules"]} == {"Compact week", "Weekday day"}


def test_selected_consumer_clone_on_write_changes_only_its_schedule_branch(tmp_path):
    source = tmp_path / "source.idf"
    source.write_text("synthetic source")
    output = tmp_path / "candidate.idf"
    shared = _hourly("Shared availability")
    idf = FakeIDF(
        **{
            "Schedule:Day:Hourly": [shared],
            "Lights": [Record(Name="Lights A", Schedule_Name="Shared availability")],
            "ElectricEquipment": [Record(Name="Equipment B", Schedule_Name="Shared availability")],
        }
    )
    graph = ScheduleGraph(idf)
    lighting = next(item.public() for item in graph.consumers.values() if item.role == "lighting")
    source_hash = __import__("hashlib").sha256(source.read_bytes()).hexdigest()

    response = ScheduleEditor(idf_loader=lambda _path: idf).edit(
        str(source), [lighting], "scale", 0.5, output_file=str(output),
        clone_on_write=True, expected_model_sha256=source_hash, mode="apply",
    )

    lights = idf.idfobjects["Lights"][0]
    equipment = idf.idfobjects["ElectricEquipment"][0]
    assert response["success"] is True
    assert response["coverage"] == "complete"
    assert response["shared_objects"][0]["clone_on_write"]["decision"] == "clone"
    assert lights.Schedule_Name != "Shared availability"
    assert equipment.Schedule_Name == "Shared availability"
    original = next(item for item in idf.idfobjects["Schedule:Day:Hourly"] if item.Name == "Shared availability")
    clone = next(item for item in idf.idfobjects["Schedule:Day:Hourly"] if item.Name == lights.Schedule_Name)
    assert original.Hour_9_Value == 1.0
    assert clone.Hour_9_Value == 0.5
    assert source.read_text() == "synthetic source"
    assert output.is_file() and lights.Schedule_Name in output.read_text()


def test_bounds_dry_run_hash_binding_and_distinct_output_protection(tmp_path):
    source = tmp_path / "source.idf"
    source.write_text("unchanged input")
    constant = Record(Name="Fraction schedule", Schedule_Type_Limits_Name="Fraction", Hourly_Value=0.8)
    idf = FakeIDF(
        **{
            "ScheduleTypeLimits": [Record(Name="Fraction", Lower_Limit_Value=0.0, Upper_Limit_Value=1.0, Unit_Type="Dimensionless")],
            "Schedule:Constant": [constant],
            "Lights": [Record(Name="Lights", Schedule_Name="Fraction schedule")],
        }
    )
    graph = ScheduleGraph(idf)
    reference = next(item.public() for item in graph.consumers.values())
    editor = ScheduleEditor(idf_loader=lambda _path: idf)

    dry_run = editor.edit(str(source), [reference], "scale", 2.0, mode="dry_run")
    assert dry_run["success"] is False
    assert dry_run["coverage"] == "none"
    assert dry_run["supported"] is False
    assert "above upper bound" in dry_run["skipped"][0]["reason"]
    assert constant.Hourly_Value == 0.8

    mismatch = editor.edit(
        str(source), [reference], "scale", 1.0, output_file=str(tmp_path / "candidate.idf"),
        expected_model_sha256="not-the-input", mode="apply",
    )
    assert mismatch["success"] is False
    assert "expected_model_sha256" in mismatch["skipped"][0]["reason"]

    protected = editor.edit(
        str(source), [reference], "scale", 1.0, output_file=str(source), mode="apply"
    )
    assert protected["success"] is False
    assert "distinct IDF" in protected["skipped"][0]["reason"]


def test_shift_and_extension_are_dry_run_only_for_complete_hourly_profiles(tmp_path):
    source = tmp_path / "source.idf"
    source.write_text("shift source")
    idf = FakeIDF(
        **{
            "Schedule:Day:Hourly": [_hourly("Occupied")],
            "Lights": [Record(Name="Lights", Schedule_Name="Occupied")],
        }
    )
    graph = ScheduleGraph(idf)
    reference = next(item.public() for item in graph.consumers.values())
    response = ScheduleEditor(idf_loader=lambda _path: idf).edit(
        str(source), [reference], "shift_or_extend",
        {"shift_hours": 1, "extend_hours": 1, "extension_side": "end"},
        mode="dry_run",
    )

    assert response["success"] is True
    assert response["coverage"] == "complete"
    assert response["changed"] is True
    assert idf.idfobjects["Schedule:Day:Hourly"][0].Hour_9_Value == 1.0


def test_compact_and_interval_value_fields_scale_without_reformatting(tmp_path):
    source = tmp_path / "source.idf"
    source.write_text("compact source")
    compact = Record(
        Name="Compact",
        Field_1="Through: 12/31",
        Field_2="For: AllDays",
        Field_3="Until: 08:00",
        Field_4=0.0,
        Field_5="Until: 24:00",
        Field_6=1.0,
    )
    interval = Record(
        Name="Interval",
        Time_1="08:00",
        Value_Until_Time_1=0.0,
        Time_2="24:00",
        Value_Until_Time_2=1.0,
    )
    idf = FakeIDF(
        **{
            "Schedule:Compact": [compact],
            "Schedule:Day:Interval": [interval],
            "Lights": [Record(Name="Compact lights", Schedule_Name="Compact")],
            "ElectricEquipment": [Record(Name="Interval plug", Schedule_Name="Interval")],
        }
    )
    graph = ScheduleGraph(idf)
    references = [item.public() for item in graph.consumers.values()]
    response = ScheduleEditor(idf_loader=lambda _path: idf).edit(
        str(source), references, "scale", 0.5, mode="dry_run"
    )

    assert response["coverage"] == "complete"
    evidence = {(item["schedule_name"], item["field"], item["value"]) for item in response["after"]}
    assert ("Compact", "Field_6", 0.5) in evidence
    assert ("Interval", "Value_Until_Time_2", 0.5) in evidence
    assert compact.Field_3 == "Until: 08:00"


def test_schedule_file_is_reported_unsupported_and_never_mutated(tmp_path):
    source = tmp_path / "source.idf"
    source.write_text("file schedule source")
    file_schedule = Record(Name="External schedule", File_Name="profile.csv", Column_Number=2)
    idf = FakeIDF(
        **{
            "Schedule:File": [file_schedule],
            "Lights": [Record(Name="File lights", Schedule_Name="External schedule")],
        }
    )
    reference = next(item.public() for item in ScheduleGraph(idf).consumers.values())
    response = ScheduleEditor(idf_loader=lambda _path: idf).edit(
        str(source), [reference], "delta", 1.0, mode="dry_run"
    )

    assert response["success"] is False
    assert response["coverage"] == "none"
    assert "Schedule:File is unsupported" in response["skipped"][0]["reason"]
    assert file_schedule.File_Name == "profile.csv"
