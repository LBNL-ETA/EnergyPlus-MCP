"""Admin gating for server_manager actions over the streamable-http transport."""
import json
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace

import pytest

from energyplus_mcp_server.auth import _token_label
from energyplus_mcp_server.tools import server as server_tools

ALICE_TOKEN = "alice-token-32-chars-abcdefghijklmnop"
ADMIN_TOKEN = "admin-token-32-chars-abcdefghijklmnop"


class FakeMCP:
    def __init__(self):
        self._tool_manager = SimpleNamespace(_tools={})

    def tool(self, *args, **kwargs):
        def decorate(fn):
            self._tool_manager._tools[kwargs.get("name") or fn.__name__] = fn
            return fn

        return decorate


class FakeManager:
    def get_configuration_info(self):
        return json.dumps({"paths": {"workspace_root": "/secret"}})


def _make_config(monkeypatch, tmp_path, transport):
    for var in ("MCP_HTTP_HOST", "MCP_HTTP_PORT", "MCP_HTTP_PATH", "PORT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MCP_TRANSPORT", transport)
    if transport == "streamable-http":
        monkeypatch.setenv("MCP_TOKENS", json.dumps([
            {"label": "alice", "token": ALICE_TOKEN},
            {"label": "ops", "token": ADMIN_TOKEN},
        ]))
        monkeypatch.setenv("MCP_ADMIN_LABELS", "ops")
    else:
        monkeypatch.delenv("MCP_TOKENS", raising=False)
        monkeypatch.delenv("MCP_ADMIN_LABELS", raising=False)
    monkeypatch.setenv("MCP_USER_DATA_ROOT", str(tmp_path / "users"))

    from energyplus_mcp_server.config import Config
    cfg = Config()
    cfg.paths.workspace_root = str(tmp_path)
    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)
    (logs / "energyplus_mcp_server.log").write_text("2026-11-23 10:00:00 - INFO - bob opened /users/bob/x.idf\n")
    (logs / "energyplus_mcp_errors.log").write_text("2026-11-23 10:00:01 - ERROR - boom\n")
    return cfg


@pytest.fixture
def server_manager(monkeypatch):
    monkeypatch.setattr(server_tools, "STARTUP_TIME", datetime.utcnow(), raising=False)

    def build(cfg):
        mcp = FakeMCP()
        server_tools.register(mcp, FakeManager(), cfg)
        return mcp._tool_manager._tools["server_manager"]

    return build


@contextmanager
def as_label(label):
    # Set and reset inside the test body: async tests run in a different
    # context from fixture teardown, so a fixture cannot reset the ContextVar.
    tok = _token_label.set(label)
    try:
        yield
    finally:
        _token_label.reset(tok)


def _denied(result: str) -> bool:
    try:
        payload = json.loads(result)
    except json.JSONDecodeError:
        return False
    return "requires an admin token" in payload.get("error", "")


ADMIN_ONLY_CALLS = [
    {"action": "logs"},
    {"action": "logs", "type": "both", "format": "raw"},
    {"action": "clear_logs"},
    {"action": "clear_logs", "mode": "apply"},
    {"action": "status", "include_config": True, "detail": "detailed"},
]


@pytest.mark.parametrize("kwargs", ADMIN_ONLY_CALLS)
async def test_non_admin_token_is_denied(monkeypatch, tmp_path, server_manager, kwargs):
    tool = server_manager(_make_config(monkeypatch, tmp_path, "streamable-http"))
    with as_label("alice"):
        result = await tool(**kwargs)

    assert _denied(result)
    assert "bob" not in result and "/secret" not in result
    # A denied clear_logs must not rotate anything.
    assert (tmp_path / "logs" / "energyplus_mcp_server.log").exists()


@pytest.mark.parametrize("kwargs", ADMIN_ONLY_CALLS)
async def test_http_call_without_identity_is_denied(monkeypatch, tmp_path, server_manager, kwargs):
    tool = server_manager(_make_config(monkeypatch, tmp_path, "streamable-http"))

    assert _denied(await tool(**kwargs))


@pytest.mark.parametrize("kwargs", [
    {"action": "status"},
    {"action": "status", "include_config": True},  # summary detail adds no config
])
async def test_plain_status_is_open_to_every_token(monkeypatch, tmp_path, server_manager, kwargs):
    tool = server_manager(_make_config(monkeypatch, tmp_path, "streamable-http"))
    with as_label("alice"):
        payload = json.loads(await tool(**kwargs))

    assert "error" not in payload
    assert "config" not in payload["data"]


async def test_admin_token_can_read_logs_and_config(monkeypatch, tmp_path, server_manager):
    tool = server_manager(_make_config(monkeypatch, tmp_path, "streamable-http"))
    with as_label("ops"):
        logs = json.loads(await tool(action="logs", type="both"))
        status = json.loads(await tool(action="status", include_config=True, detail="detailed"))
        plan = json.loads(await tool(action="clear_logs"))

    assert "bob opened" in logs["data"]["content"]
    assert status["data"]["config"]["paths"]["workspace_root"] == "/secret"
    assert len(plan["data"]["will_rotate"]) == 2


async def test_stdio_caller_is_unrestricted(monkeypatch, tmp_path, server_manager):
    tool = server_manager(_make_config(monkeypatch, tmp_path, "stdio"))

    logs = json.loads(await tool(action="logs"))

    assert "bob opened" in logs["data"]["content"]
