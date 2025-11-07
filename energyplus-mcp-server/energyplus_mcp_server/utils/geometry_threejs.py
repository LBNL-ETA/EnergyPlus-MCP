"""
Three.js geometry conversion utilities for building visualization.

This module converts EnergyPlus geometry data into three.js-compatible format
for 3D visualization in web browsers.
"""

import json
import math
from typing import Any, Dict, List, Optional, Tuple


# Color scheme for different surface types
SURFACE_COLORS = {
    "WALL": {"color": 0xD2B48C, "opacity": 0.9},  # Tan
    "FLOOR": {"color": 0x8B7355, "opacity": 1.0},  # Brown
    "ROOF": {"color": 0x8B4513, "opacity": 0.9},  # Saddle brown
    "CEILING": {"color": 0xF5F5DC, "opacity": 0.9},  # Beige
    "WINDOW": {"color": 0x87CEEB, "opacity": 0.5},  # Sky blue (transparent)
    "DOOR": {"color": 0x8B4513, "opacity": 0.9},  # Brown
    "GLASSDOOR": {"color": 0x87CEEB, "opacity": 0.5},  # Sky blue (transparent)
    "SHADING": {"color": 0x696969, "opacity": 0.7},  # Dim gray
}


def triangulate_polygon(vertices: List[List[float]]) -> List[List[int]]:
    """
    Simple ear-clipping triangulation for convex/simple polygons.
    
    Args:
        vertices: List of [x, y, z] coordinates
        
    Returns:
        List of triangles, each as [i1, i2, i3] indices
    """
    n = len(vertices)
    if n < 3:
        return []
    
    if n == 3:
        return [[0, 1, 2]]
    
    # Simple fan triangulation (works for convex polygons)
    # For more complex polygons, a proper ear-clipping algorithm would be needed
    triangles = []
    for i in range(1, n - 1):
        triangles.append([0, i, i + 1])
    
    return triangles


def calculate_surface_center(vertices: List[List[float]]) -> List[float]:
    """Calculate the center point of a surface."""
    if not vertices:
        return [0, 0, 0]
    
    x = sum(v[0] for v in vertices) / len(vertices)
    y = sum(v[1] for v in vertices) / len(vertices)
    z = sum(v[2] for v in vertices) / len(vertices)
    
    return [x, y, z]


