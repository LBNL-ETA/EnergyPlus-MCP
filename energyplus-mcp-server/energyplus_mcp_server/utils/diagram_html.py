"""
Self-contained HTML/SVG diagrams of HVAC loops, drawn from loop topology data.

Unlike ``diagrams.HVACDiagramGenerator`` this needs no Graphviz executable
and no network: the layout is computed here and written as an inline SVG, so
the file opens in any browser and in static previews. Each component carries a
tooltip with its name and inlet/outlet nodes, and a table below the drawing
lists every component with its nodes. Each side of a loop sits in a dashed
frame; clicking a frame focuses that side and filters the table. A few lines
of inline script do this without scrolling; without scripts, the frames are
plain links and CSS ``:target`` does the same.

EnergyPlus Model Context Protocol Server (EnergyPlus-MCP)
Copyright (c) 2025, The Regents of the University of California,
through Lawrence Berkeley National Laboratory (subject to receipt of
any required approvals from the U.S. Dept. of Energy). All rights reserved.

See License.txt in the parent directory for license details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any, Iterable

from energyplus_mcp_server.utils.diagrams import HVACDiagramGenerator

BOX_W = 150
BOX_H = 58
COL_GAP = 46
ROW_GAP = 16
LANE = 34          # room left and right of the frames for the loop-closing arrows
FRAME_PAD = 16     # space between a side's frame and its components
FRAME_TITLE = 30   # frame height above the first component row, for the side title
SIDE_GAP = 56      # vertical space between the supply and demand frames
TOP = 12

DEFAULT_COLOR = HVACDiagramGenerator.COMPONENT_COLORS["default"]


@dataclass
class _Node:
    id: str
    comp: dict
    connector: bool = False
    x: float = 0.0
    y: float = 0.0


@dataclass
class _Stage:
    """A column group: one series chain, one connector, or parallel lanes."""

    kind: str  # "series" | "connector" | "parallel"
    lanes: list[list[_Node]] = field(default_factory=list)

    @property
    def columns(self) -> int:
        return max((len(lane) for lane in self.lanes), default=0)

    def entries(self) -> list[_Node]:
        return [lane[0] for lane in self.lanes if lane]

    def exits(self) -> list[_Node]:
        return [lane[-1] for lane in self.lanes if lane]


class _Ids:
    def __init__(self) -> None:
        self.count = 0

    def next(self) -> str:
        self.count += 1
        return f"n{self.count}"


def _series(ids: _Ids, comps: Iterable[dict]) -> _Stage | None:
    lane = [_Node(ids.next(), c) for c in comps]
    return _Stage("series", [lane]) if lane else None


def _connector(ids: _Ids, comp: dict) -> _Stage:
    return _Stage("connector", [[_Node(ids.next(), comp, connector=True)]])


def _parallel(ids: _Ids, lanes: Iterable[Iterable[dict]]) -> _Stage | None:
    built = [[_Node(ids.next(), c) for c in lane] for lane in lanes]
    built = [lane for lane in built if lane]
    return _Stage("parallel", built) if built else None


def _plant_side_stages(ids: _Ids, side: dict) -> list[_Stage]:
    """Inlet branch -> splitter -> parallel branches -> mixer -> outlet branch."""
    branches = side.get("branches", [])
    by_name = {b.get("name"): b for b in branches}
    splitter = next((c for c in side.get("connector_lists", []) if c.get("type") == "Connector:Splitter"), None)
    mixer = next((c for c in side.get("connector_lists", []) if c.get("type") == "Connector:Mixer"), None)

    parallel_names = list(splitter.get("outlet_branches", [])) if splitter else []
    if mixer:
        parallel_names += [n for n in mixer.get("inlet_branches", []) if n not in parallel_names]
    inlet = by_name.get(splitter.get("inlet_branch")) if splitter else None
    outlet = by_name.get(mixer.get("outlet_branch")) if mixer else None

    if not splitter and not mixer:
        # No connectors: the branches run in series in the listed order.
        return [s for s in (_series(ids, b.get("components", [])) for b in branches) if s]

    used = {n for n in parallel_names} | {b.get("name") for b in (inlet, outlet) if b}
    if inlet is None:
        inlet = next((b for b in branches if b.get("name") not in used), None)
        if inlet:
            used.add(inlet.get("name"))
    if outlet is None:
        outlet = next((b for b in reversed(branches) if b.get("name") not in used), None)

    stages: list[_Stage | None] = []
    if inlet:
        stages.append(_series(ids, inlet.get("components", [])))
    if splitter:
        stages.append(_connector(ids, splitter))
    stages.append(_parallel(ids, (by_name[n].get("components", []) for n in parallel_names if n in by_name)))
    if mixer:
        stages.append(_connector(ids, mixer))
    if outlet and outlet is not inlet:
        stages.append(_series(ids, outlet.get("components", [])))
    return [s for s in stages if s]


def _air_supply_stages(ids: _Ids, side: dict) -> list[_Stage]:
    comps = side.get("components")
    if not comps:
        comps = [c for b in side.get("branches", []) for c in b.get("components", [])]
    stage = _series(ids, comps)
    return [stage] if stage else []


def _air_demand_stages(ids: _Ids, side: dict) -> list[_Stage]:
    """Zone splitter(s) -> zone terminals (parallel) -> return plenum(s) -> zone mixer(s)."""
    stages: list[_Stage | None] = [_connector(ids, s) for s in side.get("zone_splitters", [])]
    stages.append(_parallel(ids, ([eq] for eq in side.get("zone_equipment", []))))
    stages.extend(_connector(ids, p) for p in side.get("return_plenums", []))
    stages.extend(_connector(ids, m) for m in side.get("zone_mixers", []))
    return [s for s in stages if s]


def _layout(stages: list[_Stage], top: float, left: float) -> tuple[float, float]:
    """Place nodes column by column from ``left``; return (span width, height)."""
    rows = max((len(s.lanes) for s in stages), default=1)
    height = rows * BOX_H + (rows - 1) * ROW_GAP
    x = left
    for stage in stages:
        lane_count = len(stage.lanes)
        block = lane_count * BOX_H + (lane_count - 1) * ROW_GAP
        y0 = top + (height - block) / 2
        for row, lane in enumerate(stage.lanes):
            for col, node in enumerate(lane):
                node.x = x + col * (BOX_W + COL_GAP)
                node.y = y0 + row * (BOX_H + ROW_GAP)
        x += stage.columns * (BOX_W + COL_GAP)
    span = x - COL_GAP - left if stages else 0
    return span, height


def _mirror(stages: list[_Stage], left: float, inner_width: float) -> None:
    """Flip a side horizontally so its flow runs right to left."""
    for stage in stages:
        for lane in stage.lanes:
            for node in lane:
                node.x = left + inner_width - (node.x - left) - BOX_W


def _edges(stages: list[_Stage]) -> list[tuple[_Node, _Node]]:
    edges: list[tuple[_Node, _Node]] = []
    for stage in stages:
        for lane in stage.lanes:
            edges.extend(zip(lane, lane[1:]))
    for current, following in zip(stages, stages[1:]):
        sources, targets = current.exits(), following.entries()
        if len(sources) == len(targets) and current.kind == following.kind == "parallel":
            edges.extend(zip(sources, targets))
        else:
            edges.extend((s, t) for s in sources for t in targets)
    return edges


def _wrap(text: str, width: int = 20, lines: int = 2) -> list[str]:
    words, out, line = str(text).split(), [], ""
    for word in words:
        if len(line) + len(word) + (1 if line else 0) <= width:
            line = f"{line} {word}".strip()
        else:
            if line:
                out.append(line)
            line = word
    if line:
        out.append(line)
    if len(out) > lines:
        out = out[:lines]
        out[-1] = out[-1][: width - 1] + "…"
    return [o if len(o) <= width else o[: width - 1] + "…" for o in out]


TYPE_LABELS = {
    "AirLoopHVAC:OutdoorAirSystem": "OA System",
    "AirLoopHVAC:UnitarySystem": "Unitary System",
    "Coil:Cooling:DX:TwoSpeed": "DX Cooling (2-spd)",
    "Coil:Cooling:DX:VariableSpeed": "DX Cooling (VS)",
    "HeatExchanger:AirToAir:SensibleAndLatent": "Heat Recovery",
    "Pump:VariableSpeed": "Pump (VSD)",
    "Pump:ConstantSpeed": "Pump (CSD)",
}
TYPE_LABEL_MAX = 21


def _type_label(object_type: str) -> str:
    """Short type label that fits a box; the full type stays in the tooltip."""
    label = TYPE_LABELS.get(object_type) or HVACDiagramGenerator._abbrev_type(object_type).replace("\n", " ")
    if len(label) > TYPE_LABEL_MAX:
        label = " ".join(object_type.split(":")[-2:])
    if len(label) > TYPE_LABEL_MAX:
        label = label[: TYPE_LABEL_MAX - 1] + "…"
    return label


def _tooltip(comp: dict) -> str:
    parts = [f"{comp.get('type', '')}: {comp.get('name', '')}"]
    for key, label in (("inlet_node", "Inlet"), ("outlet_node", "Outlet"),
                       ("zone_name", "Zone"), ("inlet_branch", "Inlet branch")):
        if comp.get(key):
            parts.append(f"{label}: {comp[key]}")
    for key, label in (("inlet_nodes", "Inlets"), ("outlet_nodes", "Outlets"),
                       ("outlet_branches", "Outlet branches"), ("inlet_branches", "Inlet branches")):
        if comp.get(key):
            parts.append(f"{label}: {', '.join(map(str, comp[key]))}")
    return "\n".join(parts)


def _node_svg(node: _Node) -> str:
    comp = node.comp
    color = HVACDiagramGenerator.COMPONENT_COLORS.get(comp.get("type", ""), DEFAULT_COLOR)
    rx = BOX_H / 2 if node.connector else 8
    type_label = _type_label(comp.get("type", ""))
    name_lines = _wrap(comp.get("name", ""))
    text = [f'<text x="{node.x + BOX_W / 2:.1f}" y="{node.y + 20:.1f}" class="t">{escape(type_label)}</text>']
    for i, line in enumerate(name_lines):
        text.append(
            f'<text x="{node.x + BOX_W / 2:.1f}" y="{node.y + 36 + i * 13:.1f}" class="n">{escape(line)}</text>'
        )
    return (
        f'<g class="c"><title>{escape(_tooltip(comp))}</title>'
        f'<rect x="{node.x:.1f}" y="{node.y:.1f}" width="{BOX_W}" height="{BOX_H}" rx="{rx:.1f}" '
        f'fill="{color}" />{"".join(text)}</g>'
    )


def _edge_svg(a: _Node, b: _Node, rtl: bool, marker: str) -> str:
    if rtl:
        x1, x2 = a.x, b.x + BOX_W
    else:
        x1, x2 = a.x + BOX_W, b.x
    y1, y2 = a.y + BOX_H / 2, b.y + BOX_H / 2
    mid = (x1 + x2) / 2
    return (
        f'<path class="e" d="M{x1:.1f},{y1:.1f} C{mid:.1f},{y1:.1f} {mid:.1f},{y2:.1f} {x2:.1f},{y2:.1f}" '
        f'marker-end="url(#{marker}-e)" />'
    )


def _all_nodes(stages: list[_Stage]) -> list[_Node]:
    return [node for stage in stages for lane in stage.lanes for node in lane]


def _mid_y(nodes: list[_Node]) -> float:
    return sum(n.y for n in nodes) / len(nodes) + BOX_H / 2


def _side_group(gid: str, side: str, flow: str, frame: tuple[float, float, float, float],
                stages: list[_Stage], rtl: bool, marker: str) -> str:
    """One side of the loop: a dashed, clickable frame around its components."""
    x, y, w, h = frame
    parts = [
        f'<g id="{gid}" class="grp g-{side.lower()}">',
        f'<a href="#{gid}" class="frame-link"><title>Show only the {side.lower()} side</title>',
        f'<rect class="frame" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="12" />',
        f'<text class="side" x="{x + 14:.1f}" y="{y + 20:.1f}">{side} side'
        f'<tspan class="flow" dx="8">{flow}</tspan></text></a>',
    ]
    parts.extend(_edge_svg(a, b, rtl, marker) for a, b in _edges(stages))
    parts.extend(_node_svg(n) for n in _all_nodes(stages))
    parts.append("</g>")
    return "".join(parts)


def loop_svg(topology: dict, marker_id: str = "m") -> tuple[str, int]:
    """Return (svg markup, component count) for one loop's topology.

    The supply side runs left to right in the upper frame and the demand side
    right to left in the lower one; the loop is closed outside the frames by a
    red (supply outlet -> demand inlet) and a blue (demand outlet -> supply
    inlet) arrow, each labelled with its node.
    """
    ids = _Ids()
    supply = topology.get("supply_side", {}) or {}
    demand = topology.get("demand_side", {}) or {}
    if topology.get("loop_type") == "AirLoopHVAC":
        supply_stages = _air_supply_stages(ids, supply)
        demand_stages = _air_demand_stages(ids, demand)
    else:
        supply_stages = _plant_side_stages(ids, supply)
        demand_stages = _plant_side_stages(ids, demand)

    content_left = LANE + FRAME_PAD
    supply_frame_y = TOP
    supply_span, supply_h = _layout(supply_stages, supply_frame_y + FRAME_TITLE, content_left)
    demand_frame_y = supply_frame_y + FRAME_TITLE + supply_h + FRAME_PAD + SIDE_GAP
    demand_span, demand_h = _layout(demand_stages, demand_frame_y + FRAME_TITLE, content_left)
    inner = max(supply_span, demand_span, 360)
    _mirror(demand_stages, content_left, inner)

    frame_x, frame_w = LANE, inner + 2 * FRAME_PAD
    supply_frame = (frame_x, supply_frame_y, frame_w, FRAME_TITLE + supply_h + FRAME_PAD)
    demand_frame = (frame_x, demand_frame_y, frame_w, FRAME_TITLE + demand_h + FRAME_PAD)
    width = frame_x + frame_w + LANE
    height = demand_frame_y + demand_frame[3] + TOP

    m = escape(marker_id)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width:.0f} {height:.0f}" role="img" '
        f'aria-label="{escape(str(topology.get("loop_name", "HVAC loop")))}"><defs>',
    ]
    for name, cls in (("e", "ah"), ("hot", "ah-hot"), ("cold", "ah-cold")):
        parts.append(
            f'<marker id="{m}-{name}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" '
            f'markerHeight="9" markerUnits="userSpaceOnUse" orient="auto-start-reverse">'
            f'<path d="M0,0 L10,5 L0,10 z" class="{cls}"/></marker>'
        )
    parts.append("</defs>")

    supply_nodes, demand_nodes = _all_nodes(supply_stages), _all_nodes(demand_stages)
    if supply_nodes and demand_nodes:
        s_out, d_in = supply_stages[-1].exits(), demand_stages[0].entries()
        d_out, s_in = demand_stages[-1].exits(), supply_stages[0].entries()
        right, left = frame_x + frame_w + LANE / 2, LANE / 2
        sy, dy = _mid_y(s_out), _mid_y(d_in)
        oy, iy = _mid_y(d_out), _mid_y(s_in)
        sx = max(n.x for n in s_out) + BOX_W
        dx = max(n.x for n in d_in) + BOX_W
        ox = min(n.x for n in d_out)
        ix = min(n.x for n in s_in)
        gap_y = supply_frame_y + supply_frame[3] + SIDE_GAP / 2
        parts.append('<g class="links">')
        parts.append(
            f'<path class="hot" d="M{sx:.1f},{sy:.1f} H{right:.1f} V{dy:.1f} H{dx + 2:.1f}" '
            f'marker-end="url(#{m}-hot)"/>'
        )
        parts.append(
            f'<path class="cold" d="M{ox:.1f},{oy:.1f} H{left:.1f} V{iy:.1f} H{ix - 2:.1f}" '
            f'marker-end="url(#{m}-cold)"/>'
        )
        for label, x, anchor, cls in (
            (supply.get("outlet_node"), right - 8, "end", "node hot-t"),
            (demand.get("outlet_node"), left + 8, "start", "node cold-t"),
        ):
            if label:
                parts.append(
                    f'<text x="{x:.1f}" y="{gap_y + 4:.1f}" class="{cls}" text-anchor="{anchor}">'
                    f"{escape(str(label))}</text>"
                )
        parts.append("</g>")

    parts.append(_side_group(f"{m}-supply", "Supply", "flow →", supply_frame, supply_stages, False, m))
    parts.append(_side_group(f"{m}-demand", "Demand", "← flow", demand_frame, demand_stages, True, m))
    parts.append("</svg>")
    return "".join(parts), len(supply_nodes) + len(demand_nodes)


def _component_rows(topology: dict) -> list[tuple[str, str, str, str, str]]:
    rows = []
    for side_key, side_label in (("supply_side", "Supply"), ("demand_side", "Demand")):
        side = topology.get(side_key, {}) or {}
        if side.get("branches"):
            for branch in side["branches"]:
                for comp in branch.get("components", []):
                    rows.append((side_label, branch.get("name", ""), comp.get("type", ""),
                                 comp.get("name", ""), f"{comp.get('inlet_node', '')} → {comp.get('outlet_node', '')}"))
        else:
            for comp in side.get("components", []):
                rows.append((side_label, "", comp.get("type", ""), comp.get("name", ""),
                             f"{comp.get('inlet_node', '')} → {comp.get('outlet_node', '')}"))
        for key in ("connector_lists", "zone_splitters", "zone_equipment", "return_plenums", "zone_mixers"):
            for comp in side.get(key, []):
                inlets = comp.get("inlet_node") or ", ".join(comp.get("inlet_nodes", [])) or comp.get("inlet_branch", "")
                outlets = (comp.get("outlet_node") or ", ".join(comp.get("outlet_nodes", []))
                           or ", ".join(comp.get("outlet_branches", [])) or comp.get("outlet_branch", ""))
                rows.append((side_label, "", comp.get("type", ""), comp.get("name", ""), f"{inlets} → {outlets}"))
    return rows


_CSS = """
:root{color-scheme:light dark;--bg:#fff;--fg:#1a202c;--muted:#5a6578;--line:#4a5568;--card:#f7f8fa;
--border:#e2e8f0;--frame:#a0aec0;--accent:#2b6cb0;--accent-bg:rgba(43,108,176,.06)}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--fg:#e8ebf0;--muted:#9aa4b2;--line:#a0aec0;
--card:#1c2027;--border:#2d3440;--frame:#5a6578;--accent:#63b3ed;--accent-bg:rgba(99,179,237,.08)}}
body{margin:0;padding:20px;background:var(--bg);color:var(--fg);
font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
h1{font-size:20px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 6px}.meta{color:var(--muted);margin:0 0 12px}
h2 .meta{font-weight:400}.reset{font-size:12.5px;font-weight:400;margin-left:10px;color:var(--accent)}
.scroll{overflow-x:auto;border:1px solid var(--border);border-radius:10px;background:var(--card);padding:6px}
svg text{font-family:inherit}svg .t{font-size:12px;font-weight:600;fill:#fff;text-anchor:middle}
svg .n{font-size:10.5px;fill:#fff;text-anchor:middle;opacity:.92}
svg .side{font-size:13px;font-weight:600;fill:var(--fg)}svg .flow{font-weight:400;fill:var(--muted)}
svg .frame{fill:transparent;stroke:var(--frame);stroke-width:1.3;stroke-dasharray:7 5}
svg .frame-link{cursor:pointer}svg .frame-link:hover .frame{stroke:var(--accent);fill:var(--accent-bg)}
svg .node{font-size:10.5px}svg .hot-t{fill:#C53030}svg .cold-t{fill:#2B6CB0}
svg .e{fill:none;stroke:var(--line);stroke-width:1.4}svg .ah{fill:var(--line)}
svg .hot{fill:none;stroke:#E53E3E;stroke-width:2.4}svg .ah-hot{fill:#E53E3E}
svg .cold{fill:none;stroke:#3182CE;stroke-width:2.4}svg .ah-cold{fill:#3182CE}
svg .c rect{stroke:rgba(0,0,0,.18)}svg .grp,svg .links{transition:opacity .15s}
/* Focus a side. _SCRIPT sets data-focus on the loop without scrolling; where scripts cannot
   run, the frame links still focus it through :target (#<loop>-supply / #<loop>-demand). */
svg .grp:target .frame,.loop[data-focus=supply] .g-supply .frame,.loop[data-focus=demand] .g-demand .frame
{stroke:var(--accent);stroke-width:2;stroke-dasharray:none;fill:var(--accent-bg)}
.loop:has(.grp:target) .grp:not(:target),.loop:has(.grp:target) .links,
.loop[data-focus=supply] .g-demand,.loop[data-focus=demand] .g-supply,.loop[data-focus] .links{opacity:.2}
.loop:has(.g-supply:target) tr.r-demand,.loop:has(.g-demand:target) tr.r-supply,
.loop[data-focus=supply] tr.r-demand,.loop[data-focus=demand] tr.r-supply{display:none}
.loop .reset{display:none}.loop:has(.grp:target) .reset,.loop[data-focus] .reset{display:inline}
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;margin:10px 0 0;color:var(--muted);font-size:12px}
.legend span{display:inline-flex;align-items:center;gap:6px}.legend i{width:12px;height:12px;border-radius:3px;display:inline-block}
details{margin-top:10px}table{border-collapse:collapse;width:100%;font-size:12.5px;margin-top:6px}
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--border);vertical-align:top}th{color:var(--muted);font-weight:600}
"""


# Optional enhancement (no network): focus a side in place, and click again to unfocus.
_SCRIPT = """
document.addEventListener("click", function (event) {
  var link = event.target.closest("a.frame-link, a.reset");
  if (!link) return;
  event.preventDefault();
  var loop = link.closest(".loop");
  var side = link.classList.contains("reset") ? "" : (/-supply$/.test(link.getAttribute("href")) ? "supply" : "demand");
  if (!side || loop.dataset.focus === side) { delete loop.dataset.focus; } else { loop.dataset.focus = side; }
  if (location.hash) history.replaceState(null, "", location.pathname + location.search);
});
"""


def _legend(topology: dict) -> str:
    types = sorted({row[2] for row in _component_rows(topology)})
    items = [
        f'<span><i style="background:{HVACDiagramGenerator.COMPONENT_COLORS.get(t, DEFAULT_COLOR)}"></i>{escape(t)}</span>'
        for t in types
    ]
    return f'<div class="legend">{"".join(items)}</div>' if items else ""


def render_loops_html(topologies: list[dict], title: str, show_legend: bool = True) -> tuple[str, int]:
    """Render one or more loop topologies into a single self-contained HTML page."""
    sections, total = [], 0
    for index, topo in enumerate(topologies, start=1):
        loop_id = f"loop{index}"
        svg, count = loop_svg(topo, loop_id)
        total += count
        rows = "".join(
            f'<tr class="r-{row[0].lower()}">' + "".join(f"<td>{escape(str(v))}</td>" for v in row) + "</tr>"
            for row in _component_rows(topo)
        )
        sections.append(
            f'<section class="loop" id="{loop_id}">'
            f'<h2>{escape(str(topo.get("loop_name", "")))} <span class="meta">('
            f'{escape(str(topo.get("loop_type", "")))}, {count} components)</span>'
            f'<a class="reset" href="#{loop_id}">Show both sides</a></h2>'
            f'<div class="scroll">{svg}</div>'
            + (_legend(topo) if show_legend else "")
            + '<details><summary>Components and nodes</summary><table><thead><tr><th>Side</th><th>Branch</th>'
            '<th>Type</th><th>Name</th><th>Inlet → outlet</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></details></section>"
        )
    html = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title><style>{_CSS}</style></head><body>"
        f"<h1>{escape(title)}</h1>"
        '<p class="meta">Click a dashed frame to focus on the supply or demand side (the component table '
        "follows). Red: supply outlet to demand inlet; blue: demand outlet back to supply inlet. "
        "Hover a component for its nodes.</p>"
        + "".join(sections)
        + f"<script>{_SCRIPT}</script></body></html>"
    )
    return html, total


def write_loops_html(topologies: list[dict], output_path: str, title: str, show_legend: bool = True) -> dict[str, Any]:
    html, total = render_loops_html(topologies, title, show_legend)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(html)
    return {
        "success": True,
        "output_file": output_path,
        "loop_name": topologies[0].get("loop_name") if len(topologies) == 1 else "all_loops",
        "loops_drawn": [t.get("loop_name") for t in topologies],
        "components_drawn": total,
        "diagram_type": "html_topology",
    }
