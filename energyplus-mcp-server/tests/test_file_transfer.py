"""One-time upload and download links for remote (streamable-HTTP) clients."""
import asyncio
import hashlib
import io
import json
import os
import time
import zipfile
from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from energyplus_mcp_server.auth import AuthMiddleware, _token_label
from energyplus_mcp_server.file_routes import file_routes
from energyplus_mcp_server.tools import file_transfer as file_transfer_tool
from energyplus_mcp_server.utils import file_transfer as transfer

ALICE_TOKEN = "alice-token-32-chars-abcdefghijklmnop"
BOB_TOKEN = "bob-token-32-chars-abcdefghijklmnopqr"
BASE = "http://testserver"


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self, *args, **kwargs):
        def decorate(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorate


@pytest.fixture
def server(monkeypatch, tmp_path):
    for var in ("MCP_HTTP_HOST", "MCP_HTTP_PORT", "MCP_HTTP_PATH", "PORT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("MCP_TOKENS", json.dumps([
        {"label": "alice", "token": ALICE_TOKEN},
        {"label": "bob", "token": BOB_TOKEN},
    ]))
    monkeypatch.setenv("MCP_USER_DATA_ROOT", str(tmp_path / "users"))

    from energyplus_mcp_server.config import Config
    cfg = Config()
    cfg.paths.workspace_root = str(tmp_path)
    cfg.paths.sample_files_path = str(tmp_path / "sample_files")
    cfg.energyplus.example_files_path = str(tmp_path / "examples")
    cfg.energyplus.weather_data_path = str(tmp_path / "weather")
    for d in ("sample_files", "examples", "weather", "users/alice", "users/bob"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    store = transfer.TransferStore(transfer.TransferSettings(
        max_upload_bytes=1000, user_quota_bytes=5000, max_download_bytes=10_000,
        public_base_url=BASE,
    ))
    transfer.reset_store(store)

    mcp = FakeMCP()
    file_transfer_tool.register(mcp, None, cfg)
    tool = mcp.tools["file_transfer"]

    def call(label, **kwargs):
        async def run():
            tok = _token_label.set(label)
            try:
                return json.loads(await tool(**kwargs))
            finally:
                _token_label.reset(tok)
        return asyncio.run(run())

    async def mcp_endpoint(_request):
        return JSONResponse({"ok": True})

    app = Starlette(routes=[*file_routes(), Route("/mcp", mcp_endpoint, methods=["POST"])])
    app.add_middleware(AuthMiddleware, tokens=cfg.auth.tokens)
    client = TestClient(app)
    yield SimpleNamespace(cfg=cfg, call=call, client=client, store=store, root=tmp_path)
    transfer.reset_store(None)


def _path(url):
    assert url.startswith(BASE)
    return url[len(BASE):]


def test_upload_round_trip_and_reuse_is_refused(server):
    data = b"Version,26.1;\n"
    link = server.call("alice", action="request_upload", filename="office.idf",
                       size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    # The upload route needs no bearer token: the code in the URL is the credential.
    response = server.client.put(_path(link["upload_url"]), content=data)
    assert response.status_code == 200, response.text

    status = server.call("alice", action="upload_status", file_id=link["file_id"])
    expected = server.root / "users/alice/models/uploads/office.idf"
    assert status["status"] == "ready" and status["server_path"] == str(expected)
    assert expected.read_bytes() == data
    assert server.client.put(_path(link["upload_url"]), content=data).status_code == 404

    # Other tools find the upload by its bare name.
    from energyplus_mcp_server.utils.path_utils import resolve_path
    tok = _token_label.set("alice")
    try:
        assert resolve_path(server.cfg, "office.idf", file_types=[".idf"]) == os.path.realpath(expected)
    finally:
        _token_label.reset(tok)

    listed = server.call("alice", action="list_uploads")
    assert [f["filename"] for f in listed["uploads"]] == ["office.idf"]
    assert server.call("bob", action="list_uploads")["uploads"] == []


def test_browser_upload_without_declared_size(server):
    link = server.call("alice", action="request_upload", filename="weather.epw")
    page = server.client.get(_path(link["upload_url"]))
    assert page.status_code == 200 and "weather.epw" in page.text
    assert server.client.post(_path(link["upload_url"]), content=b"LOCATION,x\n").status_code == 200
    assert server.client.get("/files/upload/not-a-real-code").status_code == 404


def test_bad_uploads_fail_and_can_retry(server):
    link = server.call("alice", action="request_upload", filename="a.idf", size_bytes=5)
    url = _path(link["upload_url"])
    assert server.client.put(url, content=b"123").status_code == 400  # wrong size
    assert server.call("alice", action="upload_status", file_id=link["file_id"])["status"] == "failed"
    assert server.client.put(url, content=b"12345").status_code == 200  # retry succeeds

    checked = server.call("alice", action="request_upload", filename="b.idf", size_bytes=3,
                          sha256="0" * 64)
    assert server.client.put(_path(checked["upload_url"]), content=b"abc").status_code == 400

    unsized = server.call("alice", action="request_upload", filename="big.idf")
    assert server.client.put(_path(unsized["upload_url"]), content=b"x" * 1001).status_code == 413
    uploads = server.root / "users/alice/models/uploads"
    assert sorted(p.name for p in uploads.iterdir()) == ["a.idf"]  # no partial files left


@pytest.mark.parametrize("kwargs, message", [
    ({"filename": "run.sh"}, "Unsupported file type"),
    ({"filename": "x.idf", "size_bytes": 1001}, "upload limit"),
    ({"filename": "x.idf", "sha256": "nothex"}, "sha256"),
    ({"filename": "x.idf", "size_bytes": 900}, None),
])
def test_upload_requests_are_validated(server, kwargs, message):
    result = server.call("alice", action="request_upload", **kwargs)
    if message:
        assert message in result["error"]
    else:
        assert "upload_url" in result


def test_quota_counts_the_users_folder(server):
    (server.root / "users/alice/runs").mkdir(parents=True)
    (server.root / "users/alice/runs/out.sql").write_bytes(b"x" * 4500)
    result = server.call("alice", action="request_upload", filename="x.idf", size_bytes=600)
    assert "quota" in result["error"]


def test_upload_names_stay_inside_the_users_uploads_folder(server):
    first = server.call("alice", action="request_upload", filename="../../bob/evil.idf")
    second = server.call("alice", action="request_upload", filename="evil.idf")
    assert first["stored_as"] == "evil.idf" and second["stored_as"] == "evil_2.idf"
    server.client.put(_path(first["upload_url"]), content=b"!")
    assert (server.root / "users/alice/models/uploads/evil.idf").exists()
    assert not (server.root / "users/bob/evil.idf").exists()


def test_upload_status_is_private(server):
    link = server.call("alice", action="request_upload", filename="a.idf")
    assert "error" in server.call("bob", action="upload_status", file_id=link["file_id"])


def test_expired_links_stop_working(server):
    link = server.call("alice", action="request_upload", filename="a.idf")
    for ticket in server.store._tickets.values():
        ticket.expires_at = time.time() - 1
    assert server.client.put(_path(link["upload_url"]), content=b"!").status_code == 404


def test_download_file_once_and_only_own_files(server):
    mine = server.root / "users/alice/runs/r1/eplusout.csv"
    mine.parent.mkdir(parents=True)
    mine.write_text("a,b\n1,2\n")
    (server.root / "users/bob/secret.idf").write_text("! bob\n")

    link = server.call("alice", action="request_download", path=str(mine))
    first = server.client.get(_path(link["download_url"]))
    assert first.status_code == 200 and first.content == b"a,b\n1,2\n"
    assert "eplusout.csv" in first.headers["content-disposition"]
    assert server.client.get(_path(link["download_url"])).status_code == 404  # single use

    stolen = server.call("alice", action="request_download", path=str(server.root / "users/bob/secret.idf"))
    assert "error" in stolen


def test_download_folder_as_zip_skips_links_out_of_scope(server):
    run = server.root / "users/alice/runs/r1"
    run.mkdir(parents=True)
    (run / "eplusout.err").write_text("ok\n")
    (server.root / "users/bob/secret.idf").write_text("! bob\n")
    os.symlink(server.root / "users/bob/secret.idf", run / "sneaky.idf")

    link = server.call("alice", action="request_download", path=str(run))
    assert link["filename"] == "r1.zip"
    response = server.client.get(_path(link["download_url"]))
    names = zipfile.ZipFile(io.BytesIO(response.content)).namelist()
    assert names == ["eplusout.err"]


def test_mcp_endpoint_still_requires_a_token(server):
    assert server.client.post("/mcp").status_code == 401
    ok = server.client.post("/mcp", headers={"Authorization": f"Bearer {ALICE_TOKEN}"})
    assert ok.status_code == 200


def test_stdio_mode_explains_the_tool_is_not_needed(server, monkeypatch):
    monkeypatch.setattr(server.cfg.transport, "transport", "stdio")
    result = server.call(None, action="list_uploads")
    assert "only needed over the HTTP transport" in result["error"]