def categorize_surfaces(geometry_data: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Categorize surfaces into floors, walls, roofs, ceilings, and partitions.
    
    Args:
        geometry_data: Geometry data from extract_building_geometry
        
    Returns:
        Dictionary with categorized surfaces
    """
    categorized = {
        "floors": [],
        "walls": [],
        "roofs": [],
        "ceilings": [],
        "partitions": [],
        "windows": [],
        "doors": [],
        "shading": []
    }
    
    for surface in geometry_data.get("surfaces", []):
        surface_type = surface.get("surface_type", "").upper()
        outside_bc = surface.get("outside_boundary_condition", "").upper()
        
        # Partition = interior surface (not to outdoors/ground)
        is_partition = outside_bc not in ("OUTDOORS", "GROUND", "")
        
        if surface_type == "FLOOR":
            categorized["floors"].append(surface)
        elif surface_type == "ROOF":
            categorized["roofs"].append(surface)
        elif surface_type == "CEILING":
            categorized["ceilings"].append(surface)
        elif surface_type == "WALL":
            if is_partition or outside_bc == "SURFACE":
                categorized["partitions"].append(surface)
            else:
                categorized["walls"].append(surface)
        else:
            # Default classification by tilt
            tilt = surface.get("tilt", 0)
            if tilt < 45:  # Mostly horizontal, facing up
                categorized["roofs"].append(surface)
            elif tilt > 135:  # Mostly horizontal, facing down
                categorized["floors"].append(surface)
            elif is_partition:
                categorized["partitions"].append(surface)
            else:
                categorized["walls"].append(surface)
    
    # Categorize subsurfaces
    for subsurface in geometry_data.get("subsurfaces", []):
        surface_type = subsurface.get("surface_type", "").upper()
        if "WINDOW" in surface_type or "GLASS" in surface_type:
            categorized["windows"].append(subsurface)
        else:  # DOOR
            categorized["doors"].append(subsurface)
    
    # Add shading
    categorized["shading"] = geometry_data.get("shading_surfaces", [])
    
    return categorized


def create_threejs_geometry(
    geometry_data: Dict[str, Any],
    include_subsurfaces: bool = True,
    include_shading: bool = True,
    wireframe_mode: bool = False
) -> Dict[str, Any]:
    """
    Convert EnergyPlus geometry to three.js-compatible format.
    
    Args:
        geometry_data: Geometry data from extract_building_geometry
        include_subsurfaces: Whether to include windows/doors
        include_shading: Whether to include shading surfaces
        wireframe_mode: If True, only output edges for wireframe view
        
    Returns:
        Dictionary containing three.js scene data
    """
    threejs_scene = {
        "metadata": {
            "version": "1.0",
            "type": "energyplus_building",
            "generator": "energyplus-mcp-server",
            "building_name": geometry_data.get("building", {}).get("name", "Unknown"),
            "north_axis": geometry_data.get("building", {}).get("north_axis", 0.0)
        },
        "objects": [],
        "materials": _create_materials(),
        "lights": _create_default_lights(),
        "camera": _calculate_camera_position(geometry_data)
    }
    
    # Convert surfaces
    for surface in geometry_data.get("surfaces", []):
        obj = _create_surface_object(surface, "surface")
        if obj:
            threejs_scene["objects"].append(obj)
    
    # Convert subsurfaces (windows, doors)
    if include_subsurfaces:
        for subsurface in geometry_data.get("subsurfaces", []):
            obj = _create_surface_object(subsurface, "subsurface")
            if obj:
                threejs_scene["objects"].append(obj)
    
    # Convert shading surfaces
    if include_shading:
        for shading in geometry_data.get("shading_surfaces", []):
            obj = _create_shading_object(shading)
            if obj:
                threejs_scene["objects"].append(obj)
    
    return threejs_scene


def _create_materials() -> Dict[str, Any]:
    """Create material definitions for different surface types."""
    materials = {}
    
    for surface_type, props in SURFACE_COLORS.items():
        material_name = f"material_{surface_type.lower()}"
        materials[material_name] = {
            "type": "MeshStandardMaterial" if props["opacity"] == 1.0 else "MeshPhysicalMaterial",
            "color": props["color"],
            "opacity": props["opacity"],
            "transparent": props["opacity"] < 1.0,
            "side": 2,  # DoubleSide
            "metalness": 0.1,
            "roughness": 0.8
        }
    
    return materials


def _create_default_lights() -> List[Dict[str, Any]]:
    """Create default lighting setup."""
    return [
        {
            "type": "AmbientLight",
            "color": 0x404040,
            "intensity": 0.6
        },
        {
            "type": "DirectionalLight",
            "color": 0xffffff,
            "intensity": 0.8,
            "position": [100, 100, 50]
        },
        {
            "type": "DirectionalLight",
            "color": 0xffffff,
            "intensity": 0.4,
            "position": [-100, -100, 50]
        }
    ]


def _calculate_camera_position(geometry_data: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate optimal camera position based on building bounds."""
    # Find bounding box
    all_vertices = []
    
    for surface in geometry_data.get("surfaces", []):
        all_vertices.extend(surface.get("vertices", []))
    
    if not all_vertices:
        return {
            "position": [50, 50, 50],
            "lookAt": [0, 0, 0]
        }
    
    # Calculate bounds
    xs = [v[0] for v in all_vertices]
    ys = [v[1] for v in all_vertices]
    zs = [v[2] for v in all_vertices]
    
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    min_z, max_z = min(zs), max(zs)
    
    # Center of the building
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2
    center_z = (min_z + max_z) / 2
    
    # Building size
    size_x = max_x - min_x
    size_y = max_y - min_y
    size_z = max_z - min_z
    max_size = max(size_x, size_y, size_z)
    
    # Camera distance (2x building size for good view)
    distance = max_size * 2
    
    # Position camera at 45° angle
    camera_x = center_x + distance * 0.7
    camera_y = center_y + distance * 0.7
    camera_z = center_z + distance * 0.5
    
    return {
        "position": [camera_x, camera_y, camera_z],
        "lookAt": [center_x, center_y, center_z],
        "fov": 50,
        "near": 0.1,
        "far": max_size * 10
    }


def _create_surface_object(surface: Dict[str, Any], obj_type: str) -> Optional[Dict[str, Any]]:
    """Create a three.js object from a surface."""
    vertices = surface.get("vertices", [])
    if len(vertices) < 3:
        return None
    
    # Determine surface type and material
    surface_type = surface.get("surface_type", "WALL").upper()
    material_key = f"material_{surface_type.lower()}"
    
    # Triangulate the polygon
    triangles = triangulate_polygon(vertices)
    
    # Flatten vertices for three.js
    positions = []
    for v in vertices:
        positions.extend(v)  # [x, y, z, x, y, z, ...]
    
    # Create indices for triangles
    indices = []
    for tri in triangles:
        indices.extend(tri)
    
    # Calculate normals (simple approach - use first triangle normal)
    if len(vertices) >= 3:
        v1 = [vertices[1][i] - vertices[0][i] for i in range(3)]
        v2 = [vertices[2][i] - vertices[0][i] for i in range(3)]
        
        # Cross product
        normal = [
            v1[1] * v2[2] - v1[2] * v2[1],
            v1[2] * v2[0] - v1[0] * v2[2],
            v1[0] * v2[1] - v1[1] * v2[0]
        ]
        
        # Normalize
        magnitude = math.sqrt(sum(n**2 for n in normal))
        if magnitude > 0:
            normal = [n / magnitude for n in normal]
        else:
            normal = [0, 0, 1]
    else:
        normal = [0, 0, 1]
    
    # Repeat normal for each vertex
    normals = normal * len(vertices)
    
    return {
        "type": "Mesh",
        "name": surface.get("name", "Unknown"),
        "geometry": {
            "type": "BufferGeometry",
            "attributes": {
                "position": {
                    "itemSize": 3,
                    "array": positions
                },
                "normal": {
                    "itemSize": 3,
                    "array": normals
                }
            },
            "index": indices
        },
        "material": material_key,
        "userData": {
            "surface_type": surface_type,
            "construction": surface.get("construction", ""),
            "zone_name": surface.get("zone_name", ""),
            "base_surface_name": surface.get("base_surface_name", ""),
            "tilt": surface.get("tilt"),
            "azimuth": surface.get("azimuth")
        }
    }


def _create_shading_object(shading: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Create a three.js object from a shading surface."""
    vertices = shading.get("vertices", [])
    if len(vertices) < 3:
        return None
    
    # Reuse surface object creation with shading material
    shading_surface = {
        **shading,
        "surface_type": "SHADING"
    }
    
    return _create_surface_object(shading_surface, "shading")


def geometry_to_threejs_json(
    geometry_data: Dict[str, Any],
    include_subsurfaces: bool = True,
    include_shading: bool = True,
    pretty: bool = True
) -> str:
    """
    Convert geometry to three.js JSON string.
    
    Args:
        geometry_data: Geometry data from extract_building_geometry
        include_subsurfaces: Whether to include windows/doors
        include_shading: Whether to include shading surfaces
        pretty: Whether to format with indentation
        
    Returns:
        JSON string in three.js format
    """
    threejs_data = create_threejs_geometry(
        geometry_data,
        include_subsurfaces=include_subsurfaces,
        include_shading=include_shading
    )
    
    if pretty:
        return json.dumps(threejs_data, indent=2)
    return json.dumps(threejs_data)


def create_enhanced_html_viewer(
    geometry_data: Dict[str, Any],
    title: str = "Building Geometry Viewer"
) -> str:
    """
    Create an enhanced HTML viewer with the polished template.
    Returns the HTML string directly (no file writing).
    
    Args:
        geometry_data: Geometry data from extract_building_geometry
        title: Title for the viewer page
        
    Returns:
        HTML string with embedded geometry data
    """
    # Categorize surfaces
    categorized = categorize_surfaces(geometry_data)
    
    # Generate geometry JavaScript data structure
    zones_info = []
    for zone in geometry_data.get("zones", []):
        zones_info.append({
            "name": zone.get("name", "Unknown"),
            "floor_area": zone.get("floor_area"),
            "volume": zone.get("volume")
        })
    
    # Build surfaces array with categorization
    surfaces_js = []
    
    for surface in categorized["floors"]:
        surfaces_js.append({
            "type": "Floor",
            "zone": surface.get("zone_name", ""),
            "vertices": surface.get("vertices", [])
        })
    
    for surface in categorized["walls"]:
        surfaces_js.append({
            "type": "Wall",
            "zone": surface.get("zone_name", ""),
            "vertices": surface.get("vertices", [])
        })
    
    for surface in categorized["roofs"]:
        surfaces_js.append({
            "type": "Roof",
            "zone": surface.get("zone_name", ""),
            "vertices": surface.get("vertices", [])
        })
    
    for surface in categorized["ceilings"]:
        surfaces_js.append({
            "type": "Ceiling",
            "zone": surface.get("zone_name", ""),
            "vertices": surface.get("vertices", [])
        })
    
    for surface in categorized["partitions"]:
        surfaces_js.append({
            "type": "Partition",
            "zone": surface.get("zone_name", ""),
            "vertices": surface.get("vertices", [])
        })
    
    windows_js = [{"vertices": w.get("vertices", [])} for w in categorized["windows"]]
    doors_js = [{"vertices": d.get("vertices", [])} for d in categorized["doors"]]
    
    # Calculate building stats for info panel
    building_name = geometry_data.get("building", {}).get("name", "Building")
    total_volume = sum(z.get("volume", 0) for z in geometry_data.get("zones", []))
    
    # Generate zone info HTML
    zone_info_html = ""
    for zone in geometry_data.get("zones", [])[:3]:  # Show up to 3 zones
        name = zone.get("name", "Unknown")
        area = zone.get("floor_area")
        if area:
            zone_info_html += f'<p><strong>{name}:</strong> {area:.2f} m²</p>\n        '
    
    if total_volume > 0:
        zone_info_html += f'<p><strong>Total Volume:</strong> {total_volume:.2f} m³</p>'
    
    # Convert Python data to JavaScript
    zones_json = json.dumps(zones_info)
    surfaces_json = json.dumps(surfaces_js, indent=16)
    windows_json = json.dumps(windows_js, indent=16)
    doors_json = json.dumps(doors_js, indent=16)
    
    html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{
            margin: 0;
            overflow: hidden;
            font-family: Arial, sans-serif;
        }}
        #canvas-container {{
            width: 100vw;
            height: 100vh;
        }}
        #info {{
            position: absolute;
            top: 10px;
            left: 10px;
            background: rgba(255, 255, 255, 0.9);
            padding: 15px;
            border-radius: 5px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
            max-width: 300px;
        }}
        #info h3 {{
            margin: 0 0 10px 0;
            font-size: 16px;
        }}
        #info p {{
            margin: 5px 0;
            font-size: 12px;
        }}
        #controls {{
            position: absolute;
            top: 10px;
            right: 10px;
            background: rgba(255, 255, 255, 0.95);
            padding: 15px;
            border-radius: 5px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
            max-width: 380px;
        }}
        #controls h4 {{
            margin: 0 0 10px 0;
            font-size: 14px;
            color: #333;
            display: flex;
            align-items: center;
            justify-content: space-between;
            cursor: pointer;
            user-select: none;
        }}
        #controls h4:hover {{
            color: #4CAF50;
        }}
        .toggle-icon {{
            font-size: 12px;
            transition: transform 0.3s ease;
        }}
        .toggle-icon.collapsed {{
            transform: rotate(-90deg);
        }}
        #controls-content {{
            max-height: 1000px;
            overflow: hidden;
            transition: max-height 0.3s ease, opacity 0.3s ease;
        }}
        #controls-content.collapsed {{
            max-height: 0;
            opacity: 0;
        }}
        .control-row {{
            display: flex;
            align-items: center;
            margin: 8px 0;
            gap: 10px;
        }}
        .control-row label {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
            flex: 1;
            cursor: pointer;
            min-width: 110px;
        }}
        .control-row input[type="checkbox"] {{
            cursor: pointer;
            width: 16px;
            height: 16px;
        }}
        .control-row input[type="color"] {{
            cursor: pointer;
            width: 40px;
            height: 28px;
            border: 1px solid #ccc;
            border-radius: 3px;
        }}
        .control-row input[type="range"] {{
            cursor: pointer;
            width: 80px;
            height: 6px;
        }}
        .opacity-value {{
            font-size: 11px;
            color: #666;
            min-width: 35px;
            text-align: right;
        }}
        #controls button {{
            width: 100%;
            margin-top: 10px;
            padding: 10px;
            border: none;
            background: #4CAF50;
            color: white;
            border-radius: 3px;
            cursor: pointer;
            font-size: 13px;
            font-weight: bold;
        }}
        #controls button:hover {{
            background: #45a049;
        }}
        .section-divider {{
            border-top: 1px solid #ddd;
            margin: 12px 0;
        }}
        #loading {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-size: 24px;
            color: #333;
        }}
    </style>
</head>
<body>
    <div id="loading">Loading building geometry...</div>
    <div id="canvas-container"></div>
    <div id="info" style="display:none;">
        <h3 id="building-name">{building_name}</h3>
        {zone_info_html}
        <p style="margin-top: 10px; font-size: 11px; color: #666;">
            Left click + drag to rotate<br>
            Right click + drag to pan<br>
            Scroll to zoom<br>
            <br>
            <strong>Tip:</strong> Adjust colors and transparency to see through surfaces!
        </p>
    </div>
    <div id="controls" style="display:none;">
        <h4 id="controls-toggle">
            <span>Visualization Settings</span>
            <span class="toggle-icon">▼</span>
        </h4>
        
        <div id="controls-content">
            <div class="control-row">
                <label>
                    <input type="checkbox" id="toggle-floors" checked>
                    <span>🟫 Floors</span>
                </label>
                <input type="color" id="color-floors" value="#d4a574">
                <input type="range" id="opacity-floors" min="0" max="100" value="90">
                <span class="opacity-value" id="opacity-floors-value">90%</span>
            </div>
            
            <div class="control-row">
                <label>
                    <input type="checkbox" id="toggle-walls" checked>
                    <span>🧱 Walls</span>
                </label>
                <input type="color" id="color-walls" value="#f0e68c">
                <input type="range" id="opacity-walls" min="0" max="100" value="70">
                <span class="opacity-value" id="opacity-walls-value">70%</span>
            </div>
            
            <div class="control-row">
                <label>
                    <input type="checkbox" id="toggle-roofs" checked>
                    <span>🏠 Roofs</span>
                </label>
                <input type="color" id="color-roofs" value="#d03939">
                <input type="range" id="opacity-roofs" min="0" max="100" value="60">
                <span class="opacity-value" id="opacity-roofs-value">60%</span>
            </div>
            
            <div class="control-row">
                <label>
                    <input type="checkbox" id="toggle-partitions" checked>
                    <span>⭐ Partitions</span>
                </label>
                <input type="color" id="color-partitions" value="#ffa500">
                <input type="range" id="opacity-partitions" min="0" max="100" value="50">
                <span class="opacity-value" id="opacity-partitions-value">50%</span>
            </div>
            
            <div class="control-row">
                <label>
                    <input type="checkbox" id="toggle-windows" checked>
                    <span>🪟 Windows</span>
                </label>
                <input type="color" id="color-windows" value="#87ceeb">
                <input type="range" id="opacity-windows" min="0" max="100" value="30">
                <span class="opacity-value" id="opacity-windows-value">30%</span>
            </div>
            
            <div class="control-row">
                <label>
                    <input type="checkbox" id="toggle-doors" checked>
                    <span>🚪 Doors</span>
                </label>
                <input type="color" id="color-doors" value="#8b4513">
                <input type="range" id="opacity-doors" min="0" max="100" value="80">
                <span class="opacity-value" id="opacity-doors-value">80%</span>
            </div>
            
            <div class="section-divider"></div>
            
            <button id="reset-camera">🔄 Reset View</button>
        </div>
    </div>

    <script type="importmap">
    {{
        "imports": {{
            "three": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
            "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"
        }}
    }}
    </script>

    <script type="module">
        import * as THREE from 'three';
        import {{ OrbitControls }} from 'three/addons/controls/OrbitControls.js';

        let scene, camera, renderer, controls;
        let floorObjects = [];
        let wallObjects = [];
        let roofObjects = [];
        let partitionObjects = [];
        let windowObjects = [];
        let doorObjects = [];

        const geometryData = {{
            zones: {zones_json},
            surfaces: {surfaces_json},
            windows: {windows_json},
            doors: {doors_json}
        }};

        async function init() {{
            // Hide loading
            document.getElementById('loading').style.display = 'none';
            document.getElementById('info').style.display = 'block';
            document.getElementById('controls').style.display = 'block';

            // Setup scene
            scene = new THREE.Scene();
            scene.background = new THREE.Color(0xffffff);
            
            // STEP 1: Calculate building bounds in EnergyPlus space (for centering)
            let minX = Infinity, maxX = -Infinity;
            let minY = Infinity, maxY = -Infinity;
            let minZ_EP = Infinity, maxZ_EP = -Infinity;  // Z in EnergyPlus space
            
            geometryData.surfaces.forEach(surface => {{
                surface.vertices.forEach(v => {{
                    minX = Math.min(minX, v[0]);
                    maxX = Math.max(maxX, v[0]);
                    minY = Math.min(minY, v[1]);
                    maxY = Math.max(maxY, v[1]);
                    minZ_EP = Math.min(minZ_EP, v[2]);  // Height in EnergyPlus
                    maxZ_EP = Math.max(maxZ_EP, v[2]);
                }});
            }});
            
            // STEP 2: Calculate center offsets
            const centerOffsetX = (minX + maxX) / 2;
            const centerOffsetY = (minY + maxY) / 2;
            
            // STEP 3: Calculate building dimensions in Three.js space (after transformation)
            const buildingWidth = maxX - minX;      // X stays X
            const buildingDepth = maxY - minY;      // Y becomes -Z, but dimension is same
            const buildingHeight = maxZ_EP - minZ_EP;  // Z becomes Y
            const buildingSize = Math.max(buildingWidth, buildingDepth, buildingHeight);
            
            // Building center in Three.js space is now at (0, buildingHeight/2, 0)
            const centerHeight = buildingHeight / 2;
            
            // STEP 4: Setup camera to view the centered building
            const cameraDistance = buildingSize * 1.5;
            camera = new THREE.PerspectiveCamera(
                50,
                window.innerWidth / window.innerHeight,
                0.1,
                buildingSize * 10
            );
            camera.position.set(
                cameraDistance * 0.7,     // To the right
                cameraDistance * 0.6,     // Above
                cameraDistance * 0.7      // In front
            );
            camera.lookAt(0, centerHeight, 0);  // Look at building center

            // Setup renderer
            const container = document.getElementById('canvas-container');
            renderer = new THREE.WebGLRenderer({{ antialias: true }});
            renderer.setSize(window.innerWidth, window.innerHeight);
            renderer.shadowMap.enabled = true;
            renderer.shadowMap.type = THREE.PCFSoftShadowMap;
            container.appendChild(renderer.domElement);

            // Setup controls
            controls = new OrbitControls(camera, renderer.domElement);
            controls.target.set(0, centerHeight, 0);  // Orbit around building center
            controls.update();
            
            // STEP 5: Setup lights OUTSIDE and ABOVE the building
            // Light is positioned in Three.js space relative to centered building
            const lightDistance = buildingSize * 2;
            const lightHeight = maxZ_EP + buildingSize * 0.5;  // Above the building top
            
            const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
            scene.add(ambientLight);

            // Main directional light (like sun)
            const directionalLight1 = new THREE.DirectionalLight(0xffffff, 0.8);
            directionalLight1.position.set(
                buildingWidth * 0.8,        // To the right of building
                lightHeight,                // Well above building
                buildingDepth * 0.8         // In front of building (positive Z in Three.js)
            );
            directionalLight1.castShadow = true;
            directionalLight1.target.position.set(0, 0, 0);  // Point at origin (building center)
            scene.add(directionalLight1.target);
            
            // Configure shadow camera to cover the entire building AND its shadow
            // Make it 3x building size to ensure shadow doesn't get clipped
            const shadowCameraSize = buildingSize * 3;
            directionalLight1.shadow.camera.left = -shadowCameraSize;
            directionalLight1.shadow.camera.right = shadowCameraSize;
            directionalLight1.shadow.camera.top = shadowCameraSize;
            directionalLight1.shadow.camera.bottom = -shadowCameraSize;
            directionalLight1.shadow.camera.near = 0.5;
            directionalLight1.shadow.camera.far = lightHeight * 3;
            directionalLight1.shadow.mapSize.width = 2048;
            directionalLight1.shadow.mapSize.height = 2048;
            directionalLight1.shadow.bias = -0.0001;
            
            scene.add(directionalLight1);

            // Fill light from opposite side (no shadows)
            const directionalLight2 = new THREE.DirectionalLight(0xffffff, 0.3);
            directionalLight2.position.set(
                -buildingWidth * 0.5,
                buildingHeight * 0.8,
                -buildingDepth * 0.5
            );
            scene.add(directionalLight2);

            // Create materials
            const materials = {{
                floor: new THREE.MeshStandardMaterial({{
                    color: 0xd4a574,
                    side: THREE.DoubleSide,
                    roughness: 0.8,
                    metalness: 0.1,
                    transparent: true,
                    opacity: 0.9
                }}),
                wall: new THREE.MeshStandardMaterial({{
                    color: 0xf0e68c,
                    side: THREE.DoubleSide,
                    roughness: 0.9,
                    metalness: 0.1,
                    transparent: true,
                    opacity: 0.7
                }}),
                roof: new THREE.MeshStandardMaterial({{
                    color: 0xd03939,
                    side: THREE.DoubleSide,
                    roughness: 0.7,
                    metalness: 0.2,
                    transparent: true,
                    opacity: 0.6
                }}),
                partition: new THREE.MeshStandardMaterial({{
                    color: 0xffa500,
                    side: THREE.DoubleSide,
                    transparent: true,
                    opacity: 0.5,
                    roughness: 0.5,
                    metalness: 0.2,
                    depthWrite: false
                }}),
                window: new THREE.MeshStandardMaterial({{
                    color: 0x87ceeb,
                    side: THREE.DoubleSide,
                    transparent: true,
                    opacity: 0.3,
                    roughness: 0.3,
                    metalness: 0.1,
                    depthWrite: false
                }}),
                door: new THREE.MeshStandardMaterial({{
                    color: 0x8b4513,
                    side: THREE.DoubleSide,
                    roughness: 0.8,
                    metalness: 0.1,
                    transparent: true,
                    opacity: 0.8
                }})
            }};

            // Helper function to create a quad (centerOffsetX/Y already calculated above)
            function createQuad(vertices, material, offset = 0) {{
                const geometry = new THREE.BufferGeometry();
                
                // Convert to Three.js coordinates with centering: x=x-centerX, y=z, z=-y+centerY
                const v = vertices.map(v => new THREE.Vector3(
                    v[0] - centerOffsetX, 
                    v[2], 
                    -(v[1] - centerOffsetY)
                ));
                
                // If offset is specified, push the quad along its normal
                if (offset !== 0) {{
                    const v1 = new THREE.Vector3().subVectors(v[1], v[0]);
                    const v2 = new THREE.Vector3().subVectors(v[2], v[0]);
                    const normal = new THREE.Vector3().crossVectors(v1, v2).normalize();
                    
                    v.forEach(vertex => {{
                        vertex.x += normal.x * offset;
                        vertex.y += normal.y * offset;
                        vertex.z += normal.z * offset;
                    }});
                }}
                
                const positions = new Float32Array([
                    v[0].x, v[0].y, v[0].z,
                    v[1].x, v[1].y, v[1].z,
                    v[2].x, v[2].y, v[2].z,
                    v[0].x, v[0].y, v[0].z,
                    v[2].x, v[2].y, v[2].z,
                    v[3].x, v[3].y, v[3].z,
                ]);
                
                geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
                geometry.computeVertexNormals();
                
                const mesh = new THREE.Mesh(geometry, material);
                // Building surfaces cast shadows (onto ground) but DON'T receive them
                // This prevents unrealistic self-shadowing (roof shadow on walls, etc.)
                mesh.castShadow = true;
                mesh.receiveShadow = false;  // Building doesn't shadow itself
                
                return mesh;
            }}

            // Add surfaces
            geometryData.surfaces.forEach(surface => {{
                let material, array;
                
                switch (surface.type) {{
                    case 'Floor':
                        material = materials.floor;
                        array = floorObjects;
                        break;
                    case 'Wall':
                        material = materials.wall;
                        array = wallObjects;
                        break;
                    case 'Roof':
                    case 'Ceiling':
                        material = materials.roof;
                        array = roofObjects;
                        break;
                    case 'Partition':
                        material = materials.partition;
                        array = partitionObjects;
                        break;
                }}
                
                if (material) {{
                    const mesh = createQuad(surface.vertices, material);
                    mesh.userData.type = surface.type;
                    mesh.userData.zone = surface.zone;
                    array.push(mesh);
                    scene.add(mesh);
                }}
            }});

            // Add windows (with offset to prevent z-fighting)
            geometryData.windows.forEach(window => {{
                const mesh = createQuad(window.vertices, materials.window, 0.02);
                mesh.userData.type = 'Window';
                windowObjects.push(mesh);
                scene.add(mesh);
            }});

            // Add doors (with offset to prevent z-fighting)
            geometryData.doors.forEach(door => {{
                const mesh = createQuad(door.vertices, materials.door, 0.02);
                mesh.userData.type = 'Door';
                doorObjects.push(mesh);
                scene.add(mesh);
            }});

            // Create simple ground
            const grassGeometry = new THREE.PlaneGeometry(50, 50);
            const grassMaterial = new THREE.MeshStandardMaterial({{ 
                color: 0x7cb342,
                side: THREE.DoubleSide,
                roughness: 0.95
            }});
            const grass = new THREE.Mesh(grassGeometry, grassMaterial);
            grass.rotation.x = Math.PI / 2;
            grass.position.set(0, -0.05, 0);
            grass.receiveShadow = true;
            scene.add(grass);

            // Subtle grid overlay for reference
            const subtleGrid = new THREE.GridHelper(50, 50, 0xdddddd, 0xf0f0f0);
            subtleGrid.position.set(0, 0.01, 0);
            subtleGrid.material.opacity = 0.3;
            subtleGrid.material.transparent = true;
            scene.add(subtleGrid);

            // Setup button controls
            setupControls();

            // Start animation
            animate();

            // Handle window resize
            window.addEventListener('resize', onWindowResize);
        }}

        function setupControls() {{
            // Collapsible controls toggle
            document.getElementById('controls-toggle').addEventListener('click', () => {{
                const content = document.getElementById('controls-content');
                const icon = document.querySelector('.toggle-icon');
                
                content.classList.toggle('collapsed');
                icon.classList.toggle('collapsed');
            }});

            // Toggle visibility with checkboxes
            document.getElementById('toggle-floors').addEventListener('change', (e) => {{
                floorObjects.forEach(obj => obj.visible = e.target.checked);
            }});

            document.getElementById('toggle-walls').addEventListener('change', (e) => {{
                wallObjects.forEach(obj => obj.visible = e.target.checked);
            }});

            document.getElementById('toggle-roofs').addEventListener('change', (e) => {{
                roofObjects.forEach(obj => obj.visible = e.target.checked);
            }});

            document.getElementById('toggle-partitions').addEventListener('change', (e) => {{
                partitionObjects.forEach(obj => obj.visible = e.target.checked);
            }});

            document.getElementById('toggle-windows').addEventListener('change', (e) => {{
                windowObjects.forEach(obj => obj.visible = e.target.checked);
            }});

            document.getElementById('toggle-doors').addEventListener('change', (e) => {{
                doorObjects.forEach(obj => obj.visible = e.target.checked);
            }});

            // Color pickers
            document.getElementById('color-floors').addEventListener('input', (e) => {{
                const color = new THREE.Color(e.target.value);
                floorObjects.forEach(obj => obj.material.color = color);
            }});

            document.getElementById('color-walls').addEventListener('input', (e) => {{
                const color = new THREE.Color(e.target.value);
                wallObjects.forEach(obj => obj.material.color = color);
            }});

            document.getElementById('color-roofs').addEventListener('input', (e) => {{
                const color = new THREE.Color(e.target.value);
                roofObjects.forEach(obj => obj.material.color = color);
            }});

            document.getElementById('color-partitions').addEventListener('input', (e) => {{
                const color = new THREE.Color(e.target.value);
                partitionObjects.forEach(obj => obj.material.color = color);
            }});

            document.getElementById('color-windows').addEventListener('input', (e) => {{
                const color = new THREE.Color(e.target.value);
                windowObjects.forEach(obj => obj.material.color = color);
            }});

            document.getElementById('color-doors').addEventListener('input', (e) => {{
                const color = new THREE.Color(e.target.value);
                doorObjects.forEach(obj => obj.material.color = color);
            }});

            // Opacity sliders
            document.getElementById('opacity-floors').addEventListener('input', (e) => {{
                const opacity = e.target.value / 100;
                floorObjects.forEach(obj => obj.material.opacity = opacity);
                document.getElementById('opacity-floors-value').textContent = e.target.value + '%';
            }});

            document.getElementById('opacity-walls').addEventListener('input', (e) => {{
                const opacity = e.target.value / 100;
                wallObjects.forEach(obj => obj.material.opacity = opacity);
                document.getElementById('opacity-walls-value').textContent = e.target.value + '%';
            }});

            document.getElementById('opacity-roofs').addEventListener('input', (e) => {{
                const opacity = e.target.value / 100;
                roofObjects.forEach(obj => obj.material.opacity = opacity);
                document.getElementById('opacity-roofs-value').textContent = e.target.value + '%';
            }});

            document.getElementById('opacity-partitions').addEventListener('input', (e) => {{
                const opacity = e.target.value / 100;
                partitionObjects.forEach(obj => obj.material.opacity = opacity);
                document.getElementById('opacity-partitions-value').textContent = e.target.value + '%';
            }});

            document.getElementById('opacity-windows').addEventListener('input', (e) => {{
                const opacity = e.target.value / 100;
                windowObjects.forEach(obj => obj.material.opacity = opacity);
                document.getElementById('opacity-windows-value').textContent = e.target.value + '%';
            }});

            document.getElementById('opacity-doors').addEventListener('input', (e) => {{
                const opacity = e.target.value / 100;
                doorObjects.forEach(obj => obj.material.opacity = opacity);
                document.getElementById('opacity-doors-value').textContent = e.target.value + '%';
            }});

            // Reset camera button
            document.getElementById('reset-camera').addEventListener('click', () => {{
                controls.reset();
            }});
        }}

        function animate() {{
            requestAnimationFrame(animate);
            controls.update();
            renderer.render(scene, camera);
        }}

        function onWindowResize() {{
            camera.aspect = window.innerWidth / window.innerHeight;
            camera.updateProjectionMatrix();
            renderer.setSize(window.innerWidth, window.innerHeight);
        }}

        // Initialize
        init().catch(error => {{
            document.getElementById('loading').textContent = 'Error loading geometry: ' + error.message;
            console.error('Error:', error);
        }});
    </script>
</body>
</html>'''

    return html_content


def create_html_viewer(
    threejs_json_path: str,
    output_html_path: str,
    title: str = "Building Geometry Viewer",
    embed_data: bool = True
) -> str:
    """
    Create a standalone HTML viewer for the three.js geometry.
    
    Args:
        threejs_json_path: Path to the three.js JSON file (or just filename if embed_data=False)
        output_html_path: Path where HTML file will be saved
        title: Title for the viewer page
        embed_data: If True, embed JSON data in HTML (avoids CORS issues). If False, load via fetch.
        
    Returns:
        Path to the created HTML file
    """
    
    # Load JSON data if embedding
    json_data_embedded = ""
    if embed_data:
        try:
            with open(threejs_json_path, 'r') as f:
                json_content = f.read()
            json_data_embedded = f"const data = {json_content};"
        except Exception:
            # If file doesn't exist yet, will be created later
            json_data_embedded = "const data = null;"
    else:
        json_data_embedded = f"""
        // Load data from external file
        const response = await fetch('{threejs_json_path}');
        const data = await response.json();
        """
    html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{
            margin: 0;
            overflow: hidden;
            font-family: Arial, sans-serif;
        }}
        #canvas-container {{
            width: 100vw;
            height: 100vh;
        }}
        #info {{
            position: absolute;
            top: 10px;
            left: 10px;
            background: rgba(255, 255, 255, 0.9);
            padding: 15px;
            border-radius: 5px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
            max-width: 300px;
        }}
        #info h3 {{
            margin: 0 0 10px 0;
            font-size: 16px;
        }}
        #info p {{
            margin: 5px 0;
            font-size: 12px;
        }}
        #controls {{
            position: absolute;
            bottom: 10px;
            left: 10px;
            background: rgba(255, 255, 255, 0.9);
            padding: 10px;
            border-radius: 5px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
        }}
        #controls button {{
            margin: 5px;
            padding: 8px 15px;
            border: none;
            background: #4CAF50;
            color: white;
            border-radius: 3px;
            cursor: pointer;
        }}
        #controls button:hover {{
            background: #45a049;
        }}
        #loading {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-size: 24px;
            color: #333;
        }}
    </style>
</head>
<body>
    <div id="loading">Loading building geometry...</div>
    <div id="canvas-container"></div>
    <div id="info" style="display:none;">
        <h3 id="building-name">Building</h3>
        <p><strong>Surfaces:</strong> <span id="surface-count">0</span></p>
        <p><strong>Subsurfaces:</strong> <span id="subsurface-count">0</span></p>
        <p><strong>Shading:</strong> <span id="shading-count">0</span></p>
        <p style="margin-top: 10px; font-size: 11px; color: #666;">
            Left click + drag to rotate<br>
            Right click + drag to pan<br>
            Scroll to zoom
        </p>
    </div>
    <div id="controls" style="display:none;">
        <button id="toggle-subsurfaces">Toggle Windows/Doors</button>
        <button id="toggle-shading">Toggle Shading</button>
        <button id="reset-camera">Reset View</button>
    </div>

    <script type="importmap">
    {{
        "imports": {{
            "three": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",
            "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"
        }}
    }}
    </script>

    <script type="module">
        import * as THREE from 'three';
        import {{ OrbitControls }} from 'three/addons/controls/OrbitControls.js';

        let scene, camera, renderer, controls;
        let subsurfaceObjects = [];
        let shadingObjects = [];

        async function init() {{
            // Load geometry data
            {json_data_embedded}
            
            if (!data) {{
                throw new Error('No geometry data available');
            }}

            // Hide loading
            document.getElementById('loading').style.display = 'none';
            document.getElementById('info').style.display = 'block';
            document.getElementById('controls').style.display = 'block';

            // Update info
            document.getElementById('building-name').textContent = data.metadata.building_name;
            
            // Setup scene
            scene = new THREE.Scene();
            scene.background = new THREE.Color(0x87CEEB);
            
            // Setup camera
            const camData = data.camera;
            camera = new THREE.PerspectiveCamera(
                camData.fov || 50,
                window.innerWidth / window.innerHeight,
                camData.near || 0.1,
                camData.far || 10000
            );
            camera.position.set(...camData.position);
            camera.lookAt(...camData.lookAt);

            // Setup renderer
            const container = document.getElementById('canvas-container');
            renderer = new THREE.WebGLRenderer({{ antialias: true }});
            renderer.setSize(window.innerWidth, window.innerHeight);
            renderer.shadowMap.enabled = true;
            container.appendChild(renderer.domElement);

            // Setup controls
            controls = new OrbitControls(camera, renderer.domElement);
            controls.target.set(...camData.lookAt);
            controls.update();

            // Add lights
            data.lights.forEach(lightData => {{
                let light;
                if (lightData.type === 'AmbientLight') {{
                    light = new THREE.AmbientLight(lightData.color, lightData.intensity);
                }} else if (lightData.type === 'DirectionalLight') {{
                    light = new THREE.DirectionalLight(lightData.color, lightData.intensity);
                    light.position.set(...lightData.position);
                    light.castShadow = true;
                }}
                scene.add(light);
            }});

            // Create materials
            const materials = {{}};
            for (const [name, matData] of Object.entries(data.materials)) {{
                materials[name] = new THREE.MeshStandardMaterial({{
                    color: matData.color,
                    opacity: matData.opacity,
                    transparent: matData.transparent,
                    side: THREE.DoubleSide,
                    metalness: matData.metalness || 0.1,
                    roughness: matData.roughness || 0.8
                }});
            }}

            // Add objects
            let surfaceCount = 0;
            let subsurfaceCount = 0;
            let shadingCount = 0;

            data.objects.forEach(objData => {{
                const geometry = new THREE.BufferGeometry();
                
                const positions = new Float32Array(objData.geometry.attributes.position.array);
                const normals = new Float32Array(objData.geometry.attributes.normal.array);
                const indices = new Uint16Array(objData.geometry.index);
                
                geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
                geometry.setAttribute('normal', new THREE.BufferAttribute(normals, 3));
                geometry.setIndex(new THREE.BufferAttribute(indices, 1));

                const material = materials[objData.material] || materials['material_wall'];
                const mesh = new THREE.Mesh(geometry, material);
                mesh.name = objData.name;
                mesh.userData = objData.userData;

                // Categorize objects
                if (objData.userData.surface_type === 'WINDOW' || 
                    objData.userData.surface_type === 'DOOR' || 
                    objData.userData.surface_type === 'GLASSDOOR') {{
                    subsurfaceObjects.push(mesh);
                    subsurfaceCount++;
                }} else if (objData.userData.surface_type === 'SHADING') {{
                    shadingObjects.push(mesh);
                    shadingCount++;
                }} else {{
                    surfaceCount++;
                }}

                scene.add(mesh);
            }});

            // Update counts
            document.getElementById('surface-count').textContent = surfaceCount;
            document.getElementById('subsurface-count').textContent = subsurfaceCount;
            document.getElementById('shading-count').textContent = shadingCount;

            // Add ground plane
            const groundGeometry = new THREE.PlaneGeometry(1000, 1000);
            const groundMaterial = new THREE.MeshStandardMaterial({{ 
                color: 0x90EE90, 
                side: THREE.DoubleSide 
            }});
            const ground = new THREE.Mesh(groundGeometry, groundMaterial);
            ground.rotation.x = Math.PI / 2;
            ground.position.z = 0;
            ground.receiveShadow = true;
            scene.add(ground);

            // Add grid
            const gridHelper = new THREE.GridHelper(1000, 50);
            gridHelper.position.z = 0.1;
            scene.add(gridHelper);

            // Setup controls
            setupControls();

            // Start animation
            animate();

            // Handle window resize
            window.addEventListener('resize', onWindowResize);
        }}

        function setupControls() {{
            document.getElementById('toggle-subsurfaces').addEventListener('click', () => {{
                subsurfaceObjects.forEach(obj => {{
                    obj.visible = !obj.visible;
                }});
            }});

            document.getElementById('toggle-shading').addEventListener('click', () => {{
                shadingObjects.forEach(obj => {{
                    obj.visible = !obj.visible;
                }});
            }});

            document.getElementById('reset-camera').addEventListener('click', () => {{
                controls.reset();
            }});
        }}

        function animate() {{
            requestAnimationFrame(animate);
            controls.update();
            renderer.render(scene, camera);
        }}

        function onWindowResize() {{
            camera.aspect = window.innerWidth / window.innerHeight;
            camera.updateProjectionMatrix();
            renderer.setSize(window.innerWidth, window.innerHeight);
        }}

        // Initialize
        init().catch(error => {{
            document.getElementById('loading').textContent = 'Error loading geometry: ' + error.message;
            console.error('Error:', error);
        }});
    </script>
</body>
</html>"""

    with open(output_html_path, 'w') as f:
        f.write(html_template)
    
    return output_html_path

