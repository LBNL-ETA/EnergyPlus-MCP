"""
Geometry extraction and processing utilities for EnergyPlus IDF files.

This module provides functions to extract building geometry information including:
- Building metadata
- Zones with area and volume
- Surfaces (walls, floors, roofs, ceilings) with vertices
- Subsurfaces (windows, doors) with vertices
- Shading surfaces with vertices
- Calculated tilt and azimuth angles
"""

import json
import math
from typing import Any, Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


def calculate_tilt_and_azimuth(vertices: List[List[float]]) -> Tuple[float, float]:
    """
    Calculate tilt and azimuth from surface vertices.
    
    Args:
        vertices: List of [x, y, z] coordinates defining the surface
        
    Returns:
        Tuple of (tilt, azimuth) in degrees
        - Tilt: 0° = horizontal facing up, 90° = vertical, 180° = horizontal facing down
        - Azimuth: 0° = North, 90° = East, 180° = South, 270° = West
    """
    if len(vertices) < 3:
        return 0.0, 0.0
    
    try:
        # Calculate normal vector using first three vertices
        v1 = [vertices[1][i] - vertices[0][i] for i in range(3)]
        v2 = [vertices[2][i] - vertices[0][i] for i in range(3)]
        
        # Cross product to get normal vector
        normal = [
            v1[1] * v2[2] - v1[2] * v2[1],
            v1[2] * v2[0] - v1[0] * v2[2],
            v1[0] * v2[1] - v1[1] * v2[0]
        ]
        
        # Normalize
        magnitude = math.sqrt(sum(n**2 for n in normal))
        if magnitude < 1e-10:
            return 0.0, 0.0
        
        normal = [n / magnitude for n in normal]
        
        # Calculate tilt (angle from vertical)
        # Tilt = arccos(normal_z) converted to degrees
        tilt = math.degrees(math.acos(max(-1.0, min(1.0, normal[2]))))
        
        # Calculate azimuth (angle from North in horizontal plane)
        # Azimuth is measured clockwise from North
        if abs(normal[0]) < 1e-10 and abs(normal[1]) < 1e-10:
            azimuth = 0.0  # Horizontal surface
        else:
            azimuth = math.degrees(math.atan2(normal[0], normal[1]))
            if azimuth < 0:
                azimuth += 360
        
        return round(tilt, 2), round(azimuth, 2)
    
    except Exception as e:
        logger.warning(f"Error calculating tilt/azimuth: {e}")
        return 0.0, 0.0


def extract_vertices(obj: Any) -> List[List[float]]:
    """
    Extract vertices from an EnergyPlus surface object.
    
    Args:
        obj: EnergyPlus IDF object with vertex fields
        
    Returns:
        List of [x, y, z] coordinate triplets
    """
    vertices = []
    i = 0
    
    # Find where vertex data starts (after standard fields)
    field_names = [f.lower() for f in obj.fieldnames]
    
    # Look for vertex coordinate patterns
    for idx, name in enumerate(field_names):
        if 'vertex' in name and ('x' in name or 'coordinate' in name):
            # Found start of vertex data
            i = idx
            break
    
    # Extract vertices (groups of 3 coordinates)
    while i < len(obj.fieldvalues):
        try:
            x = float(obj.fieldvalues[i]) if obj.fieldvalues[i] else 0.0
            y = float(obj.fieldvalues[i + 1]) if i + 1 < len(obj.fieldvalues) and obj.fieldvalues[i + 1] else 0.0
            z = float(obj.fieldvalues[i + 2]) if i + 2 < len(obj.fieldvalues) and obj.fieldvalues[i + 2] else 0.0
            vertices.append([x, y, z])
            i += 3
        except (ValueError, IndexError):
            break
    
    return vertices


