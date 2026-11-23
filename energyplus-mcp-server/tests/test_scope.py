"""Per-token file-access isolation for the streamable-http transport."""
import json
import os
from pathlib import Path
import socket
import threading
import time

import pytest

from energyplus_mcp_server.auth import _token_label
from energyplus_mcp_server.scope import ScopeError

ALICE_TOKEN = "alice-token-32-chars-abcdefghijklmnop"
BOB_TOKEN = "bob-token-32-chars-abcdefghijklmnopqr"
ADMIN_TOKEN = "admin-token-32-chars-abcdefghijklmnop"


@pytest.fixture
def http_config(monkeypatch, tmp_path):
    """A streamable-http Config whose directories all live under tmp_path."""
    for var in ("MCP_HTTP_HOST", "MCP_HTTP_PORT", "MCP_HTTP_PATH", "PORT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("MCP_TOKENS", json.dumps([
        {"label": "alice", "token": ALICE_TOKEN},
        {"label": "bob", "token": BOB_TOKEN},
        {"label": "ops", "token": ADMIN_TOKEN},
    ]))
    monkeypatch.setenv("MCP_ADMIN_LABELS", "ops")
    users = tmp_path / "users"
    monkeypatch.setenv("MCP_USER_DATA_ROOT", str(users))

    from energyplus_mcp_server.config import Config
    cfg = Config()
    cfg.paths.workspace_root = str(tmp_path)
    cfg.paths.output_dir = str(tmp_path / "outputs")
    cfg.paths.sample_files_path = str(tmp_path / "sample_files")
    cfg.energyplus.example_files_path = str(tmp_path / "examples")
    cfg.energyplus.weather_data_path = str(tmp_path / "weather")
    for d in ("sample_files", "examples", "weather", "logs", "users/alice", "users/bob"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / "sample_files" / "shared.idf").write_text("! shared sample\n")
    (tmp_path / "users" / "alice" / "mine.idf").write_text("! alice\n")
    (tmp_path / "users" / "bob" / "secret.idf").write_text("! bob\n")
    (tmp_path / "server_secret.idf").write_text("! not for users\n")
    return cfg


@pytest.fixture
def as_alice():
    tok = _token_label.set("alice")
    yield
    _token_label.reset(tok)


def _real(p):
    return os.path.realpath(str(p))


# --- resolve_path: reads -------------------------------------------------------

def test_reads_own_file_and_shared_samples(http_config, as_alice, tmp_path):
    from energyplus_mcp_server.utils.path_utils import resolve_path
    assert resolve_path(http_config, "mine.idf", ['.idf']) == _real(tmp_path / "users/alice/mine.idf")
    assert resolve_path(http_config, "shared.idf", ['.idf']) == _real(tmp_path / "sample_files/shared.idf")


def test_cannot_read_other_users_file_by_absolute_path(http_config, as_alice, tmp_path):
    from energyplus_mcp_server.utils.path_utils import resolve_path
    with pytest.raises(ScopeError):
        resolve_path(http_config, str(tmp_path / "users/bob/secret.idf"), ['.idf'])


def test_cannot_read_server_files_by_absolute_path(http_config, as_alice, tmp_path):
    from energyplus_mcp_server.utils.path_utils import resolve_path
    with pytest.raises(ScopeError):
        resolve_path(http_config, str(tmp_path / "server_secret.idf"), ['.idf'])


@pytest.mark.parametrize("rel", ["../bob/secret.idf", "../../server_secret.idf"])
def test_cannot_traverse_out_with_relative_path(http_config, as_alice, rel):
    from energyplus_mcp_server.utils.path_utils import resolve_path
    with pytest.raises((ScopeError, FileNotFoundError)):
        resolve_path(http_config, rel, ['.idf'])


def test_symlink_out_of_workspace_is_not_readable(http_config, as_alice, tmp_path):
    from energyplus_mcp_server.utils.path_utils import resolve_path
    link = tmp_path / "users/alice/link.idf"
    link.symlink_to(tmp_path / "users/bob/secret.idf")
    with pytest.raises((ScopeError, FileNotFoundError)):
        resolve_path(http_config, "link.idf", ['.idf'])
    with pytest.raises(ScopeError):
        resolve_path(http_config, str(link), ['.idf'])


