"""Remote callers may not run models that execute external code or read outside files."""
import json

import pytest

from energyplus_mcp_server.auth import _token_label
from energyplus_mcp_server.utils.model_guard import (
    UnsafeModelError,
    check_model_for_caller,
    find_problems,
    iter_objects,
)

BASE = "Version,26.1;\nBuilding, Office, 0, City, 0.04, 0.4, FullExterior, 25, 6;\n"


def test_iter_objects_ignores_comments_and_case():
    text = "! PythonPlugin:Instance, commented out;\nSchedule:File, S, Any, data.csv, 1; ! trailing"
    assert list(iter_objects(text)) == [("Schedule:File", ["S", "Any", "data.csv", "1"])]


@pytest.mark.parametrize("snippet", [
    "PythonPlugin:Instance, Evil, No, evil, Evil;",
    "pythonplugin:searchpaths, Paths, Yes, Yes, Yes, /data/users/me/models/uploads/evil.zip;",
    "PythonPlugin:Variables, Vars, x;",
    "ExternalInterface, PtolemyServer;",
    "ExternalInterface:FunctionalMockupUnitImport, /tmp/x.fmu, 15, 0;",
])
def test_code_running_objects_are_rejected(snippet):
    problems = find_problems(BASE + snippet)
    assert len(problems) == 1 and "runs external code" in problems[0]


@pytest.mark.parametrize("snippet, allowed", [
    ("Schedule:File, S, Any, occupancy.csv, 1, 0;", True),                    # relative, no ..
    ("Schedule:File, S, Any, ../bob/secret.csv, 1, 0;", False),
    ("Schedule:File, S, Any, sub\\..\\..\\bob.csv, 1, 0;", False),
    ("Schedule:File, S, Any, /etc/passwd, 1, 0;", False),
    ("Schedule:File, S, Any, C:\\data\\x.csv, 1, 0;", False),
    ("Schedule:File:Shading, /data/users/bob/shade.csv;", False),
    ("Construction:WindowDataFile, W, /data/users/bob/window.dat;", False),
    ("Table:Lookup, T, , , , , , , /proc/self/environ, 1, 1;", False),
    ("Table:IndependentVariable, V, Linear, Constant, , , , , ../../x.csv, 1, 1;", False),
    ("Chiller:Electric:ASHRAE205, C, /data/users/bob/chiller.cbor;", False),
    ("Schedule:File, S, Any, , 1, 0;", True),                                  # empty field
])
def test_file_references_must_stay_inside_the_callers_folders(snippet, allowed):
    assert (find_problems(BASE + snippet) == []) is allowed


def test_absolute_paths_the_caller_may_read_are_allowed():
    text = BASE + "Schedule:File, S, Any, /data/users/me/occ.csv, 1, 0;"
    assert find_problems(text, can_read=lambda p: p.startswith("/data/users/me/")) == []
    assert find_problems(text, can_read=lambda p: False) != []


def _http_config(monkeypatch, tmp_path, transport="streamable-http"):
    for var in ("MCP_HTTP_HOST", "MCP_HTTP_PORT", "MCP_HTTP_PATH", "PORT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MCP_TRANSPORT", transport)
    monkeypatch.setenv("MCP_TOKENS", json.dumps([{"label": "alice", "token": "a" * 40}]))
    monkeypatch.setenv("MCP_USER_DATA_ROOT", str(tmp_path / "users"))
    from energyplus_mcp_server.config import Config
    cfg = Config()
    cfg.paths.sample_files_path = str(tmp_path / "samples")
    return cfg


def test_check_applies_only_to_http_callers(monkeypatch, tmp_path):
    model = tmp_path / "evil.idf"
    model.write_text(BASE + "PythonPlugin:Instance, Evil, No, evil, Evil;")

    http = _http_config(monkeypatch, tmp_path)
    tok = _token_label.set("alice")
    try:
        with pytest.raises(UnsafeModelError, match="PythonPlugin:Instance"):
            check_model_for_caller(http, str(model))
    finally:
        _token_label.reset(tok)

    stdio = _http_config(monkeypatch, tmp_path, transport="stdio")
    check_model_for_caller(stdio, str(model))  # local users run their own models


def test_own_absolute_file_reference_is_allowed_over_http(monkeypatch, tmp_path):
    cfg = _http_config(monkeypatch, tmp_path)
    own = tmp_path / "users" / "alice" / "models" / "uploads" / "occ.csv"
    own.parent.mkdir(parents=True)
    own.write_text("1\n")
    model = tmp_path / "users" / "alice" / "models" / "uploads" / "m.idf"
    model.write_text(BASE + f"Schedule:File, S, Any, {own}, 1, 0;")
    tok = _token_label.set("alice")
    try:
        check_model_for_caller(cfg, str(model))
    finally:
        _token_label.reset(tok)
