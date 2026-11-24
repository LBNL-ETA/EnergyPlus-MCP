"""Summaries of large inspection replies keep problems and never truncate a list."""

import copy
import json

from energyplus_mcp_server.utils import reply_summary
from energyplus_mcp_server.utils.reply_summary import KEEP_LIMIT


def _schedule_result(consumers):
    return {
        "success": True,
        "scope": "all",
        "schedules": [
            {"schedule_id": f"s{i}", "schedule_name": f"Sched {i}", "object_type": "Schedule:Compact",
             "kind": "compact", "segments": [[0, 24, 1.0]] * 10, "valid": i != 3}
            for i in range(30)
        ],
        "consumers": [
            {"consumer_id": f"c{i}", "object_type": "Lights" if i % 2 else "People", "role": "lighting" if i % 2 else "occupancy"}
            for i in range(consumers)
        ],
        "skipped": [{"reason": "Schedule:File is not edited"}],
        "ambiguous": [],
    }


def test_schedule_summary_drops_entries_but_keeps_problems_and_consumers():
    result = reply_summary.schedule_inspection(_schedule_result(consumers=20))

    assert "schedules" not in result and result["schedules_count"] == 30
    assert result["schedules_by_object_type"] == {"Schedule:Compact": 30}
    assert result["invalid_schedules"] == [{"schedule_id": "s3", "schedule_name": "Sched 3", "object_type": "Schedule:Compact"}]
    # Consumers are what schedule edits refer to; a short list is kept whole.
    assert len(result["consumers"]) == 20
    assert result["skipped"] == [{"reason": "Schedule:File is not edited"}]
    assert result["detail"] == "summary" and result["omitted"] == {"schedules": 30}
    assert "detail='full'" in result["full_detail"] and "scope=" in result["full_detail"]


def test_a_long_list_becomes_counts_and_is_never_truncated():
    result = reply_summary.schedule_inspection(_schedule_result(consumers=KEEP_LIMIT + 1))

    assert "consumers" not in result
    assert result["consumers_count"] == KEEP_LIMIT + 1
    assert result["consumers_by_role"] == {"lighting": 50, "occupancy": 51}
    assert result["omitted"]["consumers"] == KEEP_LIMIT + 1


def test_a_list_at_the_limit_is_kept_whole():
    result = reply_summary.schedule_inspection(_schedule_result(consumers=KEEP_LIMIT))

    assert len(result["consumers"]) == KEEP_LIMIT and "consumers" not in result.get("omitted", {})


def test_geometry_summary_keeps_the_summary_and_zones():
    full = {
        "summary": {"counts": {"zones": 2, "surfaces": 3}},
        "geometry": {
            "building": {"name": "B"},
            "zones": [{"name": "Z1", "volume": 10.0}, {"name": "Z2", "volume": 20.0}],
            "surfaces": [{"name": f"S{i}", "vertices": [[0, 0, 0]] * 4} for i in range(3)],
            "subsurfaces": [{"name": "W1", "vertices": [[0, 0, 0]] * 4}],
            "shading_surfaces": [],
        },
    }

    result = reply_summary.geometry_summary(copy.deepcopy(full))

    assert result["summary"] == full["summary"]
    assert result["geometry"]["zones"] == full["geometry"]["zones"]
    assert "surfaces" not in result["geometry"]
    assert result["omitted"] == {"geometry.surfaces": 3, "geometry.subsurfaces": 1}


def test_envelope_summary_counts_surfaces_and_keeps_relationships():
    full = {
        "summary": {"total_surfaces": 3},
        "constructions": [{"name": "Wall"}],
        "materials": [{"name": "Brick"}],
        "surfaces": [
            {"name": "S1", "surface_type": "Wall", "outside_boundary_condition": "Outdoors", "construction_name": "Wall", "zone_name": "Z1"},
            {"name": "S2", "surface_type": "Wall", "outside_boundary_condition": "Surface", "construction_name": "Wall", "zone_name": "Z1"},
            {"name": "S3", "surface_type": "Floor", "outside_boundary_condition": "Ground", "construction_name": "Slab", "zone_name": "Z2"},
        ],
        "relationships": {"orphaned_constructions": ["Old"], "missing_references": []},
    }

    result = reply_summary.envelope_inspection(copy.deepcopy(full))

    assert "surfaces" not in result and result["surfaces_count"] == 3
    assert result["surfaces_by_surface_type"] == {"Wall": 2, "Floor": 1}
    assert result["surfaces_by_zone_name"] == {"Z1": 2, "Z2": 1}
    for key in ("summary", "constructions", "materials", "relationships"):
        assert result[key] == full[key]


def test_hvac_summary_counts_targets_and_keeps_coverage_problems():
    full = {
        "success": True,
        "thermostats": {
            "targets": [{"target_id": f"t{i}", "object_type": "ZoneControl:Thermostat"} for i in range(5)],
            "skipped": [],
            "ambiguous": [{"target_id": "t9", "reason": "multi-control"}],
            "shared_object_relationships": [{"schedule_name": "Htg"}],
        },
        "schedule_profiles": {"Htg": {"min": 15.0, "max": 21.0}},
        "declared_deadband_c": 1.0,
    }

    result = reply_summary.hvac_controls(copy.deepcopy(full))

    section = result["thermostats"]
    assert "targets" not in section and section["targets_count"] == 5
    assert section["targets_by_object_type"] == {"ZoneControl:Thermostat": 5}
    assert section["ambiguous"] == full["thermostats"]["ambiguous"]
    assert section["shared_object_relationships_count"] == 1
    assert result["schedule_profiles"] == full["schedule_profiles"]
    assert result["omitted"] == {"thermostats.targets": 5, "thermostats.shared_object_relationships": 1}


def test_nothing_omitted_means_no_hint():
    result = reply_summary.hvac_controls({"success": True, "thermostats": {"targets": [], "skipped": [], "ambiguous": []}})

    assert result["detail"] == "summary" and "omitted" not in result and "full_detail" not in result


def test_error_and_non_json_replies_pass_through_unchanged():
    error = json.dumps({"error": "File not found: x.idf"})

    assert reply_summary.summarize_text(error, reply_summary.envelope_inspection) == error
    assert reply_summary.summarize_text("Missing required parameter", reply_summary.envelope_inspection) == "Missing required parameter"
