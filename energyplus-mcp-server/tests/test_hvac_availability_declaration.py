"""HVAC availability is declared unsupported: scaling an on/off schedule does not change operating hours."""

import asyncio
import json
import os
import shutil
from pathlib import Path

import pytest

from energyplus_mcp_server.domains import capabilities, schedules

REAL_IDD = os.getenv("EPLUS_IDD_PATH", "/app/software/EnergyPlusV26-1-0/Energy+.idd")
SAMPLE = Path(__file__).resolve().parents[1] / "sample_files" / "basic" / "5ZoneAirCooled.idf"


class FakeMCP:
    def tool(self, *args, **kwargs):
        def capture(fn):
            self.fn = fn
            return fn
        return capture


def _tool():
    mcp = FakeMCP()
    schedules.register(mcp, object(), config=None)
    return mcp.fn


def _check_unsupported(declaration):
    assert declaration["coverage"] == "none" and declaration["supported"] is False
    assert declaration["status"] == "not_implemented"
    assert declaration["action"] is None and declaration["operations"] == []
    assert "value_semantics" not in declaration
    assert "on/off" in declaration["limitations"][0]


def test_declaration_without_a_model_is_unsupported_and_meets_the_contract():
    result = schedules._parameter_capabilities(object(), None)

    _check_unsupported(result["parameters"]["hvac_availability_schedule"])
    assert capabilities.declaration_problems("schedule_manager", result["parameters"]) == []
    # Percentage scaling stays declared for the scopes where it means something.
    assert {name: d["action"] for name, d in result["parameters"].items() if d["action"]} == {
        "lighting_schedule": "adjust_percentage", "equipment_schedule": "adjust_percentage"}


def test_adjust_percentage_refuses_hvac_availability():
    reply = json.loads(asyncio.run(_tool()(
        action="adjust_percentage", idf_path="model.idf", scope="hvac_availability", percentage_change=-6)))

    assert reply["success"] is False and reply["supported"] is False
    assert "does not support hvac_availability" in reply["error"]


def test_capabilities_list_the_percentage_scopes():
    listing = json.loads(asyncio.run(_tool()(action="capabilities")))
    adjust = next(a for a in listing["actions"] if a["name"] == "adjust_percentage")

    assert adjust["scopes"] == ["electric_equipment", "lighting"]


@pytest.mark.skipif(not os.path.isfile(REAL_IDD), reason="EnergyPlus IDD not installed")
def test_declaration_on_a_model_counts_consumers_but_stays_unsupported(tmp_path):
    from eppy.modeleditor import IDF

    if IDF.getiddname() is None:
        IDF.setiddname(REAL_IDD)
    model = tmp_path / "model.idf"
    shutil.copyfile(SAMPLE, model)

    result = schedules._parameter_capabilities(object(), str(model))
    declaration = result["parameters"]["hvac_availability_schedule"]

    _check_unsupported(declaration)
    assert declaration["availability_consumer_count"] > 0
    assert declaration["input_sha256"]
    assert result["parameters"]["lighting_schedule"]["coverage"] == "complete"
    assert capabilities.declaration_problems("schedule_manager", result["parameters"]) == []
