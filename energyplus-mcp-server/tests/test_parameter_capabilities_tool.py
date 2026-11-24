"""The aggregate parameter_capabilities tool (domains/capabilities.py)."""

import asyncio
import json

import pytest

from energyplus_mcp_server.domains import capabilities
from energyplus_mcp_server.energyplus_tools import simulation_evidence_contract

ALL_MANAGERS = [manager for _, manager, _ in capabilities.PARAMETER_DOMAINS]
EVIDENCE = {
    "tool": "simulation_manager", "action": "run",
    "required_args": ["idf_path", "runs_dir"],
    "paths": "<runs_dir>/<run_id>/run/eplusout.sql and <runs_dir>/<run_id>/run_record.json",
}


class Manager:
    def __init__(self, model_version="26.1", missing=False):
        self.model_version, self.missing = model_version, missing

    def _resolve_idf_path(self, idf_path):
        if self.missing:
            raise FileNotFoundError(f"IDF file not found: {idf_path}")
        return "/m/seed.idf"

    def _assert_simulation_version_matches(self, idf_path):
        if self.model_version != "26.1":
            raise ValueError("EnergyPlus runtime version does not match model Version object: "
                             f"model {self.model_version}, runtime 26.1.0.")
        return {"model_version": "26.1", "runtime_version": "26.1.0"}


def _declaration(coverage="complete", targets=3):
    return {
        "coverage": coverage,
        "supported": coverage == "complete",
        "applicable_field_count": targets,
        "applicable_targets": [{"target_id": f"t{i}"} for i in range(targets)],
        "shared_object_relationships": [{"scope": "s"}] * 2,
        "skipped": [] if coverage == "complete" else [{"object": "x", "reason": "r"}],
        "ambiguous": [],
        "minimum_value": -100.0,
    }


def _responses(failing=()):
    """Fake domain responses shaped like the real managers' output."""
    common = {
        "success": True, "ready": True, "model_format": "idf",
        "idf_path": "/m/seed.idf", "energyplus_version": "26.1.0",
        "monthly_meters": ["Electricity:Facility", "NaturalGas:Facility"],
        "simulation_evidence": EVIDENCE,
        "applicability": {"lights_count": 1},
    }
    parameters = {
        "internal_load_manager": {"LPD": _declaration(), "coupled_occupancy": _declaration(targets=1)},
        "envelope_manager": {"INF": _declaration()},
        "schedule_manager": {"lighting_schedule": _declaration(),
                             "hvac_availability_schedule": _declaration("none", targets=400)},
        "hvac_manager": {"heating_setpoint": _declaration(), "economizer_control": _declaration()},
        "service_water_manager": {"service_water_efficiency": {
            **_declaration(), "all_service_water_targets": [{"id": 1}] * 4}},
    }
    funcs = {"calls": []}
    for _, manager, module in capabilities.PARAMETER_DOMAINS:
        def make(manager=manager):
            def call(ep_manager, idf_path):
                funcs["calls"].append((manager, idf_path))
                if manager in failing:
                    return {"success": False, "model_error": f"{manager} cannot read model"}
                # Schedules and service water do not repeat the shared fields.
                base = {} if manager in ("schedule_manager", "service_water_manager") else dict(common)
                return {**base, "tool": manager, "manager": manager,
                        "action": "parameter_capabilities",
                        "parameters": json.loads(json.dumps(parameters[manager]))}
            return call
        funcs[module] = make()
    return funcs


@pytest.fixture
def fake_domains(monkeypatch):
    def install(failing=()):
        funcs = _responses(failing)
        monkeypatch.setattr(capabilities, "_domain_capability_function", lambda module: funcs[module])
        return funcs["calls"]
    return install


def test_aggregate_states_shared_fields_once_and_keeps_each_manager(fake_domains):
    fake_domains()
    result = capabilities.combined_capabilities(Manager(), "/m/seed.idf", ALL_MANAGERS)

    assert result["success"] is True and result["ready"] is True
    assert result["model_format"] == "idf"
    assert result["idf_path"] == "/m/seed.idf"
    assert result["monthly_meters"] == ["Electricity:Facility", "NaturalGas:Facility"]
    assert result["simulation_evidence"] == simulation_evidence_contract()
    assert result["managers"] == ALL_MANAGERS
    groups = result["domain_capabilities"]
    assert [g["tool"] for g in groups] == ALL_MANAGERS
    assert all(g["action"] == "parameter_capabilities" for g in groups)
    # Every provider key is reported, including the HVAC keys an agent once dropped.
    assert {"heating_setpoint", "economizer_control", "coupled_occupancy"} <= set(result["coverage"])
    assert result["coverage"]["hvac_availability_schedule"] == {
        "manager": "schedule_manager", "coverage": "none", "supported": False}
    # Shared fields are not repeated inside each group in summary mode.
    assert "monthly_meters" not in groups[0] and "applicability" not in groups[0]


