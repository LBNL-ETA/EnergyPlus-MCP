"""Linear-time schedule field access and the cached EnergyPlus version.

Capability checks on a small DOE office took ~105 s: ``_field_names`` removed
duplicates with a list-membership test, and reading every field through Eppy
attributes scans the field list per name. Both are quadratic in the field
count of large ``Schedule:Compact`` objects. These tests pin the results to
Eppy's own attribute access.
"""

import os
from types import SimpleNamespace

import pytest

from energyplus_mcp_server.energyplus_tools import EnergyPlusManager
from energyplus_mcp_server.utils.schedule_graph import _field_names, _field_values

REAL_IDD = os.getenv("EPLUS_IDD_PATH", "/app/software/EnergyPlusV26-1-0/Energy+.idd")
needs_idd = pytest.mark.skipif(not os.path.isfile(REAL_IDD), reason="EnergyPlus IDD not installed")


def test_field_names_keep_first_occurrence_order_and_skip_key():
    obj = SimpleNamespace(fieldnames=["key", "Name", "Field_1", "Name", "Field_2", "Field_1"])
    assert _field_names(obj) == ["Name", "Field_1", "Field_2"]


def test_field_values_fall_back_to_attributes_for_plain_objects():
    obj = SimpleNamespace(Name="Office", Value=3)
    assert _field_values(obj, ["Name", "Value", "Missing"]) == ["Office", 3, None]


@needs_idd
def test_field_values_match_eppy_attribute_access(tmp_path):
    from eppy.modeleditor import IDF

    IDF.setiddname(REAL_IDD, testing=True)
    fields = []
    for day in range(200):
        fields += [f"Through: {1 + day % 12:d}/28", "For: AllDays", "Until: 08:00", "0.1",
                   "Until: 24:00", f"{0.5 + day / 1000:.3f}"]
    text = (
        "Version, 26.1;\n"
        "ScheduleTypeLimits, Fraction, 0, 1, Continuous;\n"
        "Schedule:Compact, Big schedule, Fraction,\n  "
        + ",\n  ".join(fields) + ";\n"
        "Lights, Office lights, Zone 1, Big schedule, Watts/Area, , 10, , 0, 0.2, 0.2;\n"
    )
    path = tmp_path / "model.idf"
    path.write_text(text)
    idf = IDF(str(path))
    for obj in (idf.idfobjects["SCHEDULE:COMPACT"][0], idf.idfobjects["LIGHTS"][0]):
        names = _field_names(obj)
        assert len(names) == len(set(names))
        # Includes IDD fields past the stored values, which Eppy returns as "".
        assert _field_values(obj, names) == [getattr(obj, name) for name in names]
    assert len(_field_names(idf.idfobjects["SCHEDULE:COMPACT"][0])) > len(fields)


def _manager(tmp_path, monkeypatch, executable):
    manager = EnergyPlusManager.__new__(EnergyPlusManager)
    manager.config = SimpleNamespace(energyplus=SimpleNamespace(executable_path=str(executable)))
    calls = []

    def query(path):
        calls.append(path)
        return "26.1.0"

    monkeypatch.setattr(manager, "_query_runtime_energyplus_version", query)
    return manager, calls


def test_runtime_version_is_queried_once_per_executable(tmp_path, monkeypatch):
    executable = tmp_path / "energyplus"
    executable.write_text("#!/bin/sh\n")
    manager, calls = _manager(tmp_path, monkeypatch, executable)

    assert manager._runtime_energyplus_version() == "26.1.0"
    assert manager._runtime_energyplus_version() == "26.1.0"
    assert len(calls) == 1

    stat = executable.stat()
    os.utime(executable, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    manager._runtime_energyplus_version()
    assert len(calls) == 2


def test_runtime_version_is_not_cached_without_a_file(tmp_path, monkeypatch):
    manager, calls = _manager(tmp_path, monkeypatch, tmp_path / "missing-energyplus")
    manager._runtime_energyplus_version()
    manager._runtime_energyplus_version()
    assert len(calls) == 2
