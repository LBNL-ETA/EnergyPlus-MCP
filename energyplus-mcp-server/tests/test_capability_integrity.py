"""Capability reports state coverage for every parameter and carry a tamper-evident digest."""

import asyncio
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from energyplus_mcp_server.domains import capabilities
from energyplus_mcp_server.domains.capabilities import (
    COVERAGE_VALUES,
    declaration_problems,
    report_digest,
    verify_report_digest,
)
from energyplus_mcp_server.utils.output_guard import guard_tool
from tests.test_parameter_capabilities_tool import ALL_MANAGERS, Manager, _registered, fake_domains  # noqa: F401

REAL_IDD = os.getenv("EPLUS_IDD_PATH", "/app/software/EnergyPlusV26-1-0/Energy+.idd")
SAMPLES = Path(__file__).resolve().parents[1] / "sample_files"


# -- digest ------------------------------------------------------------------------------------


def test_report_carries_a_digest_that_verifies(fake_domains):  # noqa: F811
    fake_domains()

    report = capabilities.combined_capabilities(Manager(), "/m/seed.idf", ALL_MANAGERS, "summary")

    assert report["report_sha256"] == report_digest(report)
    assert verify_report_digest(report)
    assert "report_digest_method" in report


def test_any_edit_breaks_the_digest(fake_domains):  # noqa: F811
    fake_domains()
    report = capabilities.combined_capabilities(Manager(), "/m/seed.idf", ALL_MANAGERS, "full")

    dropped = copy.deepcopy(report)
    del dropped["domain_capabilities"][0]["parameters"]["LPD"]["coverage"]
    changed = copy.deepcopy(report)
    changed["coverage"]["LPD"]["coverage"] = "partial"
    moved = copy.deepcopy(report)
    declaration = moved["domain_capabilities"][0]["parameters"]
    declaration["skipped"] = declaration["LPD"].pop("skipped")
    missing = copy.deepcopy(report)
    del missing["report_sha256"]

    for edited in (dropped, changed, moved, missing):
        assert not verify_report_digest(edited)


def test_key_order_and_formatting_do_not_matter(fake_domains):  # noqa: F811
    fake_domains()
    report = capabilities.combined_capabilities(Manager(), "/m/seed.idf", ALL_MANAGERS, "full")

    reordered = json.loads(json.dumps(dict(reversed(list(report.items())))))
    pretty = json.loads(json.dumps(report, indent=4, ensure_ascii=True))

    assert verify_report_digest(reordered) and verify_report_digest(pretty)


def test_digest_survives_the_compact_wire_format_and_the_file(fake_domains, tmp_path):  # noqa: F811
    fake_domains()
    config = SimpleNamespace(transport=SimpleNamespace(transport="stdio"))
    # Inline through the tool wrapper, which sends compact JSON.
    inline = json.loads(asyncio.run(guard_tool(_registered(), config)(idf_path="/m/seed.idf")))
    reply = json.loads(asyncio.run(_registered()(idf_path="/m/seed.idf", runs_dir=str(tmp_path / "runs"))))
    written = json.loads(Path(reply["capabilities_path"]).read_text())

    assert verify_report_digest(inline)
    assert verify_report_digest(written)
    assert reply["report_sha256"] == written["report_sha256"]


def test_failures_are_sealed_too(fake_domains):  # noqa: F811
    fake_domains()

    report = capabilities.combined_capabilities(Manager(missing=True), "/m/missing.idf", ALL_MANAGERS)

    assert report["success"] is False and verify_report_digest(report)


# -- coverage contract -------------------------------------------------------------------------


@pytest.mark.parametrize("declaration, fragment", [
    ({"supported": True}, "coverage None"),
    ({"coverage": "mostly", "supported": False}, "coverage 'mostly'"),
    ({"coverage": "complete"}, "supported must be true or false"),
    ({"coverage": "complete", "supported": "yes"}, "supported must be true or false"),
    ({"coverage": "partial", "supported": True}, "supported is true but coverage is 'partial'"),
])
def test_declaration_problems_are_named(declaration, fragment):
    problems = declaration_problems("internal_load_manager", {"LPD": declaration})

    assert len(problems) == 1 and fragment in problems[0] and "internal_load_manager.LPD" in problems[0]


def test_valid_declarations_pass():
    parameters = {f"P{i}": {"coverage": value, "supported": value == "complete"} for i, value in enumerate(COVERAGE_VALUES)}

    assert declaration_problems("hvac_manager", parameters) == []


def test_a_manager_that_omits_coverage_fails_the_report(fake_domains, monkeypatch):  # noqa: F811
    fake_domains()
    original = capabilities._domain_capability_function

    def without_coverage(module):
        function = original(module)
        if module != "envelope":
            return function

        def call(ep_manager, idf_path):
            response = function(ep_manager, idf_path)
            del response["parameters"]["INF"]["coverage"]
            return response
        return call

    monkeypatch.setattr(capabilities, "_domain_capability_function", without_coverage)

    report = capabilities.combined_capabilities(Manager(), "/m/seed.idf", ALL_MANAGERS, "summary")

    assert report["success"] is False and report["ready"] is False
    assert any("envelope_manager.INF" in error["error"] and "contract" in error["error"] for error in report["errors"])
    assert verify_report_digest(report)


@pytest.mark.skipif(not os.path.isfile(REAL_IDD), reason="EnergyPlus IDD not installed")
@pytest.mark.parametrize("model", sorted(str(p.relative_to(SAMPLES)) for p in SAMPLES.glob("*/*.idf")))
def test_real_models_meet_the_contract(model):
    from energyplus_mcp_server.energyplus_tools import EnergyPlusManager

    manager = EnergyPlusManager()
    manager._resolve_idf_path = lambda path: str(Path(path).resolve())
    manager._assert_simulation_version_matches = lambda path: {"runtime_version": "26.1.0", "model_version": "26.1"}
    manager._runtime_energyplus_version = lambda: "26.1.0"

    report = capabilities.combined_capabilities(manager, str(SAMPLES / model), ALL_MANAGERS, "full")

    contract_errors = [e for e in report.get("errors", []) if "contract" in e["error"]]
    assert contract_errors == []
    declared = {name for group in report["domain_capabilities"] for name in group["parameters"]}
    assert set(report["coverage"]) == declared
    for group in report["domain_capabilities"]:
        assert declaration_problems(group["tool"], group["parameters"]) == []
    assert verify_report_digest(report)
