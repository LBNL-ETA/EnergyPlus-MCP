"""HVAC loop diagrams: Graphviz images, self-contained HTML, and the fallback chain.

The fixture is the real topology of the EnergyPlus 26.1 5ZoneAirCooled example
(one VAV air loop, a hot-water loop and a chilled-water loop).
"""

import json
import re
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from energyplus_mcp_server.energyplus_tools import EnergyPlusManager
from energyplus_mcp_server.utils.diagram_html import render_loops_html, write_loops_html
from energyplus_mcp_server.utils.diagrams import HVACDiagramGenerator

FIXTURE = Path(__file__).parent / "fixtures" / "loop_topology" / "5ZoneAirCooled.json"
TOPOLOGY = json.loads(FIXTURE.read_text())
SERVER_DIR = Path(__file__).resolve().parents[1]


def _component_names(topology: dict) -> set[str]:
    names = set()
    for side in ("supply_side", "demand_side"):
        data = topology[side]
        for branch in data.get("branches", []):
            names.update(c["name"] for c in branch.get("components", []))
        names.update(c["name"] for c in data.get("components", []))
        for key in ("connector_lists", "zone_splitters", "zone_mixers", "zone_equipment", "return_plenums"):
            names.update(c["name"] for c in data.get(key, []))
    return names


@pytest.mark.parametrize("loop_name", sorted(TOPOLOGY))
def test_html_draws_every_component_with_its_nodes(loop_name):
    topology = TOPOLOGY[loop_name]
    html, drawn = render_loops_html([topology], "test")

    svg_titles = re.findall(r"<g class=\"c\"><title>(.*?)</title>", html, re.S)
    for name in _component_names(topology):
        assert any(name in title for title in svg_titles), f"{name} is not drawn"
    # Every drawn box has a tooltip; the loop's own inlet/outlet nodes are shown.
    assert drawn == len(svg_titles)
    assert topology["supply_side"]["outlet_node"] in html
    assert topology["demand_side"]["outlet_node"] in html


def test_html_is_self_contained():
    html, _ = render_loops_html(list(TOPOLOGY.values()), "test")

    # Only the small inline focus script; nothing is loaded from elsewhere.
    assert html.count("<script") == 1 and "<script>" in html
    assert not re.search(r"""(?:src|href)=["']?https?://""", html)
    assert "@import" not in html
    assert html.count("<svg") == 3


def test_html_escapes_model_names():
    topology = json.loads(json.dumps(TOPOLOGY["Hot Water Loop"]))
    topology["supply_side"]["branches"][0]["components"][0]["name"] = "<img src=x onerror=alert(1)>"

    html, _ = render_loops_html([topology], "<b>title</b>")

    assert "<img" not in html
    assert "<b>title" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_parallel_plant_branches_fan_out_and_back_in():
    html, drawn = render_loops_html([TOPOLOGY["Hot Water Loop"]], "test")
    # Supply: pump, splitter, boiler + bypass, mixer, outlet pipe = 6.
    # Demand: inlet pipe, splitter, 8 coil/bypass branches, mixer, outlet pipe = 12.
    assert drawn == 18
    # splitter -> 2 supply branches -> mixer, and splitter -> 8 demand branches -> mixer
    edges = html.count('class="e"')
    assert edges == (1 + 2 + 2 + 1) + (1 + 8 + 8 + 1)


def test_write_loops_html_reports_what_it_drew(tmp_path):
    result = write_loops_html(list(TOPOLOGY.values()), str(tmp_path / "loops.html"), "t")

    assert result["diagram_type"] == "html_topology"
    assert result["loop_name"] == "all_loops"
    assert result["loops_drawn"] == list(TOPOLOGY)
    assert Path(result["output_file"]).read_text().startswith("<!DOCTYPE html>")