def test_summary_drops_object_listings_but_keeps_the_capability_statement(fake_domains):
    fake_domains()
    summary = capabilities.combined_capabilities(Manager(), "/m/seed.idf", ALL_MANAGERS)
    full = capabilities.combined_capabilities(Manager(), "/m/seed.idf", ALL_MANAGERS, "full")

    lpd = summary["domain_capabilities"][0]["parameters"]["LPD"]
    assert "applicable_targets" not in lpd and "shared_object_relationships" not in lpd
    assert lpd["applicable_target_count"] == 3
    assert lpd["omitted_counts"] == {"applicable_targets": 3, "shared_object_relationships": 2}
    assert lpd["coverage"] == "complete" and lpd["applicable_field_count"] == 3
    hvac_sch = summary["domain_capabilities"][2]["parameters"]["hvac_availability_schedule"]
    assert hvac_sch["skipped"] == [{"object": "x", "reason": "r"}]
    shw = summary["domain_capabilities"][4]["parameters"]["service_water_efficiency"]
    assert "all_service_water_targets" not in shw
    assert summary["omitted_fields"] == list(capabilities.BULKY_FIELDS)

    full_lpd = full["domain_capabilities"][0]["parameters"]["LPD"]
    assert len(full_lpd["applicable_targets"]) == 3
    assert "omitted_fields" not in full
    assert len(json.dumps(summary)) < len(json.dumps(full)) / 2


def test_disabled_managers_are_not_reported(fake_domains):
    fake_domains()
    result = capabilities.combined_capabilities(
        Manager(), "/m/seed.idf", ["internal_load_manager", "hvac_manager"])
    assert result["managers"] == ["internal_load_manager", "hvac_manager"]
    assert "lighting_schedule" not in result["coverage"]


def test_a_failed_manager_fails_the_aggregate_without_hiding_others(fake_domains):
    fake_domains(failing=("hvac_manager",))
    result = capabilities.combined_capabilities(Manager(), "/m/seed.idf", ALL_MANAGERS)
    assert result["success"] is False and result["ready"] is False
    assert result["errors"] == [{"manager": "hvac_manager",
                                 "error": "hvac_manager cannot read model"}]
    assert "hvac_manager" not in result["managers"]
    assert "LPD" in result["coverage"]


def test_registered_tool_returns_json_and_rejects_unknown_detail(fake_domains):
    fake_domains()

    class Registry:
        def tool(self, name=None):
            def capture(function):
                self.name, self.call = name, function
                return function
            return capture

    registry = Registry()
    capabilities.register(registry, Manager(), None, ALL_MANAGERS)
    assert registry.name == "parameter_capabilities"
    payload = json.loads(asyncio.run(registry.call(idf_path="/m/seed.idf")))
    assert payload["success"] is True and payload["detail"] == "summary"
    error = json.loads(asyncio.run(registry.call(idf_path="/m/seed.idf", detail="verbose")))
    assert error["success"] is False and "detail" in error["error"]


def test_shared_fields_are_stated_even_without_the_managers_that_repeat_them(fake_domains):
    """Schedules and service water alone do not report meters or evidence."""
    fake_domains()
    result = capabilities.combined_capabilities(
        Manager(), "seed.idf", ["schedule_manager", "service_water_manager"])
    assert result["success"] is True
    assert result["idf_path"] == "/m/seed.idf"
    assert result["energyplus_version"] == "26.1.0" and result["model_version"] == "26.1"
    assert result["monthly_meters"] == ["Electricity:Facility", "NaturalGas:Facility"]
    assert result["simulation_evidence"]["tool"] == "simulation_manager"
    assert "runs_dir" in result["simulation_evidence"]["required_args"]


def test_domains_receive_the_resolved_path(fake_domains):
    calls = fake_domains()
    capabilities.combined_capabilities(Manager(), "relative/seed.idf", ALL_MANAGERS)
    assert {path for _, path in calls} == {"/m/seed.idf"}


@pytest.mark.parametrize(
    ("manager", "message"),
    [(Manager(model_version="9.2"), "does not match model Version"),
     (Manager(missing=True), "IDF file not found")],
)
def test_unreadable_or_wrong_version_model_is_one_error_before_any_manager(
        fake_domains, manager, message):
    calls = fake_domains()
    result = capabilities.combined_capabilities(manager, "seed.idf", ALL_MANAGERS)
    assert result["success"] is False and result["ready"] is False
    assert message in result["error"]
    assert ("model_upgrade" in result.get("next_action", "")) == (manager.model_version == "9.2")
    assert calls == []


def test_blank_path_is_rejected(fake_domains):
    fake_domains()
    with pytest.raises(ValueError, match="idf_path is required"):
        capabilities.combined_capabilities(Manager(), " ", ALL_MANAGERS)


# --- HTTP transport: the aggregate is confined like every domain manager --------

from tests.test_scope import as_alice, http_config  # noqa: E402,F401  (fixtures)


def _scoped_manager(config, monkeypatch):
    from energyplus_mcp_server.energyplus_tools import EnergyPlusManager

    manager = EnergyPlusManager.__new__(EnergyPlusManager)
    manager.config = config
    monkeypatch.setattr(manager, "_assert_simulation_version_matches",
                        lambda path: {"model_version": "26.1", "runtime_version": "26.1.0"})
    return manager


def test_http_caller_cannot_inspect_another_users_model(
        http_config, as_alice, tmp_path, fake_domains, monkeypatch):
    calls = fake_domains()
    manager = _scoped_manager(http_config, monkeypatch)
    result = capabilities.combined_capabilities(
        manager, str(tmp_path / "users/bob/secret.idf"), ALL_MANAGERS)
    assert result["success"] is False
    assert calls == []


def test_http_caller_inspects_own_model_by_name(
        http_config, as_alice, tmp_path, fake_domains, monkeypatch):
    calls = fake_domains()
    manager = _scoped_manager(http_config, monkeypatch)
    result = capabilities.combined_capabilities(manager, "mine.idf", ALL_MANAGERS)
    own = str((tmp_path / "users/alice/mine.idf").resolve())
    assert result["success"] is True and result["idf_path"] == own
    assert {path for _, path in calls} == {own}