def extract_building_geometry(idf: Any) -> Dict[str, Any]:
    """
    Extract complete building geometry from an IDF object.
    
    Args:
        idf: Loaded EnergyPlus IDF object
        
    Returns:
        Dictionary containing building metadata, zones, surfaces, subsurfaces, and shading
    """
    geometry = {
        "building": {},
        "zones": [],
        "surfaces": [],
        "subsurfaces": [],
        "shading_surfaces": []
    }
    
    # Extract building metadata
    try:
        buildings = idf.idfobjects.get("BUILDING", [])
        if buildings:
            building = buildings[0]
            geometry["building"] = {
                "name": building.Name if hasattr(building, "Name") else "Unknown",
                "north_axis": float(building.North_Axis) if hasattr(building, "North_Axis") and building.North_Axis else 0.0,
                "terrain": building.Terrain if hasattr(building, "Terrain") else "Suburbs"
            }
    except Exception as e:
        logger.warning(f"Error extracting building data: {e}")
        geometry["building"] = {"name": "Unknown", "north_axis": 0.0, "terrain": "Suburbs"}
    
    # Extract zones
    try:
        zones = idf.idfobjects.get("ZONE", [])
        for zone in zones:
            zone_data = {
                "name": zone.Name if hasattr(zone, "Name") else "Unknown"
            }
            
            # Add optional fields if available
            if hasattr(zone, "Floor_Area") and zone.Floor_Area:
                zone_data["floor_area"] = float(zone.Floor_Area)
            if hasattr(zone, "Volume") and zone.Volume:
                zone_data["volume"] = float(zone.Volume)
            
            geometry["zones"].append(zone_data)
    except Exception as e:
        logger.warning(f"Error extracting zones: {e}")
    
    # Extract surfaces (BuildingSurface:Detailed and variants)
    surface_types = [
        "BUILDINGSURFACE:DETAILED",
        "WALL:DETAILED",
        "FLOOR:DETAILED", 
        "ROOFCEILING:DETAILED",
        "CEILING:DETAILED",
        "ROOF:DETAILED"
    ]
    
    for surface_type in surface_types:
        try:
            surfaces = idf.idfobjects.get(surface_type, [])
            for surface in surfaces:
                vertices = extract_vertices(surface)
                tilt, azimuth = calculate_tilt_and_azimuth(vertices)
                
                surface_data = {
                    "name": surface.Name if hasattr(surface, "Name") else "Unknown",
                    "surface_type": surface.Surface_Type if hasattr(surface, "Surface_Type") else surface_type.split(":")[0].title(),
                    "construction": surface.Construction_Name if hasattr(surface, "Construction_Name") else "",
                    "zone_name": surface.Zone_Name if hasattr(surface, "Zone_Name") else "",
                    "outside_boundary_condition": surface.Outside_Boundary_Condition if hasattr(surface, "Outside_Boundary_Condition") else "",
                    "vertices": vertices,
                    "tilt": tilt,
                    "azimuth": azimuth
                }
                
                # Add optional fields
                if hasattr(surface, "Sun_Exposure"):
                    surface_data["sun_exposure"] = surface.Sun_Exposure
                if hasattr(surface, "Wind_Exposure"):
                    surface_data["wind_exposure"] = surface.Wind_Exposure
                
                geometry["surfaces"].append(surface_data)
        except Exception as e:
            logger.warning(f"Error extracting {surface_type}: {e}")
    
    # Extract subsurfaces (windows, doors, etc.)
    subsurface_types = [
        "FENESTRATIONSURFACE:DETAILED",
        "WINDOW",
        "DOOR",
        "GLASSDOOR"
    ]
    
    for subsurface_type in subsurface_types:
        try:
            subsurfaces = idf.idfobjects.get(subsurface_type, [])
            for subsurface in subsurfaces:
                vertices = extract_vertices(subsurface)
                
                subsurface_data = {
                    "name": subsurface.Name if hasattr(subsurface, "Name") else "Unknown",
                    "surface_type": subsurface.Surface_Type if hasattr(subsurface, "Surface_Type") else subsurface_type.title(),
                    "construction": subsurface.Construction_Name if hasattr(subsurface, "Construction_Name") else "",
                    "base_surface_name": subsurface.Building_Surface_Name if hasattr(subsurface, "Building_Surface_Name") else "",
                    "vertices": vertices
                }
                
                # Add optional fields
                if hasattr(subsurface, "Multiplier") and subsurface.Multiplier:
                    subsurface_data["multiplier"] = float(subsurface.Multiplier)
                
                geometry["subsurfaces"].append(subsurface_data)
        except Exception as e:
            logger.warning(f"Error extracting {subsurface_type}: {e}")
    
    # Extract shading surfaces
    shading_types = [
        "SHADING:SITE:DETAILED",
        "SHADING:BUILDING:DETAILED",
        "SHADING:ZONE:DETAILED",
        "SHADING:OVERHANG",
        "SHADING:FIN"
    ]
    
    for shading_type in shading_types:
        try:
            shadings = idf.idfobjects.get(shading_type, [])
            for shading in shadings:
                vertices = extract_vertices(shading)
                
                shading_data = {
                    "name": shading.Name if hasattr(shading, "Name") else "Unknown",
                    "type": shading_type.split(":")[-1].lower(),
                    "vertices": vertices
                }
                
                # Add zone reference if it's zone shading
                if "ZONE" in shading_type and hasattr(shading, "Base_Surface_Name"):
                    shading_data["base_surface_name"] = shading.Base_Surface_Name
                
                geometry["shading_surfaces"].append(shading_data)
        except Exception as e:
            logger.warning(f"Error extracting {shading_type}: {e}")
    
    return geometry