def test_failed_graphviz_render_leaves_no_dot_source(tmp_path, monkeypatch):
    def _fail(self, filename=None, **_kwargs):
        Path(filename).write_text("digraph {}")  # what graphviz writes before running dot
        raise RuntimeError("failed to execute PosixPath('dot')")

    monkeypatch.setattr("graphviz.Digraph.render", _fail)
    with pytest.raises(RuntimeError):
        HVACDiagramGenerator().create_diagram_from_topology(
            json.dumps(TOPOLOGY["Hot Water Loop"]), str(tmp_path / "loop.png")
        )

    assert list(tmp_path.iterdir()) == []


# -- EnergyPlusManager.visualize_loop_diagram -------------------------------------------------


def _manager(tmp_path, monkeypatch, render=None):
    manager = EnergyPlusManager.__new__(EnergyPlusManager)
    manager.config = SimpleNamespace(paths=SimpleNamespace(reports_dir=str(tmp_path)))
    manager.diagram_generator = HVACDiagramGenerator()
    idf = tmp_path / "Model.idf"
    idf.write_text("Version,26.1;\n")
    manager._resolve_idf_path = lambda path: str(idf)
    manager.discover_hvac_loops = lambda _path: json.dumps({
        "plant_loops": [{"name": "Hot Water Loop"}, {"name": "Chilled Water Loop"}],
        "condenser_loops": [],
        "air_loops": [{"name": "VAV Sys 1"}],
    })
    manager.get_loop_topology = lambda _path, name: json.dumps(TOPOLOGY[name])
    monkeypatch.setattr(
        "energyplus_mcp_server.energyplus_tools.report_path",
        lambda _config, name: str(tmp_path / name),
    )
    if render is not None:
        monkeypatch.setattr("graphviz.Digraph.render", render)
    return manager


def _no_dot(self, filename=None, **_kwargs):
    raise RuntimeError("failed to execute PosixPath('dot'), make sure the Graphviz executables are on your systems' PATH")


def test_png_falls_back_to_html_and_says_why(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch, render=_no_dot)

    result = json.loads(manager.visualize_loop_diagram("Model.idf", "VAV Sys 1", format="png"))

    assert result["success"] is True
    assert result["diagram_type"] == "html_topology"
    assert result["requested_format"] == "png"
    assert "Graphviz" in result["fallback_reason"] and "dot" in result["fallback_reason"]
    assert result["output_file"].endswith("Model_VAV Sys 1_diagram.html")
    assert "SPACE5-1 VAV Reheat" in Path(result["output_file"]).read_text()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Model.idf", "Model_VAV Sys 1_diagram.html"]


def test_html_without_loop_name_draws_every_loop(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)

    result = json.loads(manager.visualize_loop_diagram("Model.idf", None, format="html"))

    assert result["success"] is True
    assert result["loops_drawn"] == ["Hot Water Loop", "Chilled Water Loop", "VAV Sys 1"]
    assert "fallback_reason" not in result


def test_unknown_loop_is_an_error_not_an_empty_diagram(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)

    result = json.loads(manager.visualize_loop_diagram("Model.idf", "Condenser Loop", format="png"))

    assert result["success"] is False
    assert result["available_loops"] == ["Hot Water Loop", "Chilled Water Loop", "VAV Sys 1"]
    assert [p.name for p in tmp_path.iterdir()] == ["Model.idf"]


def test_unsupported_format_is_refused(tmp_path, monkeypatch):
    result = json.loads(_manager(tmp_path, monkeypatch).visualize_loop_diagram("Model.idf", None, format="gif"))

    assert result["success"] is False


def test_requested_image_format_reaches_graphviz(tmp_path, monkeypatch):
    seen = {}

    def _render(self, filename=None, format=None, **_kwargs):
        seen["format"] = format
        out = f"{filename}.{format}"
        Path(out).write_text("svg")
        return out

    manager = _manager(tmp_path, monkeypatch, render=_render)
    result = json.loads(manager.visualize_loop_diagram("Model.idf", "Hot Water Loop", format="svg"))

    assert seen["format"] == "svg"
    assert result["diagram_type"] == "graphviz_hierarchical"
    assert result["output_file"].endswith(".svg")