# --- resolve_path: writes ------------------------------------------------------

def test_relative_output_lands_in_own_workspace(http_config, as_alice, tmp_path):
    from energyplus_mcp_server.utils.path_utils import resolve_path
    out = resolve_path(http_config, "sub/out.idf", must_exist=False)
    assert out == _real(tmp_path / "users/alice/sub/out.idf")


@pytest.mark.parametrize("target", [
    "../bob/evil.idf",
    "/users/bob/evil.idf",          # made absolute below
    "/sample_files/overwrite.idf",  # shared dirs are read-only
])
def test_cannot_write_outside_own_workspace(http_config, as_alice, tmp_path, target):
    from energyplus_mcp_server.utils.path_utils import resolve_path
    if target.startswith("/"):
        target = str(tmp_path) + target
    with pytest.raises(ScopeError):
        resolve_path(http_config, target, must_exist=False)


# --- fail-closed and stdio behavior --------------------------------------------

def test_http_mode_without_identity_fails_closed(http_config):
    from energyplus_mcp_server.utils.path_utils import resolve_path
    with pytest.raises(ScopeError):
        resolve_path(http_config, "shared.idf", ['.idf'])


def test_stdio_mode_is_unscoped(http_config, tmp_path):
    from energyplus_mcp_server.utils.path_utils import resolve_path
    http_config.transport.transport = "stdio"
    secret = str(tmp_path / "server_secret.idf")
    assert resolve_path(http_config, secret, ['.idf']) == secret


# --- manager-level behavior ----------------------------------------------------

def test_default_output_for_shared_input_goes_to_own_workspace(http_config, as_alice, tmp_path):
    from energyplus_mcp_server.utils.path_utils import derived_model_path, report_path, resolve_output_location
    shared = str(tmp_path / "sample_files/shared.idf")
    # Same work/ layout as stdio, but inside the caller's workspace.
    assert derived_model_path(http_config, shared) == str(
        tmp_path / "users/alice/models/derived/shared_modified.idf")
    assert report_path(http_config, "plan.html") == str(tmp_path / "users/alice/reports/plan.html")
    with pytest.raises(ScopeError):
        resolve_output_location(http_config, str(tmp_path / "users/bob/x.idf"), "output_path")


def test_stdio_keeps_shared_work_folders(http_config, tmp_path, monkeypatch):
    from energyplus_mcp_server.utils.path_utils import derived_model_path, work_dir
    monkeypatch.setattr(http_config.transport, "transport", "stdio")
    monkeypatch.setattr(http_config.paths, "derived_models_dir", str(tmp_path / "work/models/derived"))
    shared = str(tmp_path / "sample_files/shared.idf")
    assert derived_model_path(http_config, shared) == str(
        os.path.join(http_config.paths.derived_models_dir, "shared_modified.idf"))
    assert work_dir(http_config, "runs") == http_config.paths.output_dir


def test_simulation_and_plot_dirs_are_scoped(http_config, as_alice, tmp_path):
    from energyplus_mcp_server.utils.path_utils import resolve_output_location, work_dir
    assert work_dir(http_config, "runs") == str(tmp_path / "users/alice/runs")
    assert resolve_output_location(http_config, "run1", "output_directory") == _real(
        tmp_path / "users/alice/run1")
    for target in (str(tmp_path / "users/bob/run1"), "../bob/run1", str(tmp_path / "outputs")):
        with pytest.raises(ScopeError):
            resolve_output_location(http_config, target, "output_directory")


def test_edited_outputs_can_be_found_again_by_name(http_config, as_alice, tmp_path):
    from energyplus_mcp_server.utils.path_utils import derived_model_path, resolve_path
    saved = derived_model_path(http_config, str(tmp_path / "sample_files/shared.idf"))
    Path(saved).write_text("! edited\n")
    assert resolve_path(http_config, "shared_modified.idf", file_types=[".idf"]) == _real(saved)