def geometry_to_json(geometry: Dict[str, Any], pretty: bool = True) -> str:
    """
    Convert geometry dictionary to JSON string.
    
    Args:
        geometry: Dictionary containing geometry data
        pretty: Whether to format with indentation
        
    Returns:
        JSON string representation
    """
    if pretty:
        return json.dumps(geometry, indent=2)
    return json.dumps(geometry)


def get_brief_summary(geometry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate a brief structured summary of the geometry.
    
    Args:
        geometry: Dictionary containing geometry data
        
    Returns:
        Dictionary with concise summary information
    """
    # Count surface types
    surface_types = {}
    for surface in geometry['surfaces']:
        stype = surface.get('surface_type', 'Unknown')
        surface_types[stype] = surface_types.get(stype, 0) + 1
    
    # Count subsurface types
    subsurface_types = {}
    for subsurface in geometry['subsurfaces']:
        stype = subsurface.get('surface_type', 'Unknown')
        subsurface_types[stype] = subsurface_types.get(stype, 0) + 1
    
    # Calculate total floor area and volume
    total_floor_area = sum(zone.get('floor_area', 0) for zone in geometry['zones'])
    total_volume = sum(zone.get('volume', 0) for zone in geometry['zones'])
    
    summary = {
        "building": {
            "name": geometry['building'].get('name', 'Unknown'),
            "north_axis": geometry['building'].get('north_axis', 0),
            "terrain": geometry['building'].get('terrain', 'Unknown')
        },
        "counts": {
            "zones": len(geometry['zones']),
            "surfaces": len(geometry['surfaces']),
            "subsurfaces": len(geometry['subsurfaces']),
            "shading_surfaces": len(geometry['shading_surfaces'])
        },
        "surface_types": surface_types,
        "subsurface_types": subsurface_types,
        "totals": {
            "floor_area_m2": round(total_floor_area, 2),
            "volume_m3": round(total_volume, 2)
        }
    }
    
    return summary


def get_geometry_summary(geometry: Dict[str, Any]) -> str:
    """
    Generate a human-readable summary of the geometry.
    
    Args:
        geometry: Dictionary containing geometry data
        
    Returns:
        Formatted summary string
    """
    summary = []
    summary.append(f"Building: {geometry['building'].get('name', 'Unknown')}")
    summary.append(f"  North Axis: {geometry['building'].get('north_axis', 0)}°")
    summary.append(f"  Terrain: {geometry['building'].get('terrain', 'Unknown')}")
    summary.append(f"\nZones: {len(geometry['zones'])}")
    
    for zone in geometry['zones']:
        summary.append(f"  - {zone['name']}")
        if 'floor_area' in zone:
            summary.append(f"    Floor Area: {zone['floor_area']:.2f} m²")
        if 'volume' in zone:
            summary.append(f"    Volume: {zone['volume']:.2f} m³")
    
    summary.append(f"\nSurfaces: {len(geometry['surfaces'])}")
    surface_types = {}
    for surface in geometry['surfaces']:
        stype = surface.get('surface_type', 'Unknown')
        surface_types[stype] = surface_types.get(stype, 0) + 1
    for stype, count in surface_types.items():
        summary.append(f"  - {stype}: {count}")
    
    summary.append(f"\nSubsurfaces: {len(geometry['subsurfaces'])}")
    subsurface_types = {}
    for subsurface in geometry['subsurfaces']:
        stype = subsurface.get('surface_type', 'Unknown')
        subsurface_types[stype] = subsurface_types.get(stype, 0) + 1
    for stype, count in subsurface_types.items():
        summary.append(f"  - {stype}: {count}")
    
    summary.append(f"\nShading Surfaces: {len(geometry['shading_surfaces'])}")
    
    return "\n".join(summary)


