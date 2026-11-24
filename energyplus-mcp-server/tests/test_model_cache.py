"""Read-only parsed models are shared within one capability call, and only there."""

import os
import threading
import time
from pathlib import Path

import pytest

from energyplus_mcp_server.utils import model_cache
from energyplus_mcp_server.utils.model_cache import read_only_idf, shared_models, with_shared_models

REAL_IDD = os.getenv("EPLUS_IDD_PATH", "/app/software/EnergyPlusV26-1-0/Energy+.idd")


class FakeIDF:
    def __init__(self, path):
        self.path = path
        self.text = Path(path).read_text()

    def idfstr(self):
        return self.text


class CountingLoader:
    def __init__(self):
        self.calls = 0

    def __call__(self, path):
        self.calls += 1
        return FakeIDF(path)


@pytest.fixture
def model(tmp_path):
    path = tmp_path / "model.idf"
    path.write_text("Version,26.1;\n")
    return path


def test_outside_a_scope_every_call_parses(model):
    loader = CountingLoader()

    first = read_only_idf(str(model), loader)
    second = read_only_idf(str(model), loader)

    assert loader.calls == 2 and first is not second


def test_inside_a_scope_one_parse_per_file(model, tmp_path):
    other = tmp_path / "other.idf"
    other.write_text("Version,26.1;\n")
    loader = CountingLoader()

    with shared_models():
        first = read_only_idf(str(model), loader)
        again = read_only_idf(str(model.resolve()), loader)
        with shared_models():  # nested scopes reuse the outer cache
            nested = read_only_idf(str(model), loader)
        different = read_only_idf(str(other), loader)

    assert first is again is nested
    assert different is not first
    assert loader.calls == 2


def test_cache_ends_with_the_outermost_scope(model):
    loader = CountingLoader()

    with shared_models():
        first = read_only_idf(str(model), loader)
    with shared_models():
        second = read_only_idf(str(model), loader)

    assert first is not second and loader.calls == 2


def test_a_changed_file_is_parsed_again(model):
    loader = CountingLoader()

    with shared_models():
        before = read_only_idf(str(model), loader)
        time.sleep(0.01)
        model.write_text("Version,26.1;\nZone,Z1;\n")
        after = read_only_idf(str(model), loader)

    assert before is not after
    assert after.text.endswith("Zone,Z1;\n")


def test_different_loaders_do_not_share(model):
    first_loader, second_loader = CountingLoader(), CountingLoader()

    with shared_models():
        first = read_only_idf(str(model), first_loader)
        second = read_only_idf(str(model), second_loader)

    assert first is not second


def test_threads_do_not_share_models(model):
    loader = CountingLoader()
    seen = {}

    def other_thread():
        seen["model"] = read_only_idf(str(model), loader)

    with shared_models():
        mine = read_only_idf(str(model), loader)
        thread = threading.Thread(target=other_thread)
        thread.start()
        thread.join()

    assert seen["model"] is not mine


def test_decorator_scopes_one_call(model):
    loader = CountingLoader()

    @with_shared_models
    def capability_check():
        return [read_only_idf(str(model), loader) for _ in range(5)]

    models = capability_check()
    capability_check()

    assert all(m is models[0] for m in models)
    assert loader.calls == 2


def test_tripwire_catches_a_modified_shared_model(model, monkeypatch):
    monkeypatch.setenv(model_cache.VERIFY_ENV, "1")
    loader = CountingLoader()

    with pytest.raises(AssertionError, match="modified in memory"):
        with shared_models():
            read_only_idf(str(model), loader).text += "Zone,Changed;\n"


def test_tripwire_passes_when_models_are_untouched(model, monkeypatch):
    monkeypatch.setenv(model_cache.VERIFY_ENV, "1")
    loader = CountingLoader()

    with shared_models():
        read_only_idf(str(model), loader)


@pytest.mark.skipif(not os.path.isfile(REAL_IDD), reason="EnergyPlus IDD not installed")
def test_aggregate_capabilities_parse_the_model_once(monkeypatch):
    from energyplus_mcp_server.domains import capabilities
    from energyplus_mcp_server.energyplus_tools import EnergyPlusManager

    sample = Path(__file__).resolve().parents[1] / "sample_files" / "basic" / "5ZoneAirCooled.idf"
    manager = EnergyPlusManager()
    # Earlier tests may leave the shared config in HTTP mode; this test only counts parses.
    manager._resolve_idf_path = lambda path: str(Path(path).resolve())
    manager._assert_simulation_version_matches = lambda path: {"runtime_version": "26.1.0", "model_version": "26.1"}
    manager._runtime_energyplus_version = lambda: "26.1.0"
    parses = []
    original = model_cache._default_loader

    def counting(path):
        parses.append(path)
        return original(path)

    monkeypatch.setattr(model_cache, "_default_loader", counting)
    monkeypatch.setenv(model_cache.VERIFY_ENV, "1")
    managers = [tool for _, tool, _ in capabilities.PARAMETER_DOMAINS]

    result = capabilities.combined_capabilities(manager, str(sample), managers, "summary")

    assert result["success"] is True, (result.get("error"), result.get("errors"))
    # One shared parse, plus one more by the tripwire's own re-parse.
    assert len(parses) == 2