@pytest.mark.skipif(shutil.which("dot") is None, reason="Graphviz dot not installed")
def test_graphviz_renders_a_real_png(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)

    result = json.loads(manager.visualize_loop_diagram("Model.idf", "VAV Sys 1", format="png"))

    assert result["diagram_type"] == "graphviz_hierarchical"
    assert Path(result["output_file"]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_production_image_installs_graphviz():
    dockerfile = (SERVER_DIR / "Dockerfile.prod").read_text()
    runtime = dockerfile.split("AS runtime", 1)[1]
    install = re.search(r"apt-get install[^&]*", runtime).group(0)
    assert re.search(r"\bgraphviz\b", install), "runtime stage must install graphviz (the dot program)"


def test_html_is_the_default_format(tmp_path, monkeypatch):
    def _unexpected(self, *args, **kwargs):
        raise AssertionError("Graphviz must not run for the default format")

    manager = _manager(tmp_path, monkeypatch, render=_unexpected)

    result = json.loads(manager.visualize_loop_diagram("Model.idf"))

    assert result["diagram_type"] == "html_topology"
    assert result["loops_drawn"] == ["Hot Water Loop", "Chilled Water Loop", "VAV Sys 1"]
    assert result["output_file"].endswith("Model_hvac_diagram.html")


def test_hvac_manager_tool_defaults_to_html():
    import inspect

    from energyplus_mcp_server.domains import hvac
    from energyplus_mcp_server.tools import hvac_loop

    assert inspect.signature(hvac.hvac_visualize).parameters["image_format"].default == "html"
    source = inspect.getsource(hvac)
    assert 'image_format: str = "png"' not in source
    assert '= "html"' in inspect.getsource(hvac_loop)


# -- review fixes ------------------------------------------------------------------------------


def _unreadable(manager, *bad_loops):
    good = manager.get_loop_topology

    def _topology(path, name):
        if name in bad_loops:
            raise RuntimeError(f"Error getting loop topology: broken {name}")
        return good(path, name)

    manager.get_loop_topology = _topology


def test_html_skips_an_unreadable_loop_and_draws_the_rest(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    _unreadable(manager, "Chilled Water Loop")

    result = json.loads(manager.visualize_loop_diagram("Model.idf"))

    assert result["success"] is True
    assert result["diagram_type"] == "html_topology"
    assert result["loops_drawn"] == ["Hot Water Loop", "VAV Sys 1"]
    assert result["skipped_loops"][0]["loop_name"] == "Chilled Water Loop"
    assert "broken Chilled Water Loop" in result["skipped_loops"][0]["error"]


def test_unreadable_topology_falls_back_to_sketch_and_blames_topology(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch, render=_no_dot)
    _unreadable(manager, "Hot Water Loop")
    sketches = []

    def _sketch(idf_path, loop_name, output_path, fmt):
        sketches.append((output_path, fmt))
        return {"success": True, "output_file": output_path, "diagram_type": "simplified"}

    manager._create_simplified_diagram = _sketch

    for fmt in ("html", "png"):
        result = json.loads(manager.visualize_loop_diagram("Model.idf", "Hot Water Loop", format=fmt))
        assert result["diagram_type"] == "simplified"
        assert result["fallback_reason"].startswith("Could not read loop topology")
        assert "Graphviz" not in result["fallback_reason"]
        assert result["requested_format"] == fmt

    # matplotlib cannot write HTML: the sketch for an html request is a PNG.
    assert [Path(path).suffix for path, _ in sketches] == [".png", ".png"]
    assert [fmt for _, fmt in sketches] == ["png", "png"]


def test_html_creates_a_missing_output_folder(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch)
    target = tmp_path / "new" / "nested" / "loops.html"

    result = json.loads(manager.visualize_loop_diagram("Model.idf", output_path=str(target)))

    assert result["success"] is True
    assert target.is_file()


def test_format_none_means_html(tmp_path, monkeypatch):
    manager = _manager(tmp_path, monkeypatch, render=lambda *a, **k: pytest.fail("Graphviz ran"))

    result = json.loads(manager.visualize_loop_diagram("Model.idf", None, None, None))

    assert result["diagram_type"] == "html_topology"
