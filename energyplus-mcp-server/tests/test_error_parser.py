"""ErrorParser against real EnergyPlus 26.1 .err files.

The fixtures were produced by running EnergyPlus 26.1.0 on copies of
ExampleFiles/5ZoneAirCooled.idf with one known defect each (design-day runs),
plus three unmodified ExampleFiles run for a year with the Chicago TMY3
weather file to capture recurring-error summaries.
"""

from pathlib import Path

import pytest

from energyplus_mcp_server.utils.error_parser import ErrorParser

FIXTURES = Path(__file__).parent / "fixtures" / "eplusout_err"


def parse(name):
    parser = ErrorParser()
    parsed = parser.parse_error_file(str(FIXTURES / f"{name}.err"))
    return parsed, parser.analyze_root_cause(parsed)


@pytest.mark.parametrize(
    ("name", "status", "totals", "category", "obj"),
    [
        ("invalid_choice", "terminated", (0, 1), "input_schema", "Lights=SPACE1-1 Lights 1"),
        ("out_of_range", "terminated", (0, 1), "input_schema", "Material=WD10"),
        ("duplicate_name", "terminated", (0, 1), "duplicate_name", None),
        ("missing_layer", "terminated", (0, 1), "missing_reference", "Construction=NONEXISTENT MATERIAL"),
        ("node_typo", "terminated", (1, 1), "node_connection", "FAN:VARIABLEVOLUME=SUPPLY FAN 1"),
        ("no_setpoint_managers", "terminated", (6, 6), "setpoint", "Controller:WaterCoil=OA HC CONTROLLER 1"),
        ("no_design_days", "terminated", (1, 3), "sizing", None),
        ("annual_no_weather", "terminated", (1, 1), "weather", None),
    ],
)
def test_lead_error_is_first_severe_not_the_fatal(name, status, totals, category, obj):
    parsed, analysis = parse(name)
    summary = parsed["summary"]
    assert summary["status"] == status and summary["terminated"] is True
    assert (summary["totals"]["warnings"], summary["totals"]["severe"]) == totals
    assert analysis["primary_issue"] == parsed["severe_errors"][0]["message"]
    assert analysis["primary_category"] == category
    assert analysis["primary_object"] == obj
    assert parsed["fatal_errors"][0]["category"] == "termination"


def test_schema_error_reports_field():
    parsed, _ = parse("invalid_choice")
    severe = parsed["severe_errors"][0]
    assert severe["field"] == "design_level_calculation_method"
    assert parsed["summary"]["stopped_before_simulation"] is True


def test_phase_counts_are_not_added_to_totals():
    # The one Severe is counted both "During Sizing" and in the final total.
    parsed, _ = parse("missing_layer")
    assert parsed["summary"]["phases"]["sizing"] == {"warnings": 0, "severe": 1}
    assert parsed["summary"]["totals"] == {"warnings": 0, "severe": 1}
    assert "phase_counts" not in parsed["summary"]


def test_crashed_run_is_incomplete_and_keeps_context():
    # EnergyPlus 26.1 exits with a segmentation fault on this input; the file
    # stops after the Severe message with no Fatal line and no totals.
    parsed, analysis = parse("missing_schedule")
    assert parsed["summary"]["status"] == "incomplete" and "totals" not in parsed["summary"]
    assert analysis["incomplete_run"] is True
    assert analysis["primary_object"] == "Lights=SPACE1-1 LIGHTS 1"
    assert analysis["primary_category"] == "missing_reference"
    assert "item not found" in analysis["primary_context"][0]


def test_completed_runs_with_warnings_and_severe():
    parsed, analysis = parse("baseline")
    assert parsed["summary"]["status"] == "completed" and parsed["summary"]["totals"] == {"warnings": 0, "severe": 0}
    assert analysis["primary_issue"] is None

    parsed, _ = parse("version_mismatch")
    assert [w["category"] for w in parsed["warnings"]] == ["version", "version"]
    parsed, _ = parse("reversed_floor")
    assert parsed["warnings"][0]["category"] == "geometry"

    parsed, analysis = parse("completed_with_severe")
    assert parsed["summary"]["status"] == "completed"
    assert parsed["summary"]["totals"]["severe"] == 2
    assert analysis["completed_with_severe"] is True


def test_recurring_summary_carries_real_counts():
    parsed, analysis = parse("recurring_millions")
    assert parsed["summary"]["totals"]["warnings"] == 5059591
    assert parsed["counts"]["warnings"] == 8  # printed in full
    by_message = {r["message"][:20]: r for r in parsed["recurring"]}
    sinks = by_message['"SINKS" - Target wat']
    assert sinks["occurrences"] == 1147903 and sinks["during_warmup"] == 0
    assert sinks["range"] == "Max=19.508979  Min=0.000006"
    coil = next(w for w in parsed["warnings"] if w["message"].startswith("CalcDoe2DXCoil"))
    assert coil["occurrences"] == 3531704
    assert analysis["frequent_recurring"][0]["occurrences"] == 3531704
    # Recurring lines are not mistaken for new messages or summary text.
    assert parsed["counts"]["recurring"] == 5


def test_recurring_matches_reworded_messages():
    parsed, _ = parse("recurring_psychrometrics")
    occurrences = {w["message"][:25]: w.get("occurrences") for w in parsed["warnings"]}
    assert occurrences["Temperature out of range "] == 1
    assert occurrences["WetBulb not converged aft"] == 1  # "after 101" vs "after max"
    assert parsed["warnings"][-1]["category"] == "psychrometrics"
    assert parsed["recurring"][0]["range"].startswith("Max=-3353.49")


def test_missing_file():
    assert ErrorParser().parse_error_file(str(FIXTURES / "nope.err"))["exists"] is False