def test_bare_sample_name_finds_category_folder(http_config, as_alice, tmp_path):
    from energyplus_mcp_server.utils.path_utils import resolve_path
    nested = tmp_path / "sample_files/basic/Nested.idf"
    nested.parent.mkdir(parents=True, exist_ok=True)
    nested.write_text("! nested sample\n")
    assert resolve_path(http_config, "Nested.idf", file_types=[".idf"]) == _real(nested)


def test_tool_guard_confines_output_arguments(http_config, as_alice, tmp_path):
    from energyplus_mcp_server.utils.output_guard import guard_tool

    def tool(idf_path, output_path=None, output_directory=None):
        return output_path, output_directory

    guarded = guard_tool(tool, http_config)
    # Relative outputs are rewritten into the caller's workspace before the tool runs.
    assert guarded("m.idf", "edited.idf", output_directory="runs/a") == (
        _real(tmp_path / "users/alice/edited.idf"), _real(tmp_path / "users/alice/runs/a"))
    for bad in (str(tmp_path / "users/bob/x.idf"), "../bob/x.idf", str(tmp_path / "server_secret.idf")):
        with pytest.raises(ScopeError):
            guarded("m.idf", output_path=bad)


def test_copy_file_cannot_exfiltrate_other_users_file(http_config, as_alice, tmp_path):
    from energyplus_mcp_server.energyplus_tools import EnergyPlusManager
    mgr = EnergyPlusManager.__new__(EnergyPlusManager)
    mgr.config = http_config
    result = mgr.copy_file(str(tmp_path / "users/bob/secret.idf"), "stolen.idf")
    assert '"success": true' not in result.lower()
    assert not (tmp_path / "users/alice/stolen.idf").exists()


def test_similar_path_suggestions_stay_in_scope(http_config, as_alice):
    from energyplus_mcp_server.utils.path_utils import PathResolver
    suggestions = PathResolver(http_config).suggest_similar_paths("secret.idf", ['.idf'])
    assert not any("bob" in s or "server_secret" in s for s in suggestions)


@pytest.mark.parametrize("bad_name", [
    "../bob/run1/secret",
    "../../bob/run1/secret",
    "sub/secret",
    "sub\\secret",
    "/tmp/secret",
    "..",
    ".",
])
def test_create_interactive_plot_rejects_traversal_in_idf_name(http_config, as_alice, tmp_path, bad_name):
    from energyplus_mcp_server.energyplus_tools import EnergyPlusManager
    bob_run = tmp_path / "users/bob/run1"
    bob_run.mkdir(parents=True, exist_ok=True)
    (bob_run / "secret.csv").write_text("Date/Time,Zone Mean Air Temperature [C](Hourly)\n01/01  01:00:00,21.0\n")
    alice_run = tmp_path / "users/alice/run1"
    alice_run.mkdir(parents=True, exist_ok=True)

    mgr = EnergyPlusManager.__new__(EnergyPlusManager)
    mgr.config = http_config
    with pytest.raises(RuntimeError, match="Invalid idf_name"):
        mgr.create_interactive_plot(str(alice_run), idf_name=bad_name)
    assert not list(bob_run.glob("*.html"))


def test_create_interactive_plot_blocks_symlink_csv_escape(http_config, as_alice, tmp_path):
    from energyplus_mcp_server.energyplus_tools import EnergyPlusManager
    bob_run = tmp_path / "users/bob/run1"
    bob_run.mkdir(parents=True, exist_ok=True)
    bob_csv = bob_run / "secret.csv"
    bob_csv.write_text("Date/Time,Zone Mean Air Temperature [C](Hourly)\n01/01  01:00:00,21.0\n")

    alice_run = tmp_path / "users/alice/run1"
    alice_run.mkdir(parents=True, exist_ok=True)
    (alice_run / "linked.csv").symlink_to(bob_csv)

    mgr = EnergyPlusManager.__new__(EnergyPlusManager)
    mgr.config = http_config
    with pytest.raises(RuntimeError, match="outside the directories"):
        mgr.create_interactive_plot(str(alice_run), idf_name="linked")
    assert not list(alice_run.glob("*.html"))
    assert not list(bob_run.glob("*.html"))


