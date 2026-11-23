"""
Utility for generating HVAC loop diagrams from topology data.

EnergyPlus Model Context Protocol Server (EnergyPlus-MCP)
Copyright (c) 2025, The Regents of the University of California,
through Lawrence Berkeley National Laboratory (subject to receipt of
any required approvals from the U.S. Dept. of Energy). All rights reserved.

See License.txt in the parent directory for license details.
"""

import json
from graphviz import Digraph  # first and only import shown
import os


class HVACDiagramGenerator:
    """Generate a hierarchical HVAC loop diagram with Graphviz."""

    # Color maps -------------------------------------------------------------
    COMPONENT_COLORS = {  # node fill colours
        'Pump:VariableSpeed': '#4CAF50',
        'Pump:ConstantSpeed': '#4CAF50',
        'Chiller:Electric': '#2196F3',
        'Chiller:Absorption': '#2196F3',
        'Boiler:HotWater': '#FF5722',
        'Coil:Cooling:Water': '#00BCD4',
        'Coil:Heating:Water': '#FF9800',
        'Pipe:Adiabatic': '#9E9E9E',
        'default': '#607D8B',
        'Connector:Splitter': '#E91E63',
        'Connector:Mixer': '#3F51B5',
        # Air loop components
        'AirLoopHVAC:ZoneSplitter': '#E91E63',
        'AirLoopHVAC:ZoneMixer': '#3F51B5',
        'AirLoopHVAC:ReturnPlenum': '#9C27B0',
        'AirTerminal:SingleDuct:VAV:Reheat': '#FF5722',
        'AirTerminal:SingleDuct:ConstantVolume:NoReheat': '#FF9800',
        'AirTerminal:SingleDuct:VAV:NoReheat': '#FF5722',
        'Fan:VariableVolume': '#4CAF50',
        'Fan:ConstantVolume': '#4CAF50',
        'Coil:Cooling:DX:SingleSpeed': '#00BCD4',
        'Coil:Heating:Electric': '#FF5722',
        'Coil:Heating:Gas': '#FF5722',
    }

    NODE_STYLE = {'shape': 'box', 'style': 'rounded,filled', 'fontname': 'Helvetica'}
    CONNECTOR_STYLE = {'shape': 'ellipse', 'style': 'filled', 'fontsize': '10'}

    # Public API -------------------------------------------------------------
    def create_diagram_from_topology(
        self,
        topology_json: str,
        output_path: str,
        title: str | None = None,
        fmt: str = "png",
        show_legend: bool = True,
    ) -> dict:
        """Parse JSON, build a Graphviz Digraph, and render to file."""
        data = json.loads(topology_json)

        dot = Digraph(comment=title or data.get("loop_name", "HVAC Loop"))
        dot.attr(rankdir="LR", splines="spline", nodesep="0.35", ranksep="0.6")

        # Collect used component types for the legend (only if needed)
        used_types = set()
        if show_legend:
            # Handle plant/condenser loops
            for side in ["supply_side", "demand_side"]:
                for branch in data[side].get("branches", []):
                    for comp in branch.get("components", []):
                        used_types.add(comp["type"])
                for conn in data[side].get("connector_lists", []):
                    used_types.add(conn["type"])
                
                # Handle air loop components
                for splitter in data[side].get("zone_splitters", []):
                    used_types.add(splitter["type"])
                for mixer in data[side].get("zone_mixers", []):
                    used_types.add(mixer["type"])
                for plenum in data[side].get("return_plenums", []):
                    used_types.add(plenum["type"])
                for equipment in data[side].get("zone_equipment", []):
                    used_types.add(equipment["type"])

        # Determine loop type and build accordingly
        loop_type = data.get("loop_type", "")
        
        if loop_type == "AirLoopHVAC":
            # Build air loop diagram with air-specific logic
            self._build_air_loop_side(dot, data["supply_side"], side="Supply")
            self._build_air_loop_side(dot, data["demand_side"], side="Demand")
        else:
            # Build plant/condenser loop with existing logic
            self._build_side(dot, data["supply_side"], side="Supply", rank="same")
            self._build_side(dot, data["demand_side"], side="Demand", rank="same")

        # Cross-link supply-demand (supply out → demand in, return back)
        dot.edge("Supply_outlet", "Demand_inlet", color="#E53E3E", penwidth="3")
        dot.edge("Demand_outlet", "Supply_inlet", color="#3182CE", penwidth="3")

        # Add legend cluster only if requested
        if show_legend:
            self._add_compact_legend(dot, used_types)

        # Remove extension from output_path since dot.render() will add it automatically
        filename_without_ext = os.path.splitext(output_path)[0]
        
        filepath = dot.render(filename=filename_without_ext, format=fmt, cleanup=True)

        return {
            "success": True,
            "output_file": filepath,
            "loop_name": data.get("loop_name"),
            "components_drawn": self._count_components(data),
            "diagram_type": "graphviz_hierarchical",
        }

    # Internal helpers -------------------------------------------------------
    def _build_side(self, dot: Digraph, side_data: dict, *, side: str, rank: str):
        """Create a subgraph cluster for one side of the loop with proper HVAC flow topology."""
        with dot.subgraph(name=f"cluster_{side.lower()}") as c:
            c.attr(label=f"{side} Side", labelloc="t", fontsize="14")

            # Pseudo-nodes to anchor cross-loop arrows
            c.node(f"{side}_inlet", "", shape="point", width="0.01")
            c.node(f"{side}_outlet", "", shape="point", width="0.01")

            branches = side_data.get("branches", [])
            connectors = side_data.get("connector_lists", [])
            
            # Find splitter and mixer
            splitter = None
            mixer = None
            for conn in connectors:
                if conn["type"] == "Connector:Splitter":
                    splitter = conn
                elif conn["type"] == "Connector:Mixer":
                    mixer = conn
            
            # Create a mapping of branch names to their components
            branch_map = {branch["name"]: branch for branch in branches}
            
            # Step 1: Find inlet branch (typically first branch or branch feeding splitter)
            inlet_branch = None
            if splitter:
                inlet_branch_name = splitter.get("inlet_branch")
                inlet_branch = branch_map.get(inlet_branch_name)
            
            if not inlet_branch and branches:
                # Fallback: use first branch as inlet
                inlet_branch = branches[0]
            
            # Step 2: Find outlet branch (typically last branch or branch from mixer)
            outlet_branch = None
            if mixer:
                # For mixer, the outlet branch is the single outlet_branch
                outlet_branch_name = mixer.get("outlet_branch")
                if outlet_branch_name and outlet_branch_name != "Unknown":
                    outlet_branch = branch_map.get(outlet_branch_name)
            
            if not outlet_branch and branches:
                # Fallback: use last branch as outlet if it's not the inlet and not in parallel branches
                last_branch = branches[-1]
                if last_branch != inlet_branch:
                    # Check if it's not a parallel branch
                    parallel_branch_names = set()
                    if splitter:
                        parallel_branch_names.update(splitter.get("outlet_branches", []))
                    if mixer:
                        parallel_branch_names.update(mixer.get("inlet_branches", []))
                    
                    if last_branch["name"] not in parallel_branch_names:
                        outlet_branch = last_branch
            
            # Step 3: Find parallel branches (branches between splitter and mixer)
            parallel_branches = []
            if splitter:
                for branch_name in splitter.get("outlet_branches", []):
                    branch = branch_map.get(branch_name)
                    if branch:
                        parallel_branches.append(branch)
            
            # Step 4: Build the flow diagram
            
            # Draw inlet branch if it exists
            if inlet_branch:
                last_node = f"{side}_inlet"
                for comp_idx, comp in enumerate(inlet_branch["components"]):
                    comp_id = f"{inlet_branch['name']}_{comp_idx}"
                    self._draw_component(c, comp_id, comp)
                    
                    if last_node:
                        c.edge(last_node, comp_id)
                    last_node = comp_id
                
                # Connect to splitter if exists
                if splitter:
                    splitter_id = splitter["name"]
                    self._draw_connector(c, splitter_id, splitter)
                    if last_node:
                        c.edge(last_node, splitter_id)
                    last_node = splitter_id
                elif not parallel_branches and outlet_branch and outlet_branch != inlet_branch:
                    # No splitter, connect directly to outlet branch
                    if outlet_branch["components"]:
                        first_outlet_comp = f"{outlet_branch['name']}_0"
                        c.edge(last_node, first_outlet_comp)
                elif not parallel_branches and not outlet_branch:
                    # No splitter and no separate outlet branch, connect to outlet
                    c.edge(last_node, f"{side}_outlet")
            
            # Draw parallel branches
            parallel_last_nodes = []
            for branch in parallel_branches:
                if not branch["components"]:
                    continue
                    
                # Connect from splitter to first component of this branch
                first_comp_id = f"{branch['name']}_0"
                if splitter:
                    c.edge(splitter["name"], first_comp_id)
                
                # Draw all components in this branch
                last_node = None
                for comp_idx, comp in enumerate(branch["components"]):
                    comp_id = f"{branch['name']}_{comp_idx}"
                    self._draw_component(c, comp_id, comp)
                    
                    if last_node:
                        c.edge(last_node, comp_id)
                    last_node = comp_id
                
                parallel_last_nodes.append(last_node)
            
            # Draw mixer if it exists
            mixer_node = None
            if mixer and parallel_last_nodes:
                mixer_id = mixer["name"]
                self._draw_connector(c, mixer_id, mixer)
                mixer_node = mixer_id
                
                # Connect all parallel branches to mixer
                for last_node in parallel_last_nodes:
                    if last_node:
                        c.edge(last_node, mixer_id)
            
            # Draw outlet branch if it exists
            if outlet_branch and outlet_branch != inlet_branch:
                first_outlet_node = mixer_node if mixer_node else (parallel_last_nodes[0] if parallel_last_nodes else f"{side}_inlet")
                
                for comp_idx, comp in enumerate(outlet_branch["components"]):
                    comp_id = f"{outlet_branch['name']}_{comp_idx}"
                    self._draw_component(c, comp_id, comp)
                    
                    if comp_idx == 0 and first_outlet_node:
                        c.edge(first_outlet_node, comp_id)
                    elif comp_idx > 0:
                        prev_comp_id = f"{outlet_branch['name']}_{comp_idx-1}"
                        c.edge(prev_comp_id, comp_id)
                
                # Connect last component of outlet branch to side outlet
                if outlet_branch["components"]:
                    last_outlet_comp = f"{outlet_branch['name']}_{len(outlet_branch['components'])-1}"
                    c.edge(last_outlet_comp, f"{side}_outlet")
            elif mixer_node:
                # Connect mixer directly to outlet if no outlet branch
                c.edge(mixer_node, f"{side}_outlet")
            elif parallel_last_nodes:
                # Connect parallel branches directly to outlet if no mixer or outlet branch
                for last_node in parallel_last_nodes:
                    if last_node:
                        c.edge(last_node, f"{side}_outlet")

    def _build_air_loop_side(self, dot: Digraph, side_data: dict, *, side: str):
        """Create a subgraph cluster specifically for air loop systems."""
        with dot.subgraph(name=f"cluster_{side.lower()}") as c:
            c.attr(label=f"{side} Side", labelloc="t", fontsize="14")

            # Pseudo-nodes to anchor cross-loop arrows
            c.node(f"{side}_inlet", "", shape="point", width="0.01")
            c.node(f"{side}_outlet", "", shape="point", width="0.01")

            if side == "Supply":
                # For supply side, show any supply equipment
                components = side_data.get("components", [])
                if components:
                    last_node = f"{side}_inlet"
                    for comp_idx, comp in enumerate(components):
                        comp_id = f"supply_comp_{comp_idx}"
                        self._draw_component(c, comp_id, comp)
                        c.edge(last_node, comp_id)
                        last_node = comp_id
                    c.edge(last_node, f"{side}_outlet")
                else:
                    # Simple connection if no components
                    c.edge(f"{side}_inlet", f"{side}_outlet")

            elif side == "Demand":
                # For demand side, show zone splitters, equipment, and mixers
                zone_splitters = side_data.get("zone_splitters", [])
                zone_mixers = side_data.get("zone_mixers", [])
                zone_equipment = side_data.get("zone_equipment", [])
                return_plenums = side_data.get("return_plenums", [])
                
                last_node = f"{side}_inlet"
                
                # Draw zone splitters
                if zone_splitters:
                    for idx, splitter in enumerate(zone_splitters):
                        splitter_id = f"zone_splitter_{idx}"
                        self._draw_air_component(c, splitter_id, splitter)
                        c.edge(last_node, splitter_id)
                        last_node = splitter_id
                        
                        # Connect splitter to zone equipment
                        if zone_equipment:
                            for eq_idx, equipment in enumerate(zone_equipment):
                                eq_id = f"zone_equipment_{eq_idx}"
                                self._draw_air_component(c, eq_id, equipment)
                                c.edge(splitter_id, eq_id)
                
                # Draw return plenums if present
                plenum_node = None
                if return_plenums:
                    for idx, plenum in enumerate(return_plenums):
                        plenum_id = f"return_plenum_{idx}"
                        self._draw_air_component(c, plenum_id, plenum)
                        plenum_node = plenum_id
                        
                        # Connect zone equipment to plenum (simplified)
                        if zone_equipment:
                            for eq_idx in range(len(zone_equipment)):
                                eq_id = f"zone_equipment_{eq_idx}"
                                c.edge(eq_id, plenum_id)
                
                # Draw zone mixers
                if zone_mixers:
                    for idx, mixer in enumerate(zone_mixers):
                        mixer_id = f"zone_mixer_{idx}"
                        self._draw_air_component(c, mixer_id, mixer)
                        
                        # Connect from plenum or equipment to mixer
                        if plenum_node:
                            c.edge(plenum_node, mixer_id)
                        elif zone_equipment:
                            # Connect equipment directly to mixer if no plenum
                            for eq_idx in range(len(zone_equipment)):
                                eq_id = f"zone_equipment_{eq_idx}"
                                c.edge(eq_id, mixer_id)
                        else:
                            c.edge(last_node, mixer_id)
                        
                        # Connect mixer to outlet
                        c.edge(mixer_id, f"{side}_outlet")
                else:
                    # No mixers, connect directly to outlet
                    if plenum_node:
                        c.edge(plenum_node, f"{side}_outlet")
                    elif zone_equipment:
                        # Connect last equipment to outlet
                        eq_id = f"zone_equipment_{len(zone_equipment)-1}"
                        c.edge(eq_id, f"{side}_outlet")
                    else:
                        c.edge(last_node, f"{side}_outlet")

    def _draw_component(self, c: Digraph, comp_id: str, comp: dict):
        """Draw a single component node."""
        label = self._abbrev_type(comp["type"])
        color = self.COMPONENT_COLORS.get(comp["type"], self.COMPONENT_COLORS["default"])
        c.node(comp_id, label, fillcolor=color, **self.NODE_STYLE)
    
    def _draw_connector(self, c: Digraph, conn_id: str, connector: dict):
        """Draw a connector (splitter/mixer) node."""
        label = self._abbrev_type(connector["type"])
        color = self.COMPONENT_COLORS[connector["type"]]
        c.node(conn_id, label, fillcolor=color, **self.CONNECTOR_STYLE)

    def _draw_air_component(self, c: Digraph, comp_id: str, comp: dict):
        """Draw an air loop component node."""
        label = self._abbrev_type(comp["type"])
        color = self.COMPONENT_COLORS.get(comp["type"], self.COMPONENT_COLORS["default"])
        c.node(comp_id, label, fillcolor=color, **self.NODE_STYLE)

    def _add_compact_legend(self, dot: Digraph, used_types: set):
        """Create a compact horizontal legend positioned at bottom."""
        
        # First, determine which legend nodes we need to create
        legend_nodes = []
        legend_data = []
        
        for typ, col in self.COMPONENT_COLORS.items():
            if "Connector" in typ or typ == "default":
                continue
            if typ in used_types:
                short = typ.split(":")[0] if ":" in typ else typ
                node_id = f"leg_{short}"
                legend_nodes.append(node_id)
                legend_data.append((node_id, short, col))
        
        # Only create the legend cluster if we have nodes to add
        if not legend_data:
            return
            
        with dot.subgraph(name="cluster_legend") as leg:
            # Make legend more compact
            leg.attr(
                label="Component Types", 
                fontsize="12", 
                labelloc="t",
                style="rounded",
                color="lightgray",
                penwidth="1",
                margin="10",
                rank="min"  # Position at top instead of sink
            )
            
            # Create a hidden node to control legend positioning
            leg.node("legend_anchor", "", shape="point", width="0", height="0", style="invis")
            
            # Create compact legend nodes with smaller styling
            for node_id, short, col in legend_data:
                # Use smaller, more compact style for legend
                leg.node(
                    node_id, 
                    short, 
                    fillcolor=col, 
                    shape="box", 
                    style="rounded,filled", 
                    fontname="Helvetica", 
                    fontsize="10",
                    width="0.8",
                    height="0.4",
                    margin="0.05"
                )
            
            # Create invisible edges to force horizontal layout
            for i in range(len(legend_nodes) - 1):
                leg.edge(legend_nodes[i], legend_nodes[i + 1], style="invis")
            
            # Set same rank for all legend nodes to make them horizontal
            if legend_nodes:
                leg.attr(rank="same")
                # Use a subgraph to group legend nodes horizontally
                with leg.subgraph() as legend_row:
                    legend_row.attr(rank="same")
                    for node in legend_nodes:
                        legend_row.node(node)

    @staticmethod
    def _abbrev_type(t: str) -> str:
        aliases = {
            "Pump:VariableSpeed": "Pump\n(VSD)",
            "Pump:ConstantSpeed": "Pump\n(CSD)",
            "Chiller:Electric": "Elec\nChiller",
            "Coil:Cooling:Water": "Cooling\nCoil",
            "Coil:Heating:Water": "Heating\nCoil",
            "Pipe:Adiabatic": "Pipe",
            "Connector:Splitter": "Splitter",
            "Connector:Mixer": "Mixer",
            # Air loop abbreviations
            "AirLoopHVAC:ZoneSplitter": "Zone\nSplitter",
            "AirLoopHVAC:ZoneMixer": "Zone\nMixer",
            "AirLoopHVAC:ReturnPlenum": "Return\nPlenum",
            "AirTerminal:SingleDuct:VAV:Reheat": "VAV\nReheat",
            "AirTerminal:SingleDuct:ConstantVolume:NoReheat": "CAV\nTerminal",
            "AirTerminal:SingleDuct:VAV:NoReheat": "VAV\nTerminal",
            "Fan:VariableVolume": "VAV\nFan",
            "Fan:ConstantVolume": "CAV\nFan",
            "Coil:Cooling:DX:SingleSpeed": "DX\nCooling",
            "Coil:Heating:Electric": "Electric\nHeating",
            "Coil:Heating:Gas": "Gas\nHeating",
        }
        return aliases.get(t, t.replace(":", "\n"))

    @staticmethod
    def _count_components(topology: dict) -> int:
        cnt = 0
        for side in ("supply_side", "demand_side"):
            # Count plant/condenser loop components
            for br in topology[side].get("branches", []):
                cnt += len(br.get("components", []))
            
            # Count air loop components
            cnt += len(topology[side].get("zone_splitters", []))
            cnt += len(topology[side].get("zone_mixers", []))
            cnt += len(topology[side].get("zone_equipment", []))
            cnt += len(topology[side].get("return_plenums", []))
            cnt += len(topology[side].get("components", []))
        return cnt
