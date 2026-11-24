"""Duplicate handling for Output:Meter requests.

EnergyPlus matches meter names and frequencies case-insensitively, and a full
meter (Output:Meter) also writes the .mtr file of its MeterFileOnly variant.
Requesting both for one meter makes EnergyPlus warn and report it twice.
"""

from types import SimpleNamespace

from energyplus_mcp_server.energyplus_tools import EnergyPlusManager
from energyplus_mcp_server.utils import output_meters
from energyplus_mcp_server.utils.output_meters import OutputMeterManager


class _FakeIDF:
    """The slice of eppy's IDF used by the meter code."""

    def __init__(self, *objects):
        self.idfobjects: dict[str, list] = {}
        for meter_type, name, frequency in objects:
            self.newidfobject(meter_type, Key_Name=name, Reporting_Frequency=frequency)
        self.saved_to = None

    def newidfobject(self, key, **fields):
        obj = SimpleNamespace(key=key, **fields)
        self.idfobjects.setdefault(key, []).append(obj)
        return obj

    def removeidfobject(self, obj):
        self.idfobjects[obj.key].remove(obj)

    def save(self, path):
        self.saved_to = path

    def meters(self):
        return sorted(
            (key, obj.Key_Name, obj.Reporting_Frequency)
            for key, objects in self.idfobjects.items()
            if key.startswith("Output:Meter")
            for obj in objects
        )


def _manager(monkeypatch, configured):
    manager = OutputMeterManager(SimpleNamespace())
    monkeypatch.setattr(
        manager,
        "_get_configured_meters_cached",
        lambda _path: [
            {"meter_type": t, "key_name": n, "reporting_frequency": f} for t, n, f in configured
        ],
    )
    return manager


def _spec(name, frequency, meter_type="Output:Meter"):
    return {"meter_name": name, "frequency": frequency, "meter_type": meter_type}


def test_same_meter_in_other_case_is_a_duplicate(monkeypatch):
    manager = _manager(monkeypatch, [("Output:Meter", "electricity:facility", "monthly")])

    report = manager.check_duplicate_meters("m.idf", [_spec("Electricity:Facility", "Monthly")])

    assert report["duplicates_found"] == 1
    assert report["new_meters"] == []


def test_file_only_request_is_covered_by_existing_full_meter(monkeypatch):
    manager = _manager(monkeypatch, [("Output:Meter", "Electricity:Facility", "Monthly")])

    report = manager.check_duplicate_meters(
        "m.idf", [_spec("Electricity:Facility", "monthly", "Output:Meter:MeterFileOnly")]
    )

    assert report["duplicates_found"] == 1
    assert report["new_meters"] == []


def test_full_meter_replaces_existing_file_only_variant(monkeypatch):
    # The 26.1 5ZoneAirCooled example requests these as MeterFileOnly.
    configured = [
        ("Output:Meter:MeterFileOnly", "Electricity:Facility", "monthly"),
        ("Output:Meter:MeterFileOnly", "NaturalGas:Facility", "monthly"),
    ]
    manager = _manager(monkeypatch, configured)
    idf = _FakeIDF(*configured)
    monkeypatch.setattr(output_meters, "IDF", lambda _path: idf)

    report = manager.check_duplicate_meters(
        "m.idf",
        [_spec("Electricity:Facility", "Monthly"), _spec("NaturalGas:Facility", "Monthly")],
    )
    result = manager.add_meters_to_idf("m.idf", report["new_meters"], "out.idf")

    assert report["duplicates_found"] == 0
    assert len(report["replaced_meters"]) == 2
    assert result["success"] is True
    assert idf.meters() == [
        ("Output:Meter", "Electricity:Facility", "Monthly"),
        ("Output:Meter", "NaturalGas:Facility", "Monthly"),
    ]


def test_cumulative_and_other_frequencies_are_not_duplicates(monkeypatch):
    manager = _manager(monkeypatch, [("Output:Meter", "Electricity:Facility", "Monthly")])

    report = manager.check_duplicate_meters(
        "m.idf",
        [
            _spec("Electricity:Facility", "Monthly", "Output:Meter:Cumulative"),
            _spec("Electricity:Facility", "Hourly"),
        ],
    )

    assert report["duplicates_found"] == 0
    assert report["replaced_meters"] == []
    assert len(report["new_meters"]) == 2


def test_repeated_request_in_one_call_is_added_once(monkeypatch):
    manager = _manager(monkeypatch, [("Output:Meter", "Gas:Facility", "Hourly")])

    report = manager.check_duplicate_meters(
        "m.idf",
        [_spec("Electricity:Facility", "Monthly"), _spec("electricity:facility", "monthly")],
    )

    assert len(report["new_meters"]) == 1
    assert report["duplicates_found"] == 1


def test_allow_duplicates_keeps_existing_objects(monkeypatch):
    manager = _manager(monkeypatch, [("Output:Meter:MeterFileOnly", "Electricity:Facility", "Monthly")])

    report = manager.check_duplicate_meters(
        "m.idf", [_spec("Electricity:Facility", "Monthly")], allow_duplicates=True
    )

    assert report["replaced_meters"] == []
    assert "replaces" not in report["new_meters"][0]


def _calibration_meters(*existing):
    idf = _FakeIDF(*existing)
    idf.idfobjects["Output:SQLite"] = [SimpleNamespace(key="Output:SQLite", Option_Type="SimpleAndTabular")]
    manager = EnergyPlusManager.__new__(EnergyPlusManager)
    manager._ensure_calibration_outputs(idf)
    return idf.meters()


def test_calibration_outputs_accept_existing_meters_in_any_case():
    assert _calibration_meters(
        ("Output:Meter", "ELECTRICITY:FACILITY", "monthly"),
        ("Output:Meter", "naturalgas:facility", "MONTHLY"),
    ) == [
        ("Output:Meter", "ELECTRICITY:FACILITY", "monthly"),
        ("Output:Meter", "naturalgas:facility", "MONTHLY"),
    ]


def test_calibration_outputs_replace_file_only_variants():
    assert _calibration_meters(
        ("Output:Meter:MeterFileOnly", "Electricity:Facility", "monthly"),
        ("Output:Meter:MeterFileOnly", "Electricity:Facility", "hourly"),
    ) == [
        ("Output:Meter", "Electricity:Facility", "Monthly"),
        ("Output:Meter", "NaturalGas:Facility", "Monthly"),
        ("Output:Meter:MeterFileOnly", "Electricity:Facility", "hourly"),
    ]