def test_create_interactive_plot_works_inside_own_workspace(http_config, as_alice, tmp_path):
    from energyplus_mcp_server.energyplus_tools import EnergyPlusManager
    alice_run = tmp_path / "users/alice/run1"
    alice_run.mkdir(parents=True, exist_ok=True)
    (alice_run / "model.csv").write_text(
        "Date/Time,Zone Mean Air Temperature [C](Hourly)\n01/01  01:00:00,21.0\n01/01  02:00:00,21.5\n"
    )

    mgr = EnergyPlusManager.__new__(EnergyPlusManager)
    mgr.config = http_config
    result = json.loads(mgr.create_interactive_plot(str(alice_run), idf_name="model"))
    assert result["success"] is True
    assert result["output_file"] == _real(alice_run / "model_variable_plot.html")
    assert (alice_run / "model_variable_plot.html").exists()


# --- admin gating --------------------------------------------------------------

def test_admin_tools_require_admin_label(http_config):
    from energyplus_mcp_server.scope import require_admin
    tok = _token_label.set("alice")
    try:
        with pytest.raises(ScopeError):
            require_admin(http_config, "clear_logs")
    finally:
        _token_label.reset(tok)
    tok = _token_label.set("ops")
    try:
        require_admin(http_config, "clear_logs")
    finally:
        _token_label.reset(tok)


def test_admin_labels_must_be_known(monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("MCP_TOKENS", json.dumps([{"label": "alice", "token": ALICE_TOKEN}]))
    monkeypatch.setenv("MCP_ADMIN_LABELS", "root")
    from energyplus_mcp_server.config import Config
    with pytest.raises(ValueError, match="MCP_ADMIN_LABELS"):
        Config()


# --- end to end: the label must reach tool code over real streamable-http ------

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_token_label_reaches_tool_handler_over_http(http_config):
    """Regression: a ContextVar set in middleware does NOT reach tool handlers,
    because they run in the MCP session's task. The label must come through the
    MCP request context instead — verified here against a real server."""
    import uvicorn
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings
    from energyplus_mcp_server.http_app import build_app
    from energyplus_mcp_server.scope import current_label

    fastmcp = FastMCP(
        "scope-test",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @fastmcp.tool()
    async def whoami() -> str:
        return str(current_label())

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(build_app(fastmcp, http_config),
                                           host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started

    async def call_as(token):
        async with streamablehttp_client(
            f"http://127.0.0.1:{port}/mcp",
            headers={"Authorization": f"Bearer {token}"},
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                first = await session.call_tool("whoami", {})
                second = await session.call_tool("whoami", {})
                return first.content[0].text, second.content[0].text

    try:
        assert await call_as(ALICE_TOKEN) == ("alice", "alice")
        assert await call_as(BOB_TOKEN) == ("bob", "bob")
    finally:
        server.should_exit = True
        thread.join(timeout=10)


async def test_session_cannot_be_reused_by_another_token(http_config):
    """A token must not be able to drive an MCP session opened by another token."""
    import httpx
    import uvicorn
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings
    from energyplus_mcp_server.http_app import build_app

    fastmcp = FastMCP(
        "session-test",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(build_app(fastmcp, http_config),
                                           host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)

    url = f"http://127.0.0.1:{port}/mcp"
    base = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "t", "version": "0"}}}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(url, json=init, headers={**base, "Authorization": f"Bearer {ALICE_TOKEN}"})
            assert r.status_code == 200
            sid = r.headers["mcp-session-id"]
            ping = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
            r = await c.post(url, json=ping, headers={
                **base, "Authorization": f"Bearer {BOB_TOKEN}", "mcp-session-id": sid})
            assert r.status_code == 403
            r = await c.post(url, json=ping, headers={
                **base, "Authorization": f"Bearer {ALICE_TOKEN}", "mcp-session-id": sid})
            assert r.status_code != 403
    finally:
        server.should_exit = True
        thread.join(timeout=10)
