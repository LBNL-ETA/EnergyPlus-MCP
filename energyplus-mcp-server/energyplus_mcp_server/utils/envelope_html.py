"""
Utilities for generating interactive HTML visualizations of building envelope data.
"""

import json
from typing import Dict, Any


def transform_envelope_data_for_viz(envelope_data: Dict[str, Any]) -> Dict[str, Any]:
    """Transform comprehensive envelope data into visualization-friendly format"""
    
    # Group surfaces by zone
    zones = {}
    for surface in envelope_data["surfaces"]:
        zone_name = surface["zone_name"]
        if zone_name not in zones:
            zones[zone_name] = []
        zones[zone_name].append({
            "name": surface["name"],
            "type": surface["surface_type"],
            "construction": surface["construction_name"],
            "boundary": surface["outside_boundary_condition"]
        })
    
    # Create zones list
    zones_list = [
        {"name": zone_name, "surfaces": surfaces}
        for zone_name, surfaces in zones.items()
    ]
    
    # Create constructions dict with full details
    constructions_dict = {}
    for construction in envelope_data["constructions"]:
        name = construction["name"]
        # Get material details for each layer
        materials_list = []
        for layer in construction["layers"]:
            material_name = layer["material"]
            # Find material in materials list
            material_data = next(
                (m for m in envelope_data["materials"] if m["name"] == material_name),
                None
            )
            if material_data:
                mat_info = {"name": material_name}
                # Add relevant properties based on material type
                if "Thickness" in material_data:
                    mat_info["thickness"] = material_data["Thickness"]
                if "Conductivity" in material_data:
                    mat_info["conductivity"] = material_data["Conductivity"]
                if "Thermal_Resistance" in material_data:
                    mat_info["resistance"] = material_data["Thermal_Resistance"]
                if "type" in material_data:
                    mat_info["type"] = material_data["type"]
                materials_list.append(mat_info)
        
        # Count surfaces using this construction
        surface_count = sum(
            1 for s in envelope_data["surfaces"] 
            if s["construction_name"] == name
        )
        
        constructions_dict[name] = {
            "layers": construction["layer_count"],
            "surfaces": surface_count,
            "materials": materials_list
        }
    
    # Create orphaned constructions list
    orphaned_constructions = [
        {
            "name": construction["name"],
            "layers": construction["layer_count"],
            "note": f"{construction['layer_count']} layer construction" if construction["layer_count"] > 1 else "Single layer construction"
        }
        for construction in envelope_data["constructions"]
        if construction["name"] in envelope_data["relationships"]["orphaned_constructions"]
    ]
    
    # Create orphaned materials list
    orphaned_materials = [
        {
            "name": material["name"],
            "type": material.get("type", "Unknown"),
            "thickness": material.get("Thickness"),
            "gas": material.get("Gas_Type")
        }
        for material in envelope_data["materials"]
        if material["name"] in envelope_data["relationships"]["orphaned_materials"]
    ]
    
    return {
        "summary": envelope_data["summary"],
        "zones": zones_list,
        "constructions": constructions_dict,
        "orphanedConstructions": orphaned_constructions,
        "orphanedMaterials": orphaned_materials
    }


