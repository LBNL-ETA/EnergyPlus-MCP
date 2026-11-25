"""HTML viewers are saved to files; replies carry the path, not the page."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from energyplus_mcp_server.domains import envelope, geometry, hvac
from tests.test_scope import as_alice, http_config  # noqa: F401  (fixtures)

PAGE = "<!DOCTYPE html><html><body>" + "x" * 5000 + "</body></html>"


class FakeManager:
    def generate_geometry_html(self, idf_path):
        return PAGE

    def generate_envelope_html(self, idf_path):
        return PAGE


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self, *args, **kwargs):
        def capture(fn):
            self.tools[kwargs.get("name") or fn.__name__] = fn
            return fn
        return capture


def _stdio_config(tmp_path):
    reports = tmp_path / "work" / "reports"
    return SimpleNamespace(
        transport=SimpleNamespace(transport="stdio"),
        paths=SimpleNamespace(workspace_root=str(tmp_path), reports_dir=str(reports)),
    )


def _tools(config, manager=None):
    mcp = FakeMCP()
    for module in (geometry, envelope):
        module.register(mcp, manager or FakeManager(), config)
    return mcp.tools


@pytest.mark.parametrize("tool, viewer", [("geometry_manager", "geometry"), ("envelope_manager", "envelope")])
def test_viewer_is_saved_and_the_reply_names_it(tmp_path, tool, viewer):
    tools = _tools(_stdio_config(tmp_path))

    reply = json.loads(asyncio.run(tools[tool](action="generate_html_str", idf_path="/m/Model.idf")))

    saved = tmp_path / "work" / "reports" / f"Model_{viewer}.html"
    assert reply["success"] is True and reply["output_file"] == str(saved)
    assert saved.read_text() == PAGE
    assert reply["workspace_path"] == f"work/reports/Model_{viewer}.html"
    assert reply["bytes"] == len(PAGE) and reply["viewer"] == viewer
    assert "browser" in reply["how_to_open"]
    assert len(json.dumps(reply)) < 600


@pytest.mark.parametrize("tool", ["geometry_manager", "envelope_manager"])
def test_return_html_keeps_the_inline_page(tmp_path, tool):
    tools = _tools(_stdio_config(tmp_path))

    assert asyncio.run(tools[tool](action="generate_html_str", idf_path="/m/Model.idf", return_html=True)) == PAGE
    assert not (tmp_path / "work" / "reports").exists()


def test_output_path_chooses_the_file(tmp_path):
    tools = _tools(_stdio_config(tmp_path))
    target = tmp_path / "views" / "house.html"

    reply = json.loads(asyncio.run(tools["geometry_manager"](
        action="generate_html_str", idf_path="/m/Model.idf", output_path=str(target))))

    assert reply["output_file"] == str(target) and target.read_text() == PAGE


def test_http_reply_uses_the_workspace_path_and_download_instructions(http_config, as_alice, tmp_path):  # noqa: F811
    tools = _tools(http_config)

    reply = json.loads(asyncio.run(tools["geometry_manager"](action="generate_html_str", idf_path="/m/Model.idf")))

    assert reply["workspace_path"] == "reports/Model_geometry.html"
    assert Path(reply["output_file"]).is_file()
    assert "file_transfer(action='request_download', path='reports/Model_geometry.html')" in reply["how_to_open"]


def test_visualize_reply_gains_workspace_path(tmp_path):
    diagram = tmp_path / "work" / "reports" / "Model_hvac_diagram.html"
    diagram.parent.mkdir(parents=True)
    diagram.write_text(PAGE)

    class VisualizingManager(FakeManager):
        def visualize_loop_diagram(self, *args):
            return json.dumps({"success": True, "output_file": str(diagram), "diagram_type": "html_topology"})

    mcp = FakeMCP()
    hvac.register(mcp, VisualizingManager(), _stdio_config(tmp_path))

    reply = json.loads(asyncio.run(mcp.tools["hvac_manager"](action="visualize", idf_path="/m/Model.idf")))

    assert reply["workspace_path"] == "work/reports/Model_hvac_diagram.html"
    assert reply["diagram_type"] == "html_topology" and "how_to_open" in reply


def test_visualize_failure_passes_through(tmp_path):
    class FailingManager(FakeManager):
        def visualize_loop_diagram(self, *args):
            return json.dumps({"success": False, "error": "Loop 'X' not found"})

    mcp = FakeMCP()
    hvac.register(mcp, FailingManager(), _stdio_config(tmp_path))

    reply = json.loads(asyncio.run(mcp.tools["hvac_manager"](action="visualize", idf_path="/m/Model.idf", loop_name="X")))

    assert reply == {"success": False, "error": "Loop 'X' not found"}