def create_envelope_html_viewer(building_name: str, envelope_data: Dict[str, Any]) -> str:
    """
    Create an interactive HTML visualization of the building envelope.
    
    Args:
        building_name: Name of the building
        envelope_data: Transformed envelope data (from transform_envelope_data_for_viz)
        
    Returns:
        Complete HTML string with embedded React-based viewer
    """
    
    # Convert data to JSON string for embedding
    data_json = json.dumps(envelope_data, indent=8)
    
    # Check if there are critical issues
    has_zero_layer_constructions = any(
        c["layers"] == 0 for c in envelope_data.get("constructions", {}).values()
    )
    
    warning_message = ""
    if has_zero_layer_constructions:
        warning_message = """
                    <div style="padding: 15px; background: #fef3c7; borderRadius: 8px; marginBottom: 20px; border: 2px solid #f59e0b;">
                        <div style="fontWeight: 600; color: #92400e; marginBottom: 8px; fontSize: 16px;">
                            ⚠️ All constructions have ZERO layers!
                        </div>
                        <div style="fontSize: 13px; color: #78350f;">
                            This visualization reveals a critical issue - all constructions have zero layers, meaning no materials are actually assigned to the building envelope. The {material_count} defined materials are all orphaned and not contributing to thermal performance calculations.
                        </div>
                    </div>
""".format(material_count=envelope_data["summary"]["total_materials"])
    
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{building_name} Envelope Explorer</title>
    <script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
    <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
    <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
    <style>
        body {{
            margin: 0;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        #root {{
            max-width: 1400px;
            margin: 0 auto;
        }}
    </style>
</head>
<body>
    <div id="root"></div>
    <script type="text/babel">
        const {{ useState }} = React;

        const envelopeData = {data_json};

        function TreeNode({{ label, icon, count, children, defaultExpanded = false, color = "#4a5568", warning = false }}) {{
            const [isExpanded, setIsExpanded] = useState(defaultExpanded);

            return (
                <div style={{{{ marginLeft: '20px', marginTop: '8px' }}}}>
                    <div
                        onClick={{() => children && setIsExpanded(!isExpanded)}}
                        style={{{{
                            display: 'flex',
                            alignItems: 'center',
                            padding: '8px 12px',
                            background: warning ? '#fef3c7' : 'white',
                            borderRadius: '6px',
                            cursor: children ? 'pointer' : 'default',
                            transition: 'all 0.2s',
                            border: warning ? '2px solid #f59e0b' : '1px solid #e2e8f0',
                            marginBottom: '4px'
                        }}}}
                        onMouseEnter={{(e) => children && (e.currentTarget.style.background = warning ? '#fde68a' : '#f7fafc')}}
                        onMouseLeave={{(e) => (e.currentTarget.style.background = warning ? '#fef3c7' : 'white')}}
                    >
                        {{children && (
                            <span style={{{{ marginRight: '8px', fontSize: '12px', color: '#718096' }}}}>
                                {{isExpanded ? '▼' : '▶'}}
                            </span>
                        )}}
                        <span style={{{{ marginRight: '8px' }}}}{{icon}}</span>
                        <span style={{{{ fontWeight: '500', color: color, flex: 1 }}}}{{label}}</span>
                        {{count !== undefined && (
                            <span style={{{{
                                background: warning ? '#f59e0b' : '#e2e8f0',
                                color: warning ? 'white' : '#4a5568',
                                padding: '2px 8px',
                                borderRadius: '12px',
                                fontSize: '12px',
                                fontWeight: '600'
                            }}}}>
                                {{count}}
                            </span>
                        )}}
                    </div>
                    {{isExpanded && children && (
                        <div style={{{{ marginLeft: '12px' }}}}>
                            {{children}}
                        </div>
                    )}}
                </div>
            );
        }}

        function App() {{
            const [view, setView] = useState('zones');

            const getSurfaceIcon = (type, boundary) => {{
                if (type === 'Floor') return '🟫';
                if (type === 'Roof') return '🟦';
                if (boundary === 'Outdoors') return '🧱';
                return '🚪';
            }};

            return (
                <div style={{{{
                    background: 'white',
                    borderRadius: '12px',
                    padding: '30px',
                    boxShadow: '0 20px 60px rgba(0,0,0,0.3)'
                }}}}>
                    <h1 style={{{{ margin: '0 0 10px 0', color: '#1a202c', fontSize: '28px' }}}}>
                        🏗️ {building_name} Envelope Explorer
                    </h1>
                    <p style={{{{ margin: '0 0 20px 0', color: '#718096' }}}}>
                        Interactive visualization of building envelope relationships
                    </p>

                    {{/* Summary Stats */}}
                    <div style={{{{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
                        gap: '15px',
                        marginBottom: '25px',
                        padding: '20px',
                        background: '#f7fafc',
                        borderRadius: '8px'
                    }}}}>
                        <div>
                            <div style={{{{ fontSize: '24px', fontWeight: 'bold', color: '#667eea' }}}}>
                                {{envelopeData.summary.total_surfaces}}
                            </div>
                            <div style={{{{ fontSize: '12px', color: '#718096' }}}}>Total Surfaces</div>
                        </div>
                        <div>
                            <div style={{{{ fontSize: '24px', fontWeight: 'bold', color: '#48bb78' }}}}>
                                {{envelopeData.summary.used_constructions}}
                            </div>
                            <div style={{{{ fontSize: '12px', color: '#718096' }}}}>Used Constructions</div>
                        </div>
                        <div>
                            <div style={{{{ fontSize: '24px', fontWeight: 'bold', color: '#ed8936' }}}}>
                                {{envelopeData.summary.orphaned_materials}}
                            </div>
                            <div style={{{{ fontSize: '12px', color: '#718096' }}}}>Orphaned Materials</div>
                        </div>
                    </div>

                    {warning_message}

                    {{/* View Toggle */}}
                    <div style={{{{ marginBottom: '20px', display: 'flex', gap: '10px', flexWrap: 'wrap' }}}}>
                        <button
                            onClick={{() => setView('zones')}}
                            style={{{{
                                padding: '10px 20px',
                                background: view === 'zones' ? '#667eea' : 'white',
                                color: view === 'zones' ? 'white' : '#4a5568',
                                border: '2px solid #667eea',
                                borderRadius: '6px',
                                cursor: 'pointer',
                                fontWeight: '600',
                                transition: 'all 0.2s'
                            }}}}
                        >
                            🏢 By Zone
                        </button>
                        <button
                            onClick={{() => setView('constructions')}}
                            style={{{{
                                padding: '10px 20px',
                                background: view === 'constructions' ? '#667eea' : 'white',
                                color: view === 'constructions' ? 'white' : '#4a5568',
                                border: '2px solid #667eea',
                                borderRadius: '6px',
                                cursor: 'pointer',
                                fontWeight: '600',
                                transition: 'all 0.2s'
                            }}}}
                        >
                            📐 By Construction
                        </button>
                        <button
                            onClick={{() => setView('orphaned')}}
                            style={{{{
                                padding: '10px 20px',
                                background: view === 'orphaned' ? '#667eea' : 'white',
                                color: view === 'orphaned' ? 'white' : '#4a5568',
                                border: '2px solid #667eea',
                                borderRadius: '6px',
                                cursor: 'pointer',
                                fontWeight: '600',
                                transition: 'all 0.2s'
                            }}}}
                        >
                            🗑️ Orphaned Items
                        </button>
                    </div>

                    {{/* Content */}}
                    <div style={{{{ marginTop: '20px' }}}}>
                        {{view === 'zones' && (
                            <div>
                                {{envelopeData.zones.map(zone => (
                                    <TreeNode
                                        key={{zone.name}}
                                        label={{zone.name}}
                                        icon="🏠"
                                        count={{zone.surfaces.length}}
                                        defaultExpanded={{false}}
                                        color="#2d3748"
                                    >
                                        {{/* Group by surface type */}}
                                        {{['Floor', 'Roof', 'Wall'].map(type => {{
                                            const surfaces = zone.surfaces.filter(s =>
                                                type === 'Wall' ? s.type === 'Wall' : s.type === type
                                            );
                                            if (surfaces.length === 0) return null;

                                            return (
                                                <TreeNode
                                                    key={{type}}
                                                    label={{`${{type}}s`}}
                                                    icon={{type === 'Floor' ? '🟫' : type === 'Roof' ? '🟦' : '🧱'}}
                                                    count={{surfaces.length}}
                                                    color="#4a5568"
                                                >
                                                    {{surfaces.map((surface, idx) => (
                                                        <TreeNode
                                                            key={{idx}}
                                                            label={{surface.name}}
                                                            icon={{getSurfaceIcon(surface.type, surface.boundary)}}
                                                            color="#718096"
                                                        >
                                                            <TreeNode
                                                                label={{surface.construction}}
                                                                icon="📋"
                                                                color="#667eea"
                                                                count={{`${{envelopeData.constructions[surface.construction]?.layers || 0}} layers`}}
                                                                warning={{envelopeData.constructions[surface.construction]?.layers === 0}}
                                                            >
                                                                {{envelopeData.constructions[surface.construction]?.materials.map((mat, midx) => (
                                                                    <div key={{midx}} style={{{{
                                                                        padding: '8px 12px',
                                                                        background: '#f0fff4',
                                                                        borderRadius: '6px',
                                                                        marginTop: '6px',
                                                                        marginLeft: '20px',
                                                                        fontSize: '12px',
                                                                        border: '1px solid #9ae6b4'
                                                                    }}}}>
                                                                        <div style={{{{ fontWeight: '600', color: '#22543d', marginBottom: '4px' }}}}>
                                                                            Layer {{midx + 1}}: {{mat.name}}
                                                                        </div>
                                                                        {{mat.thickness && (
                                                                            <div style={{{{ color: '#276749' }}}}>
                                                                                Thickness: {{(mat.thickness * 1000).toFixed(1)}} mm
                                                                            </div>
                                                                        )}}
                                                                        {{mat.conductivity && (
                                                                            <div style={{{{ color: '#276749' }}}}>
                                                                                k: {{mat.conductivity}} W/m·K
                                                                            </div>
                                                                        )}}
                                                                        {{mat.resistance && (
                                                                            <div style={{{{ color: '#276749' }}}}>
                                                                                R-value: {{mat.resistance}} m²·K/W
                                                                            </div>
                                                                        )}}
                                                                    </div>
                                                                ))}}
                                                            </TreeNode>
                                                        </TreeNode>
                                                    ))}}
                                                </TreeNode>
                                            );
                                        }})}}
                                    </TreeNode>
                                ))}}
                            </div>
                        )}}

                        {{view === 'constructions' && (
                            <div>
                                {{Object.entries(envelopeData.constructions).map(([name, data]) => (
                                    <TreeNode
                                        key={{name}}
                                        label={{name}}
                                        icon="📐"
                                        count={{`${{data.surfaces}} surfaces`}}
                                        defaultExpanded={{false}}
                                        color="#2d3748"
                                        warning={{data.layers === 0}}
                                    >
                                        <div style={{{{
                                            padding: '12px',
                                            background: '#f7fafc',
                                            borderRadius: '6px',
                                            marginTop: '8px',
                                            marginLeft: '20px',
                                            border: '1px solid #e2e8f0'
                                        }}}}>
                                            <div style={{{{ fontWeight: '600', color: '#2d3748', marginBottom: '8px' }}}}>
                                                📊 Construction Details
                                            </div>
                                            <div style={{{{ fontSize: '13px', color: '#4a5568', marginBottom: '4px' }}}}>
                                                <strong>Layers:</strong> {{data.layers}}
                                            </div>
                                            <div style={{{{ fontSize: '13px', color: '#4a5568', marginBottom: '10px' }}}}>
                                                <strong>Used by:</strong> {{data.surfaces}} surface(s)
                                            </div>
                                            {{data.layers === 0 && (
                                                <div style={{{{
                                                    padding: '8px',
                                                    background: '#fef3c7',
                                                    borderRadius: '4px',
                                                    marginBottom: '6px',
                                                    border: '1px solid #f59e0b',
                                                    fontSize: '12px',
                                                    color: '#92400e'
                                                }}}}>
                                                    ⚠️ No material layers defined
                                                </div>
                                            )}}
                                            {{data.materials.map((mat, idx) => (
                                                <div key={{idx}} style={{{{
                                                    padding: '8px',
                                                    background: '#f0fff4',
                                                    borderRadius: '4px',
                                                    marginBottom: '6px',
                                                    border: '1px solid #9ae6b4'
                                                }}}}>
                                                    <div style={{{{ fontWeight: '600', color: '#22543d', fontSize: '12px', marginBottom: '2px' }}}}>
                                                        Layer {{idx + 1}}: {{mat.name}}
                                                    </div>
                                                    <div style={{{{ fontSize: '11px', color: '#276749' }}}}>
                                                        {{mat.thickness && `${{(mat.thickness * 1000).toFixed(1)}} mm`}}
                                                        {{mat.conductivity && ` | k: ${{mat.conductivity}} W/m·K`}}
                                                        {{mat.resistance && ` | R: ${{mat.resistance}} m²·K/W`}}
                                                    </div>
                                                </div>
                                            ))}}
                                        </div>
                                    </TreeNode>
                                ))}}
                            </div>
                        )}}

                        {{view === 'orphaned' && (
                            <div>
                                {{/* Orphaned Constructions */}}
                                <div style={{{{
                                    padding: '15px',
                                    background: envelopeData.orphanedConstructions.length > 0 ? '#fef3c7' : '#f0fdf4',
                                    borderRadius: '8px',
                                    marginBottom: '20px',
                                    border: envelopeData.orphanedConstructions.length > 0 ? '2px solid #f59e0b' : '2px solid #48bb78'
                                }}}}>
                                    <div style={{{{ fontWeight: '600', color: envelopeData.orphanedConstructions.length > 0 ? '#92400e' : '#065f46', marginBottom: '8px', fontSize: '16px' }}}}>
                                        {{envelopeData.orphanedConstructions.length > 0 ? '⚠️' : '✅'}} {{envelopeData.orphanedConstructions.length}} Unused Constructions
                                    </div>
                                    <div style={{{{ fontSize: '13px', color: envelopeData.orphanedConstructions.length > 0 ? '#78350f' : '#065f46', marginBottom: '12px' }}}}>
                                        {{envelopeData.orphanedConstructions.length > 0 
                                            ? 'These constructions are defined but not assigned to any surface.'
                                            : 'Great! All constructions are properly assigned to surfaces.'}}
                                    </div>
                                </div>

                                {{envelopeData.orphanedConstructions.length > 0 && (
                                    <TreeNode
                                        label="Orphaned Constructions"
                                        icon="📐"
                                        count={{envelopeData.orphanedConstructions.length}}
                                        defaultExpanded={{true}}
                                        color="#2d3748"
                                        warning={{true}}
                                    >
                                        {{envelopeData.orphanedConstructions.map((cons, idx) => (
                                            <div key={{idx}} style={{{{
                                                padding: '10px 12px',
                                                background: 'white',
                                                borderRadius: '6px',
                                                marginTop: '6px',
                                                marginLeft: '20px',
                                                border: '1px solid #fcd34d',
                                                display: 'flex',
                                                justifyContent: 'space-between',
                                                alignItems: 'center'
                                            }}}}>
                                                <div>
                                                    <div style={{{{ fontWeight: '600', color: '#4a5568', fontSize: '13px' }}}}>
                                                        {{cons.name}}
                                                    </div>
                                                    {{cons.note && (
                                                        <div style={{{{ fontSize: '11px', color: '#718096', marginTop: '2px' }}}}>
                                                            {{cons.note}}
                                                        </div>
                                                    )}}
                                                </div>
                                                <div style={{{{
                                                    background: '#fef3c7',
                                                    padding: '4px 8px',
                                                    borderRadius: '4px',
                                                    fontSize: '11px',
                                                    fontWeight: '600',
                                                    color: '#92400e'
                                                }}}}>
                                                    {{cons.layers}} layers
                                                </div>
                                            </div>
                                        ))}}
                                    </TreeNode>
                                )}}

                                {{/* Orphaned Materials */}}
                                <div style={{{{ marginTop: '30px' }}}}>
                                    <div style={{{{
                                        padding: '15px',
                                        background: envelopeData.orphanedMaterials.length > 0 ? '#fef3c7' : '#f0fdf4',
                                        borderRadius: '8px',
                                        marginBottom: '20px',
                                        border: envelopeData.orphanedMaterials.length > 0 ? '2px solid #f59e0b' : '2px solid #48bb78'
                                    }}}}>
                                        <div style={{{{ fontWeight: '600', color: envelopeData.orphanedMaterials.length > 0 ? '#92400e' : '#065f46', marginBottom: '8px', fontSize: '16px' }}}}>
                                            {{envelopeData.orphanedMaterials.length > 0 ? '⚠️' : '✅'}} {{envelopeData.orphanedMaterials.length}} Orphaned Material(s)
                                        </div>
                                        <div style={{{{ fontSize: '13px', color: envelopeData.orphanedMaterials.length > 0 ? '#78350f' : '#065f46' }}}}>
                                            {{envelopeData.orphanedMaterials.length > 0 
                                                ? 'These materials exist in the model but are not referenced by any construction.'
                                                : 'Great! All materials are properly assigned to constructions.'}}
                                        </div>
                                    </div>

                                    {{envelopeData.orphanedMaterials.length > 0 && (
                                        <TreeNode
                                            label="Orphaned Materials"
                                            icon="🧱"
                                            count={{envelopeData.orphanedMaterials.length}}
                                            defaultExpanded={{true}}
                                            color="#2d3748"
                                            warning={{true}}
                                        >
                                            {{envelopeData.orphanedMaterials.map((mat, idx) => (
                                                <div key={{idx}} style={{{{
                                                    padding: '10px 12px',
                                                    background: 'white',
                                                    borderRadius: '6px',
                                                    marginTop: '6px',
                                                    marginLeft: '20px',
                                                    border: '1px solid #fcd34d'
                                                }}}}>
                                                    <div style={{{{ fontWeight: '600', color: '#4a5568', marginBottom: '4px', fontSize: '13px' }}}}>
                                                        {{mat.name}}
                                                    </div>
                                                    <div style={{{{ fontSize: '11px', color: '#718096' }}}}>
                                                        Type: {{mat.type}}
                                                    </div>
                                                    {{mat.thickness && (
                                                        <div style={{{{ fontSize: '11px', color: '#718096' }}}}>
                                                            Thickness: {{(mat.thickness * 1000).toFixed(1)}} mm
                                                        </div>
                                                    )}}
                                                    {{mat.gas && (
                                                        <div style={{{{ fontSize: '11px', color: '#718096' }}}}>
                                                            Gas Type: {{mat.gas}}
                                                        </div>
                                                    )}}
                                                </div>
                                            ))}}
                                        </TreeNode>
                                    )}}
                                </div>
                            </div>
                        )}}
                    </div>

                    {{/* Footer */}}
                    <div style={{{{
                        marginTop: '30px',
                        padding: '15px',
                        background: '#f7fafc',
                        borderRadius: '8px',
                        fontSize: '13px',
                        color: '#718096',
                        borderLeft: '4px solid #667eea'
                    }}}}>
                        <strong>Note:</strong> This visualization reveals the hierarchical relationships in the building envelope.
                        Navigate by zone to see surfaces → constructions → materials, or by construction to understand material assemblies.
                    </div>
                </div>
            );
        }}

        ReactDOM.render(<App />, document.getElementById('root'));
    </script>
</body>
</html>"""
    
    return html_content

