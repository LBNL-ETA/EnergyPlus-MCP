"""
EnergyPlus tools with configuration management and simulation control

EnergyPlus Model Context Protocol Server (EnergyPlus-MCP)
Copyright (c) 2025, The Regents of the University of California,
through Lawrence Berkeley National Laboratory (subject to receipt of
any required approvals from the U.S. Dept. of Energy). All rights reserved.

See License.txt in the parent directory for license details.
"""

import os
import json
import logging
from typing import Dict, List, Any, Optional
from pathlib import Path

import eppy
from eppy.modeleditor import IDF
from eppy import hvacbuilder
from eppy.useful_scripts import loopdiagram
from eppy import walk_hvac
from datetime import datetime
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.patches import FancyBboxPatch
import networkx as nx
import calendar
import string
import random

# For simulation post-processing
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .config import get_config, Config
from .utils.diagrams import HVACDiagramGenerator
from .utils.schedules import ScheduleValueParser
from .utils.output_variables import OutputVariableManager
from .utils.output_meters import OutputMeterManager
from .utils.people_utils import PeopleManager
from .utils.lights_utils import LightsManager
from .utils.electric_equipment_utils import ElectricEquipmentManager

logger = logging.getLogger(__name__)


class EnergyPlusManager:
    """Manager class for EnergyPlus operations using eppy with configuration management"""
    
    def __init__(self, config: Optional[Config] = None):
        """Initialize the EnergyPlus manager with configuration"""
        self.config = config or get_config()
        self._initialize_eppy()
        
        # Initialize utilities
        self.diagram_generator = HVACDiagramGenerator()
        self.output_var_manager = OutputVariableManager(self.config)
        self.output_meter_manager = OutputMeterManager(self.config)
        self.people_manager = PeopleManager()
        self.lights_manager = LightsManager()
        self.electric_equipment_manager = ElectricEquipmentManager()
        
        logger.info(f"EnergyPlus Manager initialized with IDD: {self.config.energyplus.idd_path}")
    

    def _initialize_eppy(self):
        """Initialize eppy with the IDD file from configuration"""
        idd_path = self.config.energyplus.idd_path
        
        if not idd_path:
            raise RuntimeError("EnergyPlus IDD path not configured")
        
        if not os.path.exists(idd_path):
            raise RuntimeError(f"IDD file not found at: {idd_path}")
        
        try:
            eppy.modeleditor.IDF.setiddname(idd_path)
            logger.debug(f"Eppy initialized with IDD: {idd_path}")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize eppy with IDD {idd_path}: {e}")
    

    def _resolve_idf_path(self, idf_path: str) -> str:
        """Resolve IDF path (handle relative paths, sample files, example files, etc.)"""
        from .utils.path_utils import resolve_path
        return resolve_path(self.config, idf_path, file_types=['.idf'], description="IDF file")
        
    
    def load_idf(self, idf_path: str) -> Dict[str, Any]:
        """Load an IDF file and return basic information"""
        resolved_path = self._resolve_idf_path(idf_path)
        
        try:
            logger.info(f"Loading IDF file: {resolved_path}")
            idf = IDF(resolved_path)
            
            # Get basic counts
            building_count = len(idf.idfobjects.get("Building", []))
            zone_count = len(idf.idfobjects.get("Zone", []))
            surface_count = len(idf.idfobjects.get("BuildingSurface:Detailed", []))
            material_count = len(idf.idfobjects.get("Material", [])) + len(idf.idfobjects.get("Material:NoMass", []))
            construction_count = len(idf.idfobjects.get("Construction", []))
            
            result = {
                "file_path": resolved_path,
                "original_path": idf_path,
                "building_count": building_count,
                "zone_count": zone_count,
                "surface_count": surface_count,
                "material_count": material_count,
                "construction_count": construction_count,
                "loaded_successfully": True,
                "file_size_bytes": os.path.getsize(resolved_path)
            }
            
            logger.info(f"IDF loaded successfully: {zone_count} zones, {surface_count} surfaces")
            return result
            
        except Exception as e:
            logger.error(f"Error loading IDF file {resolved_path}: {e}")
            raise RuntimeError(f"Error loading IDF file: {str(e)}")
    

    def list_available_files(self, include_example_files: bool = False, include_weather_data: bool = False) -> str:
        """List available files in specified directories
        
        Args:
            include_example_files: Whether to include EnergyPlus example files directory
            include_weather_data: Whether to include EnergyPlus weather data directory
            
        Returns:
            JSON string with available files organized by source and type
        """
        try:
            sample_path = Path(self.config.paths.sample_files_path)
            logger.debug(f"Listing files in sample_files: {sample_path}")
            
            files = {
                "sample_files": {
                    "path": str(sample_path),
                    "available": sample_path.exists(),
                    "IDF files": [],
                    "Weather files": [],
                    "Other files": []
                }
            }
            
            # Always process sample files directory
            if sample_path.exists():
                for file_path in sample_path.iterdir():
                    if file_path.is_file():
                        file_info = {
                            "name": file_path.name,
                            "size_bytes": file_path.stat().st_size,
                            "modified": file_path.stat().st_mtime,
                            "source": "sample_files"
                        }
                        
                        if file_path.suffix.lower() == '.idf':
                            files["sample_files"]["IDF files"].append(file_info)
                        elif file_path.suffix.lower() == '.epw':
                            files["sample_files"]["Weather files"].append(file_info)
                        else:
                            files["sample_files"]["Other files"].append(file_info)
            
            # Conditionally process example files directory
            if include_example_files:
                example_path = Path(self.config.energyplus.example_files_path)
                logger.debug(f"Listing files in example_files: {example_path}")
                
                files["example_files"] = {
                    "path": str(example_path),
                    "available": example_path.exists(),
                    "IDF files": [],
                    "Weather files": [],
                    "Other files": []
                }
                
                if example_path.exists():
                    for file_path in example_path.iterdir():
                        if file_path.is_file():
                            file_info = {
                                "name": file_path.name,
                                "size_bytes": file_path.stat().st_size,
                                "modified": file_path.stat().st_mtime,
                                "source": "example_files"
                            }
                            
                            if file_path.suffix.lower() == '.idf':
                                files["example_files"]["IDF files"].append(file_info)
                            elif file_path.suffix.lower() == '.epw':
                                files["example_files"]["Weather files"].append(file_info)
                            else:
                                files["example_files"]["Other files"].append(file_info)
            
            # Conditionally process weather data directory
            if include_weather_data:
                weather_path = Path(self.config.energyplus.weather_data_path)
                logger.debug(f"Listing files in weather_data: {weather_path}")
                
                files["weather_data"] = {
                    "path": str(weather_path),
                    "available": weather_path.exists(),
                    "IDF files": [],
                    "Weather files": [],
                    "Other files": []
                }
                
                if weather_path.exists():
                    for file_path in weather_path.iterdir():
                        if file_path.is_file():
                            file_info = {
                                "name": file_path.name,
                                "size_bytes": file_path.stat().st_size,
                                "modified": file_path.stat().st_mtime,
                                "source": "weather_data"
                            }
                            
                            if file_path.suffix.lower() == '.idf':
                                files["weather_data"]["IDF files"].append(file_info)
                            elif file_path.suffix.lower() == '.epw':
                                files["weather_data"]["Weather files"].append(file_info)
                            else:
                                files["weather_data"]["Other files"].append(file_info)
            
            # Sort files by name in each category for each source
            for source_key in files.keys():
                for category in ["IDF files", "Weather files", "Other files"]:
                    files[source_key][category].sort(key=lambda x: x["name"])
            
            # Log summary
            total_counts = {}
            for source_key in files.keys():
                total_idf = len(files[source_key]["IDF files"])
                total_weather = len(files[source_key]["Weather files"])
                total_counts[source_key] = {"IDF": total_idf, "Weather": total_weather}
                logger.debug(f"Found {total_idf} IDF files, {total_weather} weather files in {source_key}")
            
            return json.dumps(files, indent=2)
            
        except Exception as e:
            logger.error(f"Error listing available files: {e}")
            raise RuntimeError(f"Error listing available files: {str(e)}")
    

    def copy_file(self, source_path: str, target_path: str, overwrite: bool = False, file_types: List[str] = None) -> str:
        """
        Copy a file from source to target location with fuzzy path resolution
        
        Args:
            source_path: Source file path (can be fuzzy - relative, filename only, etc.)
            target_path: Target path for the copy (can be fuzzy - relative, filename only, etc.)
            overwrite: Whether to overwrite existing target file (default: False)
            file_types: List of acceptable file extensions (e.g., ['.idf', '.epw']). If None, accepts any file type.
        
        Returns:
            JSON string with copy operation results
        """
        try:
            logger.info(f"Copying file from '{source_path}' to '{target_path}'")
            
            # Import here to avoid circular imports
            from .utils.path_utils import resolve_path
            
            # Determine file description for error messages
            file_description = "file"
            if file_types:
                if '.idf' in file_types:
                    file_description = "IDF file"
                elif '.epw' in file_types:
                    file_description = "weather file"
                else:
                    file_description = f"file with extensions {file_types}"
            
            # Resolve source path (must exist)
            enable_fuzzy = file_types and '.epw' in file_types  # Enable fuzzy matching for weather files
            resolved_source_path = resolve_path(self.config, source_path, file_types, file_description, 
                                               must_exist=True, enable_fuzzy_weather_matching=enable_fuzzy)
            logger.debug(f"Resolved source path: {resolved_source_path}")
            
            # Resolve target path (for creation)
            resolved_target_path = resolve_path(self.config, target_path, must_exist=False, description="target file")
            logger.debug(f"Resolved target path: {resolved_target_path}")
            
            # Check if source file is readable
            if not os.access(resolved_source_path, os.R_OK):
                raise PermissionError(f"Cannot read source file: {resolved_source_path}")
            
            # Check if target already exists
            if os.path.exists(resolved_target_path) and not overwrite:
                raise FileExistsError(f"Target file already exists: {resolved_target_path}. Use overwrite=True to replace it.")
            
            # Create target directory if it doesn't exist
            target_dir = os.path.dirname(resolved_target_path)
            if target_dir:
                os.makedirs(target_dir, exist_ok=True)
                logger.debug(f"Created target directory: {target_dir}")
            
            # Get source file info before copying
            source_stat = os.stat(resolved_source_path)
            source_size = source_stat.st_size
            source_mtime = source_stat.st_mtime
            
            # Perform the copy
            import shutil
            start_time = datetime.now()
            shutil.copy2(resolved_source_path, resolved_target_path)
            end_time = datetime.now()
            copy_duration = end_time - start_time
            
            # Verify the copy
            if not os.path.exists(resolved_target_path):
                raise RuntimeError("Copy operation failed - target file not found after copy")
            
            target_stat = os.stat(resolved_target_path)
            target_size = target_stat.st_size
            
            if source_size != target_size:
                raise RuntimeError(f"Copy verification failed - size mismatch: source={source_size}, target={target_size}")
            
            # Try to validate the copied file if it's an IDF
            validation_passed = True
            validation_message = "File copied successfully"
            
            if file_types and '.idf' in file_types:
                try:
                    idf = IDF(resolved_target_path)
                    validation_message = "IDF file loads successfully"
                except Exception as e:
                    validation_passed = False
                    validation_message = f"Warning: Copied IDF file may be invalid: {str(e)}"
                    logger.warning(f"IDF validation failed for copied file: {e}")
            
            result = {
                "success": True,
                "source": {
                    "original_path": source_path,
                    "resolved_path": resolved_source_path,
                    "size_bytes": source_size,
                    "modified_time": datetime.fromtimestamp(source_mtime).isoformat()
                },
                "target": {
                    "original_path": target_path,
                    "resolved_path": resolved_target_path,
                    "size_bytes": target_size,
                    "created_time": end_time.isoformat()
                },
                "operation": {
                    "copy_duration": str(copy_duration),
                    "overwrite_used": overwrite and os.path.exists(resolved_target_path),
                    "validation_passed": validation_passed,
                    "validation_message": validation_message
                },
                "timestamp": end_time.isoformat()
            }
            
            logger.info(f"Successfully copied file: {resolved_source_path} -> {resolved_target_path}")
            return json.dumps(result, indent=2)
            
        except FileNotFoundError as e:
            logger.warning(f"Source file not found: {source_path}")
            
            # Try to provide helpful suggestions
            try:
                from .utils.path_utils import PathResolver
                resolver = PathResolver(self.config)
                suggestions = resolver.suggest_similar_paths(source_path, file_types)
                
                return json.dumps({
                    "success": False,
                    "error": "File not found",
                    "message": str(e),
                    "source_path": source_path,
                    "suggestions": suggestions[:5] if suggestions else [],
                    "timestamp": datetime.now().isoformat()
                }, indent=2)
            except Exception:
                return json.dumps({
                    "success": False,
                    "error": "File not found",
                    "message": str(e),
                    "source_path": source_path,
                    "timestamp": datetime.now().isoformat()
                }, indent=2)
        
        except FileExistsError as e:
            logger.warning(f"Target file already exists: {target_path}")
            return json.dumps({
                "success": False,
                "error": "File already exists",
                "message": str(e),
                "target_path": target_path,
                "suggestion": "Use overwrite=True to replace existing file",
                "timestamp": datetime.now().isoformat()
            }, indent=2)
        
        except PermissionError as e:
            logger.error(f"Permission error during copy: {e}")
            return json.dumps({
                "success": False,
                "error": "Permission denied",
                "message": str(e),
                "timestamp": datetime.now().isoformat()
            }, indent=2)
        
        except Exception as e:
            logger.error(f"Error copying file from {source_path} to {target_path}: {e}")
            return json.dumps({
                "success": False,
                "error": "Copy operation failed",
                "message": str(e),
                "source_path": source_path,
                "target_path": target_path,
                "timestamp": datetime.now().isoformat()
            }, indent=2)


    def get_configuration_info(self) -> str:
        """Get current configuration information"""
        try:
            config_info = {
                "energyplus": {
                    "idd_path": self.config.energyplus.idd_path,
                    "installation_path": self.config.energyplus.installation_path,
                    "executable_path": self.config.energyplus.executable_path,
                    "version": self.config.energyplus.version,
                    "weather_data_path": self.config.energyplus.weather_data_path,
                    "default_weather_file": self.config.energyplus.default_weather_file,
                    "example_files_path": self.config.energyplus.example_files_path,
                    "idd_exists": os.path.exists(self.config.energyplus.idd_path) if self.config.energyplus.idd_path else False,
                    "executable_exists": os.path.exists(self.config.energyplus.executable_path) if self.config.energyplus.executable_path else False,
                    "weather_data_exists": os.path.exists(self.config.energyplus.weather_data_path) if self.config.energyplus.weather_data_path else False,
                    "default_weather_file_exists": os.path.exists(self.config.energyplus.default_weather_file) if self.config.energyplus.default_weather_file else False,
                    "example_files_exists": os.path.exists(self.config.energyplus.example_files_path) if self.config.energyplus.example_files_path else False
                },
                "paths": {
                    "workspace_root": self.config.paths.workspace_root,
                    "sample_files_path": self.config.paths.sample_files_path,
                    "temp_dir": self.config.paths.temp_dir,
                    "output_dir": self.config.paths.output_dir
                },
                "server": {
                    "name": self.config.server.name,
                    "version": self.config.server.version,
                    "log_level": self.config.server.log_level,
                    "simulation_timeout": self.config.server.simulation_timeout,
                    "tool_timeout": self.config.server.tool_timeout
                },
                "debug_mode": self.config.debug_mode
            }
            
            return json.dumps(config_info, indent=2)
            
        except Exception as e:
            logger.error(f"Error getting configuration info: {e}")
            raise RuntimeError(f"Error getting configuration info: {str(e)}")
    
 
    def validate_idf(self, idf_path: str) -> str:
        """Validate an IDF file and return any issues found"""
        resolved_path = self._resolve_idf_path(idf_path)
        
        try:
            logger.debug(f"Validating IDF file: {resolved_path}")
            idf = IDF(resolved_path)
            
            validation_results = {
                "file_path": resolved_path,
                "is_valid": True,
                "warnings": [],
                "errors": [],
                "summary": {}
            }
            
            # Basic validation checks
            warnings = []
            errors = []
            
            # Check for required objects
            required_objects = ["Building", "Zone", "SimulationControl"]
            for obj_type in required_objects:
                objs = idf.idfobjects.get(obj_type, [])
                if not objs:
                    errors.append(f"Missing required object type: {obj_type}")
                elif len(objs) > 1 and obj_type in ["Building", "SimulationControl"]:
                    warnings.append(f"Multiple {obj_type} objects found (only one expected)")
            
            # Check for zones without surfaces
            zones = idf.idfobjects.get("Zone", [])
            surfaces = idf.idfobjects.get("BuildingSurface:Detailed", [])
            
            zone_names = {getattr(zone, 'Name', '') for zone in zones}
            surface_zones = {getattr(surface, 'Zone_Name', '') for surface in surfaces}
            
            zones_without_surfaces = zone_names - surface_zones
            if zones_without_surfaces:
                warnings.append(f"Zones without surfaces: {list(zones_without_surfaces)}")
            
            # Check for materials referenced in constructions
            constructions = idf.idfobjects.get("Construction", [])
            materials = idf.idfobjects.get("Material", []) + idf.idfobjects.get("Material:NoMass", [])
            material_names = {getattr(mat, 'Name', '') for mat in materials}
            
            for construction in constructions:
                # Check all layers in construction
                for i in range(1, 10):  # EnergyPlus supports up to 10 layers
                    layer_attr = f"Layer_{i}" if i > 1 else "Outside_Layer"
                    layer_name = getattr(construction, layer_attr, None)
                    if layer_name and layer_name not in material_names:
                        errors.append(f"Construction '{getattr(construction, 'Name', 'Unknown')}' references undefined material: {layer_name}")
            
            # Set validation status
            validation_results["warnings"] = warnings
            validation_results["errors"] = errors
            validation_results["is_valid"] = len(errors) == 0
            
            # Summary
            validation_results["summary"] = {
                "total_warnings": len(warnings),
                "total_errors": len(errors),
                "building_count": len(idf.idfobjects.get("Building", [])),
                "zone_count": len(zones),
                "surface_count": len(surfaces),
                "material_count": len(materials),
                "construction_count": len(constructions)
            }
            
            logger.debug(f"Validation completed: {len(errors)} errors, {len(warnings)} warnings")
            return json.dumps(validation_results, indent=2)
            
        except Exception as e:
            logger.error(f"Error validating IDF file {resolved_path}: {e}")
            raise RuntimeError(f"Error validating IDF file: {str(e)}")
    
    # ----------------------------- Model Inspection Methods ------------------------
    def get_model_basics(self, idf_path: str) -> str:
        """Get basic model information from Building, Site:Location, and SimulationControl"""
        resolved_path = self._resolve_idf_path(idf_path)
        
        try:
            logger.debug(f"Getting model basics for: {resolved_path}")
            idf = IDF(resolved_path)
            basics = {}
            
            # Building information
            building_objs = idf.idfobjects.get("Building", [])
            if building_objs:
                bldg = building_objs[0]
                basics["Building"] = {
                    "Name": getattr(bldg, 'Name', 'Unknown'),
                    "North Axis": getattr(bldg, 'North_Axis', 'Unknown'),
                    "Terrain": getattr(bldg, 'Terrain', 'Unknown'),
                    "Loads Convergence Tolerance": getattr(bldg, 'Loads_Convergence_Tolerance_Value', 'Unknown'),
                    "Temperature Convergence Tolerance": getattr(bldg, 'Temperature_Convergence_Tolerance_Value', 'Unknown'),
                    "Solar Distribution": getattr(bldg, 'Solar_Distribution', 'Unknown'),
                    "Max Warmup Days": getattr(bldg, 'Maximum_Number_of_Warmup_Days', 'Unknown'),
                    "Min Warmup Days": getattr(bldg, 'Minimum_Number_of_Warmup_Days', 'Unknown')
                }
            
            # Site:Location information
            site_objs = idf.idfobjects.get("Site:Location", [])
            if site_objs:
                site = site_objs[0]
                basics["Site:Location"] = {
                    "Name": getattr(site, 'Name', 'Unknown'),
                    "Latitude": getattr(site, 'Latitude', 'Unknown'),
                    "Longitude": getattr(site, 'Longitude', 'Unknown'),
                    "Time Zone": getattr(site, 'Time_Zone', 'Unknown'),
                    "Elevation": getattr(site, 'Elevation', 'Unknown')
                }
            
            # SimulationControl information
            sim_objs = idf.idfobjects.get("SimulationControl", [])
            if sim_objs:
                sim = sim_objs[0]
                basics["SimulationControl"] = {
                    "Do Zone Sizing Calculation": getattr(sim, 'Do_Zone_Sizing_Calculation', 'Unknown'),
                    "Do System Sizing Calculation": getattr(sim, 'Do_System_Sizing_Calculation', 'Unknown'),
                    "Do Plant Sizing Calculation": getattr(sim, 'Do_Plant_Sizing_Calculation', 'Unknown'),
                    "Run Simulation for Sizing Periods": getattr(sim, 'Run_Simulation_for_Sizing_Periods', 'Unknown'),
                    "Run Simulation for Weather File Run Periods": getattr(sim, 'Run_Simulation_for_Weather_File_Run_Periods', 'Unknown'),
                    "Do HVAC Sizing Simulation for Sizing Periods": getattr(sim, 'Do_HVAC_Sizing_Simulation_for_Sizing_Periods', 'Unknown'),
                    "Max Number of HVAC Sizing Simulation Passes": getattr(sim, 'Maximum_Number_of_HVAC_Sizing_Simulation_Passes', 'Unknown')
                }
            
            # Version information
            version_objs = idf.idfobjects.get("Version", [])
            if version_objs:
                version = version_objs[0]
                basics["Version"] = {
                    "Version Identifier": getattr(version, 'Version_Identifier', 'Unknown')
                }
            
            logger.debug(f"Model basics extracted for {len(basics)} sections")
            return json.dumps(basics, indent=2)
            
        except Exception as e:
            logger.error(f"Error getting model basics for {resolved_path}: {e}")
            raise RuntimeError(f"Error getting model basics: {str(e)}")
    

    def check_simulation_settings(self, idf_path: str) -> str:
        """Check SimulationControl and RunPeriod settings with modifiable fields info"""
        resolved_path = self._resolve_idf_path(idf_path)
        
        try:
            logger.debug(f"Checking simulation settings for: {resolved_path}")
            idf = IDF(resolved_path)
            
            settings_info = {
                "file_path": resolved_path,
                "SimulationControl": {
                    "current_values": {},
                    "modifiable_fields": {
                        "Do_Zone_Sizing_Calculation": "Yes/No - Controls zone sizing calculations",
                        "Do_System_Sizing_Calculation": "Yes/No - Controls system sizing calculations", 
                        "Do_Plant_Sizing_Calculation": "Yes/No - Controls plant sizing calculations",
                        "Run_Simulation_for_Sizing_Periods": "Yes/No - Run design day simulations",
                        "Run_Simulation_for_Weather_File_Run_Periods": "Yes/No - Run annual weather file simulation",
                        "Do_HVAC_Sizing_Simulation_for_Sizing_Periods": "Yes/No - Run HVAC sizing simulations",
                        "Maximum_Number_of_HVAC_Sizing_Simulation_Passes": "Integer - Max number of sizing passes (typically 1-3)"
                    }
                },
                "RunPeriod": {
                    "current_values": [],
                    "modifiable_fields": {
                        "Name": "String - Name of the run period",
                        "Begin_Month": "Integer 1-12 - Starting month",
                        "Begin_Day_of_Month": "Integer 1-31 - Starting day", 
                        "Begin_Year": "Integer - Starting year (optional)",
                        "End_Month": "Integer 1-12 - Ending month",
                        "End_Day_of_Month": "Integer 1-31 - Ending day",
                        "End_Year": "Integer - Ending year (optional)",
                        "Day_of_Week_for_Start_Day": "String - Monday/Tuesday/etc or UseWeatherFile",
                        "Use_Weather_File_Holidays_and_Special_Days": "Yes/No",
                        "Use_Weather_File_Daylight_Saving_Period": "Yes/No",
                        "Apply_Weekend_Holiday_Rule": "Yes/No",
                        "Use_Weather_File_Rain_Indicators": "Yes/No",
                        "Use_Weather_File_Snow_Indicators": "Yes/No"
                    }
                }
            }
            
            # Get current SimulationControl values
            sim_objs = idf.idfobjects.get("SimulationControl", [])
            if sim_objs:
                sim = sim_objs[0]
                settings_info["SimulationControl"]["current_values"] = {
                    "Do_Zone_Sizing_Calculation": getattr(sim, 'Do_Zone_Sizing_Calculation', 'Unknown'),
                    "Do_System_Sizing_Calculation": getattr(sim, 'Do_System_Sizing_Calculation', 'Unknown'),
                    "Do_Plant_Sizing_Calculation": getattr(sim, 'Do_Plant_Sizing_Calculation', 'Unknown'),
                    "Run_Simulation_for_Sizing_Periods": getattr(sim, 'Run_Simulation_for_Sizing_Periods', 'Unknown'),
                    "Run_Simulation_for_Weather_File_Run_Periods": getattr(sim, 'Run_Simulation_for_Weather_File_Run_Periods', 'Unknown'),
                    "Do_HVAC_Sizing_Simulation_for_Sizing_Periods": getattr(sim, 'Do_HVAC_Sizing_Simulation_for_Sizing_Periods', 'Unknown'),
                    "Maximum_Number_of_HVAC_Sizing_Simulation_Passes": getattr(sim, 'Maximum_Number_of_HVAC_Sizing_Simulation_Passes', 'Unknown')
                }
            else:
                settings_info["SimulationControl"]["error"] = "No SimulationControl object found"
            
            # Get current RunPeriod values  
            run_objs = idf.idfobjects.get("RunPeriod", [])
            for i, run_period in enumerate(run_objs):
                run_data = {
                    "index": i,
                    "Name": getattr(run_period, 'Name', 'Unknown'),
                    "Begin_Month": getattr(run_period, 'Begin_Month', 'Unknown'),
                    "Begin_Day_of_Month": getattr(run_period, 'Begin_Day_of_Month', 'Unknown'),
                    "Begin_Year": getattr(run_period, 'Begin_Year', 'Unknown'),
                    "End_Month": getattr(run_period, 'End_Month', 'Unknown'),
                    "End_Day_of_Month": getattr(run_period, 'End_Day_of_Month', 'Unknown'),
                    "End_Year": getattr(run_period, 'End_Year', 'Unknown'),
                    "Day_of_Week_for_Start_Day": getattr(run_period, 'Day_of_Week_for_Start_Day', 'Unknown'),
                    "Use_Weather_File_Holidays_and_Special_Days": getattr(run_period, 'Use_Weather_File_Holidays_and_Special_Days', 'Unknown'),
                    "Use_Weather_File_Daylight_Saving_Period": getattr(run_period, 'Use_Weather_File_Daylight_Saving_Period', 'Unknown'),
                    "Apply_Weekend_Holiday_Rule": getattr(run_period, 'Apply_Weekend_Holiday_Rule', 'Unknown'),
                    "Use_Weather_File_Rain_Indicators": getattr(run_period, 'Use_Weather_File_Rain_Indicators', 'Unknown'),
                    "Use_Weather_File_Snow_Indicators": getattr(run_period, 'Use_Weather_File_Snow_Indicators', 'Unknown')
                }
                settings_info["RunPeriod"]["current_values"].append(run_data)
            
            if not run_objs:
                settings_info["RunPeriod"]["error"] = "No RunPeriod objects found"
            
            logger.debug(f"Found {len(sim_objs)} SimulationControl and {len(run_objs)} RunPeriod objects")
            return json.dumps(settings_info, indent=2)
            
        except Exception as e:
            logger.error(f"Error checking simulation settings for {resolved_path}: {e}")
            raise RuntimeError(f"Error checking simulation settings: {str(e)}")
    
    
    def list_zones(self, idf_path: str) -> str:
        """List all zones in the model"""
        resolved_path = self._resolve_idf_path(idf_path)
        
        try:
            logger.debug(f"Listing zones for: {resolved_path}")
            idf = IDF(resolved_path)
            zones = idf.idfobjects.get("Zone", [])
            
            zone_info = []
            for i, zone in enumerate(zones):
                zone_data = {
                    "Index": i + 1,
                    "Name": getattr(zone, 'Name', 'Unknown'),
                    "Direction of Relative North": getattr(zone, 'Direction_of_Relative_North', 'Unknown'),
                    "X Origin": getattr(zone, 'X_Origin', 'Unknown'),
                    "Y Origin": getattr(zone, 'Y_Origin', 'Unknown'),
                    "Z Origin": getattr(zone, 'Z_Origin', 'Unknown'),
                    "Type": getattr(zone, 'Type', 'Unknown'),
                    "Multiplier": getattr(zone, 'Multiplier', 'Unknown'),
                    "Ceiling Height": getattr(zone, 'Ceiling_Height', 'autocalculate'),
                    "Volume": getattr(zone, 'Volume', 'autocalculate')
                }
                zone_info.append(zone_data)
            
            logger.debug(f"Found {len(zone_info)} zones")
            return json.dumps(zone_info, indent=2)
            
        except Exception as e:
            logger.error(f"Error listing zones for {resolved_path}: {e}")
            raise RuntimeError(f"Error listing zones: {str(e)}")
    

    def get_surfaces(self, idf_path: str) -> str:
        """Get detailed surface information"""
        resolved_path = self._resolve_idf_path(idf_path)
        
        try:
            logger.debug(f"Getting surfaces for: {resolved_path}")
            idf = IDF(resolved_path)
            surfaces = idf.idfobjects.get("BuildingSurface:Detailed", [])
            
            surface_info = []
            for i, surface in enumerate(surfaces):
                surface_data = {
                    "Index": i + 1,
                    "Name": getattr(surface, 'Name', 'Unknown'),
                    "Surface Type": getattr(surface, 'Surface_Type', 'Unknown'),
                    "Construction Name": getattr(surface, 'Construction_Name', 'Unknown'),
                    "Zone Name": getattr(surface, 'Zone_Name', 'Unknown'),
                    "Outside Boundary Condition": getattr(surface, 'Outside_Boundary_Condition', 'Unknown'),
                    "Sun Exposure": getattr(surface, 'Sun_Exposure', 'Unknown'),
                    "Wind Exposure": getattr(surface, 'Wind_Exposure', 'Unknown'),
                    "Number of Vertices": getattr(surface, 'Number_of_Vertices', 'Unknown')
                }
                surface_info.append(surface_data)
            
            logger.debug(f"Found {len(surface_info)} surfaces")
            return json.dumps(surface_info, indent=2)
            
        except Exception as e:
            logger.error(f"Error getting surfaces for {resolved_path}: {e}")
            raise RuntimeError(f"Error getting surfaces: {str(e)}")
    

    def get_materials(self, idf_path: str) -> str:
        """Get material information"""
        resolved_path = self._resolve_idf_path(idf_path)
        
        try:
            logger.debug(f"Getting materials for: {resolved_path}")
            idf = IDF(resolved_path)
            
            materials = []
            
            # Regular materials
            material_objs = idf.idfobjects.get("Material", [])
            for material in material_objs:
                material_data = {
                    "Type": "Material",
                    "Name": getattr(material, 'Name', 'Unknown'),
                    "Roughness": getattr(material, 'Roughness', 'Unknown'),
                    "Thickness": getattr(material, 'Thickness', 'Unknown'),
                    "Conductivity": getattr(material, 'Conductivity', 'Unknown'),
                    "Density": getattr(material, 'Density', 'Unknown'),
                    "Specific Heat": getattr(material, 'Specific_Heat', 'Unknown')
                }
                materials.append(material_data)
            
            # No-mass materials
            nomass_objs = idf.idfobjects.get("Material:NoMass", [])
            for material in nomass_objs:
                material_data = {
                    "Type": "Material:NoMass",
                    "Name": getattr(material, 'Name', 'Unknown'),
                    "Roughness": getattr(material, 'Roughness', 'Unknown'),
                    "Thermal Resistance": getattr(material, 'Thermal_Resistance', 'Unknown'),
                    "Thermal Absorptance": getattr(material, 'Thermal_Absorptance', 'Unknown'),
                    "Solar Absorptance": getattr(material, 'Solar_Absorptance', 'Unknown'),
                    "Visible Absorptance": getattr(material, 'Visible_Absorptance', 'Unknown')
                }
                materials.append(material_data)
            
            logger.debug(f"Found {len(materials)} materials")
            return json.dumps(materials, indent=2)
            
        except Exception as e:
            logger.error(f"Error getting materials for {resolved_path}: {e}")
            raise RuntimeError(f"Error getting materials: {str(e)}")
    

    def inspect_people(self, idf_path: str) -> str:
        """
        Inspect and list all People objects in the EnergyPlus model
        
        Args:
            idf_path: Path to the IDF file
        
        Returns:
            JSON string with detailed People objects information
        """
        resolved_path = self._resolve_idf_path(idf_path)
        
        try:
            logger.info(f"Inspecting People objects for: {resolved_path}")
            result = self.people_manager.get_people_objects(resolved_path)
            
            if result["success"]:
                logger.info(f"Found {result['total_people_objects']} People objects")
                return json.dumps(result, indent=2)
            else:
                raise RuntimeError(result.get("error", "Unknown error"))
                
        except Exception as e:
            logger.error(f"Error inspecting People objects for {resolved_path}: {e}")
            raise RuntimeError(f"Error inspecting People objects: {str(e)}")
    
    
    def modify_people(self, idf_path: str, modifications: List[Dict[str, Any]], 
                     output_path: Optional[str] = None) -> str:
        """
        Modify People objects in the EnergyPlus model
        
        Args:
            idf_path: Path to the input IDF file
            modifications: List of modification specifications. Each item should have:
                          - "target": "all", "zone:ZoneName", or "name:PeopleName"
                          - "field_updates": Dictionary of field names and new values
            output_path: Optional path for output file (if None, creates one with _modified suffix)
        
        Returns:
            JSON string with modification results
        """
        resolved_path = self._resolve_idf_path(idf_path)
        
        try:
            logger.info(f"Modifying People objects for: {resolved_path}")
            
            # Validate modifications first
            validation = self.people_manager.validate_people_modifications(modifications)
            if not validation["valid"]:
                return json.dumps({
                    "success": False,
                    "validation_errors": validation["errors"],
                    "input_file": resolved_path
                }, indent=2)
            
            # Determine output path
            if output_path is None:
                path_obj = Path(resolved_path)
                output_path = str(path_obj.parent / f"{path_obj.stem}_modified{path_obj.suffix}")
            
            # Apply modifications
            result = self.people_manager.modify_people_objects(
                resolved_path, modifications, output_path
            )
            
            if result["success"]:
                logger.info(f"Successfully modified People objects and saved to: {output_path}")
                return json.dumps(result, indent=2)
            else:
                raise RuntimeError(result.get("error", "Unknown error"))
                
        except Exception as e:
            logger.error(f"Error modifying People objects for {resolved_path}: {e}")
            raise RuntimeError(f"Error modifying People objects: {str(e)}")

    
    def inspect_lights(self, idf_path: str) -> str:
        """
        Inspect and list all Lights objects in the EnergyPlus model
        
        Args:
            idf_path: Path to the IDF file
        
        Returns:
            JSON string with detailed Lights objects information
        """
        resolved_path = self._resolve_idf_path(idf_path)
        
        try:
            logger.info(f"Inspecting Lights objects for: {resolved_path}")
            result = self.lights_manager.get_lights_objects(resolved_path)
            
            if result["success"]:
                logger.info(f"Found {result['total_lights_objects']} Lights objects")
                return json.dumps(result, indent=2)
            else:
                raise RuntimeError(result.get("error", "Unknown error"))
                
        except Exception as e:
            logger.error(f"Error inspecting Lights objects for {resolved_path}: {e}")
            raise RuntimeError(f"Error inspecting Lights objects: {str(e)}")
    
    
    def modify_lights(self, idf_path: str, modifications: List[Dict[str, Any]], 
                     output_path: Optional[str] = None) -> str:
        """
        Modify Lights objects in the EnergyPlus model
        
        Args:
            idf_path: Path to the input IDF file
            modifications: List of modification specifications. Each item should have:
                          - "target": "all", "zone:ZoneName", or "name:LightsName"
                          - "field_updates": Dictionary of field names and new values
            output_path: Optional path for output file (if None, creates one with _modified suffix)
        
        Returns:
            JSON string with modification results
        """
        resolved_path = self._resolve_idf_path(idf_path)
        
        try:
            logger.info(f"Modifying Lights objects for: {resolved_path}")
            
            # Validate modifications first
            validation = self.lights_manager.validate_lights_modifications(modifications)
            if not validation["valid"]:
                return json.dumps({
                    "success": False,
                    "validation_errors": validation["errors"],
                    "input_file": resolved_path
                }, indent=2)
            
            # Determine output path
            if output_path is None:
                path_obj = Path(resolved_path)
                output_path = str(path_obj.parent / f"{path_obj.stem}_modified{path_obj.suffix}")
            
            # Apply modifications
            result = self.lights_manager.modify_lights_objects(
                resolved_path, modifications, output_path
            )
            
            if result["success"]:
                logger.info(f"Successfully modified Lights objects and saved to: {output_path}")
                return json.dumps(result, indent=2)
            else:
                raise RuntimeError(result.get("error", "Unknown error"))
                
        except Exception as e:
            logger.error(f"Error modifying Lights objects for {resolved_path}: {e}")
            raise RuntimeError(f"Error modifying Lights objects: {str(e)}")

    
    def inspect_electric_equipment(self, idf_path: str) -> str:
        """
        Inspect and list all ElectricEquipment objects in the EnergyPlus model
        
        Args:
            idf_path: Path to the IDF file
        
        Returns:
            JSON string with detailed ElectricEquipment objects information
        """
        resolved_path = self._resolve_idf_path(idf_path)
        
        try:
            logger.info(f"Inspecting ElectricEquipment objects for: {resolved_path}")
            result = self.electric_equipment_manager.get_electric_equipment_objects(resolved_path)
            
            if result["success"]:
                logger.info(f"Found {result['total_electric_equipment_objects']} ElectricEquipment objects")
                return json.dumps(result, indent=2)
            else:
                raise RuntimeError(result.get("error", "Unknown error"))
                
        except Exception as e:
            logger.error(f"Error inspecting ElectricEquipment objects for {resolved_path}: {e}")
            raise RuntimeError(f"Error inspecting ElectricEquipment objects: {str(e)}")
    
    
    def modify_electric_equipment(self, idf_path: str, modifications: List[Dict[str, Any]], 
                                 output_path: Optional[str] = None) -> str:
        """
        Modify ElectricEquipment objects in the EnergyPlus model
        
        Args:
            idf_path: Path to the input IDF file
            modifications: List of modification specifications. Each item should have:
                          - "target": "all", "zone:ZoneName", or "name:ElectricEquipmentName"
                          - "field_updates": Dictionary of field names and new values
            output_path: Optional path for output file (if None, creates one with _modified suffix)
        
        Returns:
            JSON string with modification results
        """
        resolved_path = self._resolve_idf_path(idf_path)
        
        try:
            logger.info(f"Modifying ElectricEquipment objects for: {resolved_path}")
            
            # Validate modifications first
            validation = self.electric_equipment_manager.validate_electric_equipment_modifications(modifications)
            if not validation["valid"]:
                return json.dumps({
                    "success": False,
                    "validation_errors": validation["errors"],
                    "input_file": resolved_path
                }, indent=2)
            
            # Determine output path
            if output_path is None:
                path_obj = Path(resolved_path)
                output_path = str(path_obj.parent / f"{path_obj.stem}_modified{path_obj.suffix}")
            
            # Apply modifications
            result = self.electric_equipment_manager.modify_electric_equipment_objects(
                resolved_path, modifications, output_path
            )
            
            if result["success"]:
                logger.info(f"Successfully modified ElectricEquipment objects and saved to: {output_path}")
                return json.dumps(result, indent=2)
            else:
                raise RuntimeError(result.get("error", "Unknown error"))
                
        except Exception as e:
            logger.error(f"Error modifying ElectricEquipment objects for {resolved_path}: {e}")
            raise RuntimeError(f"Error modifying ElectricEquipment objects: {str(e)}")

    
    def get_output_variables(self, idf_path: str, discover_available: bool = False, run_days: int = 1) -> str:
        """
        Get output variables from the model - either configured variables or discover all available ones
        
        Args:
            idf_path: Path to the IDF file
            discover_available: If True, runs simulation to discover all available variables. 
                            If False, returns currently configured variables (default)
            run_days: Number of days to run for discovery simulation (default: 1, only used if discover_available=True)
        
        Returns:
            JSON string with output variables information
        """
        resolved_path = self._resolve_idf_path(idf_path)
        
        try:
            if discover_available:
                logger.info(f"Discovering available output variables for: {resolved_path}")
                result = self.output_var_manager.discover_available_variables(resolved_path, run_days)
            else:
                logger.debug(f"Getting configured output variables for: {resolved_path}")
                result = self.output_var_manager.get_configured_variables(resolved_path)
            
            return json.dumps(result, indent=2)
            
        except Exception as e:
            logger.error(f"Error getting output variables for {resolved_path}: {e}")
            raise RuntimeError(f"Error getting output variables: {str(e)}")


    def add_output_variables(self, idf_path: str, variables: List, 
                            validation_level: str = "moderate", 
                            allow_duplicates: bool = False,
                            output_path: Optional[str] = None) -> str:
        """
        Add output variables to an EnergyPlus IDF file with validation
        
        Args:
            idf_path: Path to the input IDF file
            variables: List of variable specifications (dicts, strings, or lists)
            validation_level: "strict", "moderate", or "lenient" 
            allow_duplicates: Whether to allow duplicate variable specifications
            output_path: Optional path for output file (auto-generated if None)
        
        Returns:
            JSON string with operation results
        """
        try:
            logger.info(f"Adding output variables to {idf_path} (validation: {validation_level})")
            
            # Resolve IDF path
            resolved_path = self._resolve_idf_path(idf_path)
            
            # Auto-resolve variable specifications to standard format
            resolved_variables = self.output_var_manager.auto_resolve_variable_specs(variables)
            
            # Validate variable specifications
            validation_report = self.output_var_manager.validate_variable_specifications(
                resolved_path, resolved_variables, validation_level
            )
            
            # Handle duplicates
            duplicate_report = self.output_var_manager.check_duplicate_variables(
                resolved_path, 
                [v["specification"] for v in validation_report["valid_variables"]], 
                allow_duplicates
            )
            
            # Determine output path
            if output_path is None:
                path_obj = Path(resolved_path)
                output_path = str(path_obj.parent / f"{path_obj.stem}_with_outputs{path_obj.suffix}")
            
            # Add variables to IDF
            addition_result = self.output_var_manager.add_variables_to_idf(
                resolved_path, duplicate_report["new_variables"], output_path
            )
            
            # Compile comprehensive result
            result = {
                "success": addition_result["success"],
                "input_file": resolved_path,
                "output_file": output_path,
                "validation_level": validation_level,
                "allow_duplicates": allow_duplicates,
                "requested_variables": len(variables),
                "resolved_variables": len(resolved_variables),
                "added_variables": addition_result["added_count"],
                "skipped_duplicates": duplicate_report["duplicates_found"],
                "validation_summary": {
                    "total_valid": len(validation_report["valid_variables"]),
                    "total_invalid": len(validation_report["invalid_variables"]),
                    "warnings_count": len(validation_report["warnings"])
                },
                "added_specifications": addition_result.get("added_variables", []),
                "performance": validation_report.get("performance", {}),
                "timestamp": datetime.now().isoformat()
            }
            
            # Include detailed validation info for strict mode or if there were errors
            if validation_level == "strict" or validation_report["invalid_variables"]:
                result["validation_details"] = validation_report
            
            # Include duplicate details if any were found
            if duplicate_report["duplicates_found"] > 0:
                result["duplicate_details"] = duplicate_report
            
            # Add error details if addition failed
            if not addition_result["success"]:
                result["addition_error"] = addition_result.get("error", "Unknown error")
            
            logger.info(f"Successfully processed output variables: {addition_result['added_count']} added")
            return json.dumps(result, indent=2)
            
        except Exception as e:
            logger.error(f"Error in add_output_variables: {e}")
            return json.dumps({
                "success": False,
                "error": str(e),
                "input_file": idf_path,
                "timestamp": datetime.now().isoformat()
            }, indent=2)

    
    def add_output_meters(self, idf_path: str, meters: List, 
                         validation_level: str = "moderate", 
                         allow_duplicates: bool = False,
                         output_path: Optional[str] = None) -> str:
        """
        Add output meters to an EnergyPlus IDF file with intelligent validation
        
        Args:
            idf_path: Path to the input IDF file
            meters: List of meter specifications. Can be:
                   - Simple strings: ["Electricity:Facility", "NaturalGas:Facility"] 
                   - [name, frequency] pairs: [["Electricity:Facility", "hourly"], ["NaturalGas:Facility", "daily"]]
                   - [name, frequency, type] triplets: [["Electricity:Facility", "hourly", "Output:Meter"]]
                   - Full specifications: [{"meter_name": "Electricity:Facility", "frequency": "hourly", "meter_type": "Output:Meter"}]
                   - Mixed formats in the same list
            validation_level: Validation strictness level:
                             - "strict": Full validation with model checking (recommended for beginners)
                             - "moderate": Basic validation with helpful warnings (default)
                             - "lenient": Minimal validation (for advanced users)
            allow_duplicates: Whether to allow duplicate output meter specifications (default: False)
            output_path: Optional path for output file (if None, creates one with _with_meters suffix)
        
        Returns:
            JSON string with detailed results including validation report, added meters, and performance metrics
            
        Examples:
            # Simple usage
            add_output_meters("model.idf", ["Electricity:Facility", "NaturalGas:Facility"])
            
            # With custom frequencies  
            add_output_meters("model.idf", [["Electricity:Facility", "daily"], ["NaturalGas:Facility", "hourly"]])
            
            # Full control with meter types
            add_output_meters("model.idf", [
                {"meter_name": "Electricity:Facility", "frequency": "hourly", "meter_type": "Output:Meter"},
                {"meter_name": "NaturalGas:Facility", "frequency": "daily", "meter_type": "Output:Meter:Cumulative"}
            ], validation_level="strict")
        """
        try:
            logger.info(f"Adding output meters to {idf_path} (validation: {validation_level})")
            
            # Resolve IDF path
            resolved_path = self._resolve_idf_path(idf_path)
            
            # Auto-resolve meter specifications to standard format
            resolved_meters = self.output_meter_manager.auto_resolve_meter_specs(meters)
            
            # Validate meter specifications
            validation_report = self.output_meter_manager.validate_meter_specifications(
                resolved_path, resolved_meters, validation_level
            )
            
            # Handle duplicates
            duplicate_report = self.output_meter_manager.check_duplicate_meters(
                resolved_path, 
                [m["specification"] for m in validation_report["valid_meters"]], 
                allow_duplicates
            )
            
            # Determine output path
            if output_path is None:
                path_obj = Path(resolved_path)
                output_path = str(path_obj.parent / f"{path_obj.stem}_with_meters{path_obj.suffix}")
            
            # Add meters to IDF
            addition_result = self.output_meter_manager.add_meters_to_idf(
                resolved_path, duplicate_report["new_meters"], output_path
            )
            
            # Compile comprehensive result
            result = {
                "success": addition_result["success"],
                "input_file": resolved_path,
                "output_file": output_path,
                "validation_level": validation_level,
                "allow_duplicates": allow_duplicates,
                "requested_meters": len(meters),
                "resolved_meters": len(resolved_meters),
                "added_meters": addition_result["added_count"],
                "skipped_duplicates": duplicate_report["duplicates_found"],
                "validation_summary": {
                    "total_valid": len(validation_report["valid_meters"]),
                    "total_invalid": len(validation_report["invalid_meters"]),
                    "warnings_count": len(validation_report["warnings"])
                },
                "added_specifications": addition_result.get("added_meters", []),
                "performance": validation_report.get("performance", {}),
                "timestamp": datetime.now().isoformat()
            }
            
            # Include detailed validation info for strict mode or if there were errors
            if validation_level == "strict" or validation_report["invalid_meters"]:
                result["validation_details"] = validation_report
            
            # Include duplicate details if any were found
            if duplicate_report["duplicates_found"] > 0:
                result["duplicate_details"] = duplicate_report
            
            # Add error details if addition failed
            if not addition_result["success"]:
                result["addition_error"] = addition_result.get("error", "Unknown error")
            
            logger.info(f"Successfully processed output meters: {addition_result['added_count']} added")
            return json.dumps(result, indent=2)
            
        except Exception as e:
            logger.error(f"Error in add_output_meters: {e}")
            return json.dumps({
                "success": False,
                "error": str(e),
                "input_file": idf_path,
                "timestamp": datetime.now().isoformat()
            }, indent=2)

    def get_output_meters(self, idf_path: str, discover_available: bool = False, run_days: int = 1) -> str:
        """
        Get output meters from the model - either configured meters or discover all available ones
        
        Args:
            idf_path: Path to the IDF file
            discover_available: If True, runs simulation to discover all available meters.
                              If False, returns currently configured meters in the IDF (default: False)
            run_days: Number of days to run for discovery simulation (default: 1)
        
        Returns:
            JSON string with meter information. When discover_available=True, includes
            all possible meters with units, frequencies, and ready-to-use Output:Meter lines.
            When discover_available=False, shows only currently configured Output:Meter objects.
        """
        resolved_path = self._resolve_idf_path(idf_path)
        
        try:
            if discover_available:
                logger.info(f"Discovering available output meters for: {resolved_path}")
                result = self.output_meter_manager.discover_available_meters(resolved_path, run_days)
            else:
                logger.debug(f"Getting configured output meters for: {resolved_path}")
                result = self.output_meter_manager.get_configured_meters(resolved_path)
            
            return json.dumps(result, indent=2)
            
        except Exception as e:
            logger.error(f"Error getting output meters for {resolved_path}: {e}")
            raise RuntimeError(f"Error getting output meters: {str(e)}")


    # ----------------------- Schedule Inspector Module ------------------------
    def inspect_schedules(self, idf_path: str, include_values: bool = False) -> str:
        """
        Inspect and inventory all schedule objects in the EnergyPlus model
        
        Args:
            idf_path: Path to the IDF file
            include_values: Whether to extract actual schedule values (default: False)
        
        Returns:
            JSON string with schedule inventory and analysis
        """
        resolved_path = self._resolve_idf_path(idf_path)
        
        try:
            logger.debug(f"Inspecting schedules for: {resolved_path} (include_values={include_values})")
            idf = IDF(resolved_path)
            
            # Define all schedule object types to inspect
            schedule_object_types = [
                "ScheduleTypeLimits",
                "Schedule:Day:Hourly", 
                "Schedule:Day:Interval",
                "Schedule:Day:List",
                "Schedule:Week:Daily",
                "Schedule:Week:Compact", 
                "Schedule:Year",
                "Schedule:Compact",
                "Schedule:Constant",
                "Schedule:File",
                "Schedule:File:Shading"
            ]
            
            schedule_inventory = {
                "file_path": resolved_path,
                "include_values": include_values,
                "summary": {
                    "total_schedule_objects": 0,
                    "schedule_types_found": [],
                    "schedule_type_limits_count": 0,
                    "day_schedules_count": 0,
                    "week_schedules_count": 0, 
                    "annual_schedules_count": 0
                },
                "schedule_type_limits": [],
                "day_schedules": [],
                "week_schedules": [],
                "annual_schedules": [],
                "other_schedules": []
            }
            
            # Inspect ScheduleTypeLimits
            schedule_type_limits = idf.idfobjects.get("ScheduleTypeLimits", [])
            for stl in schedule_type_limits:
                stl_info = {
                    "name": getattr(stl, 'Name', 'Unknown'),
                    "lower_limit": getattr(stl, 'Lower_Limit_Value', 'Not specified'),
                    "upper_limit": getattr(stl, 'Upper_Limit_Value', 'Not specified'),
                    "numeric_type": getattr(stl, 'Numeric_Type', 'Not specified'),
                    "unit_type": getattr(stl, 'Unit_Type', 'Not specified')
                }
                schedule_inventory["schedule_type_limits"].append(stl_info)
            
            # Inspect Day Schedules
            day_schedule_types = ["Schedule:Day:Hourly", "Schedule:Day:Interval", "Schedule:Day:List"]
            for day_type in day_schedule_types:
                day_schedules = idf.idfobjects.get(day_type, [])
                for day_sched in day_schedules:
                    day_info = {
                        "object_type": day_type,
                        "name": getattr(day_sched, 'Name', 'Unknown'),
                        "schedule_type_limits": getattr(day_sched, 'Schedule_Type_Limits_Name', 'Not specified')
                    }
                    
                    # Add type-specific fields
                    if day_type == "Schedule:Day:Hourly":
                        # For hourly, we could count non-zero hours, but keep simple for now
                        day_info["profile_type"] = "24 hourly values"
                    elif day_type == "Schedule:Day:Interval":
                        day_info["interpolate_to_timestep"] = getattr(day_sched, 'Interpolate_to_Timestep', 'No')
                    elif day_type == "Schedule:Day:List":
                        day_info["interpolate_to_timestep"] = getattr(day_sched, 'Interpolate_to_Timestep', 'No')
                        day_info["minutes_per_item"] = getattr(day_sched, 'Minutes_Per_Item', 'Not specified')
                    
                    # Extract values if requested
                    if include_values:
                        try:
                            values = ScheduleValueParser.parse_schedule_values(day_sched, day_type)
                            if values:
                                day_info["values"] = values
                        except Exception as e:
                            logger.warning(f"Failed to extract values for {day_info['name']}: {e}")
                            day_info["values"] = {"error": f"Value extraction failed: {str(e)}"}
                    
                    schedule_inventory["day_schedules"].append(day_info)
            
            # Inspect Week Schedules  
            week_schedule_types = ["Schedule:Week:Daily", "Schedule:Week:Compact"]
            for week_type in week_schedule_types:
                week_schedules = idf.idfobjects.get(week_type, [])
                for week_sched in week_schedules:
                    week_info = {
                        "object_type": week_type,
                        "name": getattr(week_sched, 'Name', 'Unknown')
                    }
                    
                    if week_type == "Schedule:Week:Daily":
                        # Extract day schedule references
                        day_types = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday',
                                   'Holiday', 'SummerDesignDay', 'WinterDesignDay', 'CustomDay1', 'CustomDay2']
                        day_refs = {}
                        for day_type in day_types:
                            field_name = f"{day_type}_Schedule_Day_Name"
                            day_refs[day_type] = getattr(week_sched, field_name, 'Not specified')
                        week_info["day_schedule_references"] = day_refs
                    
                    # Note: Week schedules don't have direct values, they reference day schedules
                    
                    schedule_inventory["week_schedules"].append(week_info)
            
            # Inspect Annual/Full Schedules
            annual_schedule_types = ["Schedule:Year", "Schedule:Compact", "Schedule:Constant", "Schedule:File"]
            for annual_type in annual_schedule_types:
                annual_schedules = idf.idfobjects.get(annual_type, [])
                for annual_sched in annual_schedules:
                    annual_info = {
                        "object_type": annual_type,
                        "name": getattr(annual_sched, 'Name', 'Unknown'),
                        "schedule_type_limits": getattr(annual_sched, 'Schedule_Type_Limits_Name', 'Not specified')
                    }
                    
                    # Add type-specific fields
                    if annual_type == "Schedule:Constant":
                        annual_info["hourly_value"] = getattr(annual_sched, 'Hourly_Value', 'Not specified')
                    elif annual_type == "Schedule:File":
                        annual_info["file_name"] = getattr(annual_sched, 'File_Name', 'Not specified')
                        annual_info["column_number"] = getattr(annual_sched, 'Column_Number', 'Not specified')
                        annual_info["number_of_hours"] = getattr(annual_sched, 'Number_of_Hours_of_Data', 'Not specified')
                        # Skip Schedule:File value extraction as requested
                        if include_values:
                            annual_info["values"] = {"note": "Schedule:File value extraction skipped"}
                    
                    # Extract values if requested (for Schedule:Compact and Schedule:Constant)
                    if include_values and annual_type in ["Schedule:Compact", "Schedule:Constant"]:
                        try:
                            values = ScheduleValueParser.parse_schedule_values(annual_sched, annual_type)
                            if values:
                                annual_info["values"] = values
                        except Exception as e:
                            logger.warning(f"Failed to extract values for {annual_info['name']}: {e}")
                            annual_info["values"] = {"error": f"Value extraction failed: {str(e)}"}
                    
                    schedule_inventory["annual_schedules"].append(annual_info)
            
            # Handle Schedule:File:Shading separately
            shading_schedules = idf.idfobjects.get("Schedule:File:Shading", [])
            for shading_sched in shading_schedules:
                other_info = {
                    "object_type": "Schedule:File:Shading",
                    "file_name": getattr(shading_sched, 'File_Name', 'Not specified'),
                    "purpose": "Shading schedules for exterior surfaces"
                }
                # Skip shading schedule value extraction
                if include_values:
                    other_info["values"] = {"note": "Schedule:File:Shading value extraction skipped"}
                
                schedule_inventory["other_schedules"].append(other_info)
            
            # Calculate summary statistics
            total_objects = (len(schedule_inventory["schedule_type_limits"]) + 
                            len(schedule_inventory["day_schedules"]) +
                            len(schedule_inventory["week_schedules"]) + 
                            len(schedule_inventory["annual_schedules"]) +
                            len(schedule_inventory["other_schedules"]))
            
            schedule_inventory["summary"] = {
                "total_schedule_objects": total_objects,
                "schedule_type_limits_count": len(schedule_inventory["schedule_type_limits"]),
                "day_schedules_count": len(schedule_inventory["day_schedules"]),
                "week_schedules_count": len(schedule_inventory["week_schedules"]),
                "annual_schedules_count": len(schedule_inventory["annual_schedules"]),
                "other_schedules_count": len(schedule_inventory["other_schedules"]),
                "schedule_types_found": [
                    obj_type for obj_type in schedule_object_types 
                    if len(idf.idfobjects.get(obj_type, [])) > 0
                ]
            }
            
            # Add value extraction summary if values were requested
            if include_values:
                value_extraction_summary = {
                    "schedules_with_values": 0,
                    "schedules_with_errors": 0,
                    "skipped_file_schedules": 0
                }
                
                all_schedules = (schedule_inventory["day_schedules"] + 
                               schedule_inventory["annual_schedules"] + 
                               schedule_inventory["other_schedules"])
                
                for sched in all_schedules:
                    if "values" in sched:
                        if "error" in sched["values"]:
                            value_extraction_summary["schedules_with_errors"] += 1
                        elif "note" in sched["values"]:
                            value_extraction_summary["skipped_file_schedules"] += 1
                        else:
                            value_extraction_summary["schedules_with_values"] += 1
                
                schedule_inventory["summary"]["value_extraction"] = value_extraction_summary
            
            logger.debug(f"Found {total_objects} schedule objects across {len(schedule_inventory['summary']['schedule_types_found'])} object types")
            logger.info(f"Schedule inspection for {resolved_path} completed successfully")
            return json.dumps(schedule_inventory, indent=2)
            
        except Exception as e:
            logger.error(f"Error inspecting schedules for {resolved_path}: {e}")
            raise RuntimeError(f"Error inspecting schedules: {str(e)}")




    # ------------------------ Loop Discovery and Topology ------------------------
    def discover_hvac_loops(self, idf_path: str) -> str:
        """Discover all HVAC loops (Plant, Condenser, Air) in the EnergyPlus model"""
        resolved_path = self._resolve_idf_path(idf_path)
        
        try:
            logger.debug(f"Discovering HVAC loops for: {resolved_path}")
            idf = IDF(resolved_path)
            
            hvac_info = {
                "file_path": resolved_path,
                "plant_loops": [],
                "condenser_loops": [],
                "air_loops": [],
                "summary": {
                    "total_plant_loops": 0,
                    "total_condenser_loops": 0,
                    "total_air_loops": 0,
                    "total_zones": 0
                }
            }
            
            # Discover Plant Loops
            plant_loops = idf.idfobjects.get("PlantLoop", [])
            for i, loop in enumerate(plant_loops):
                loop_info = {
                    "index": i + 1,
                    "name": getattr(loop, 'Name', 'Unknown'),
                    "fluid_type": getattr(loop, 'Fluid_Type', 'Unknown'),
                    "max_loop_flow_rate": getattr(loop, 'Maximum_Loop_Flow_Rate', 'Unknown'),
                    "min_loop_flow_rate": getattr(loop, 'Minimum_Loop_Flow_Rate', 'Unknown'),
                    "loop_inlet_node": getattr(loop, 'Plant_Side_Inlet_Node_Name', 'Unknown'),
                    "loop_outlet_node": getattr(loop, 'Plant_Side_Outlet_Node_Name', 'Unknown'),
                    "demand_inlet_node": getattr(loop, 'Demand_Side_Inlet_Node_Name', 'Unknown'),
                    "demand_outlet_node": getattr(loop, 'Demand_Side_Outlet_Node_Name', 'Unknown')
                }
                hvac_info["plant_loops"].append(loop_info)
            
            # Discover Condenser Loops
            condenser_loops = idf.idfobjects.get("CondenserLoop", [])
            for i, loop in enumerate(condenser_loops):
                loop_info = {
                    "index": i + 1,
                    "name": getattr(loop, 'Name', 'Unknown'),
                    "fluid_type": getattr(loop, 'Fluid_Type', 'Unknown'),
                    "max_loop_flow_rate": getattr(loop, 'Maximum_Loop_Flow_Rate', 'Unknown'),
                    "loop_inlet_node": getattr(loop, 'Condenser_Side_Inlet_Node_Name', 'Unknown'),
                    "loop_outlet_node": getattr(loop, 'Condenser_Side_Outlet_Node_Name', 'Unknown'),
                    "demand_inlet_node": getattr(loop, 'Demand_Side_Inlet_Node_Name', 'Unknown'),
                    "demand_outlet_node": getattr(loop, 'Demand_Side_Outlet_Node_Name', 'Unknown')
                }
                hvac_info["condenser_loops"].append(loop_info)
            
            # Discover Air Loops
            air_loops = idf.idfobjects.get("AirLoopHVAC", [])
            for i, loop in enumerate(air_loops):
                loop_info = {
                    "index": i + 1,
                    "name": getattr(loop, 'Name', 'Unknown'),
                    "supply_inlet_node": getattr(loop, 'Supply_Side_Inlet_Node_Name', 'Unknown'),
                    "supply_outlet_node": getattr(loop, 'Supply_Side_Outlet_Node_Names', 'Unknown'),
                    "demand_inlet_node": getattr(loop, 'Demand_Side_Inlet_Node_Names', 'Unknown'),
                    "demand_outlet_node": getattr(loop, 'Demand_Side_Outlet_Node_Name', 'Unknown')
                }
                hvac_info["air_loops"].append(loop_info)
            
            # Get zone count for context
            zones = idf.idfobjects.get("Zone", [])
            
            # Update summary
            hvac_info["summary"] = {
                "total_plant_loops": len(plant_loops),
                "total_condenser_loops": len(condenser_loops),
                "total_air_loops": len(air_loops),
                "total_zones": len(zones)
            }
            
            logger.debug(f"Found {len(plant_loops)} plant loops, {len(condenser_loops)} condenser loops, {len(air_loops)} air loops")
            return json.dumps(hvac_info, indent=2)
            
        except Exception as e:
            logger.error(f"Error discovering HVAC loops for {resolved_path}: {e}")
            raise RuntimeError(f"Error discovering HVAC loops: {str(e)}")


    def get_loop_topology(self, idf_path: str, loop_name: str) -> str:
        """Get detailed topology information for a specific HVAC loop"""
        resolved_path = self._resolve_idf_path(idf_path)
        
        try:
            logger.debug(f"Getting loop topology for '{loop_name}' in: {resolved_path}")
            idf = IDF(resolved_path)
            
            # Try to find the loop in different loop types
            loop_obj = None
            loop_type = None
            
            # Check PlantLoop
            plant_loops = idf.idfobjects.get("PlantLoop", [])
            for loop in plant_loops:
                if getattr(loop, 'Name', '') == loop_name:
                    loop_obj = loop
                    loop_type = "PlantLoop"
                    break
            
            # Check CondenserLoop if not found
            if not loop_obj:
                condenser_loops = idf.idfobjects.get("CondenserLoop", [])
                for loop in condenser_loops:
                    if getattr(loop, 'Name', '') == loop_name:
                        loop_obj = loop
                        loop_type = "CondenserLoop"
                        break
            
            # Check AirLoopHVAC if not found
            if not loop_obj:
                air_loops = idf.idfobjects.get("AirLoopHVAC", [])
                for loop in air_loops:
                    if getattr(loop, 'Name', '') == loop_name:
                        loop_obj = loop
                        loop_type = "AirLoopHVAC"
                        break
            
            if not loop_obj:
                raise ValueError(f"Loop '{loop_name}' not found in the IDF file")
            
            topology_info = {
                "loop_name": loop_name,
                "loop_type": loop_type,
                "supply_side": {
                    "branches": [],
                    "inlet_node": "",
                    "outlet_node": "",
                    "connector_lists": []
                },
                "demand_side": {
                    "branches": [],
                    "inlet_node": "",
                    "outlet_node": "",
                    "connector_lists": []
                }
            }
            
            # Handle AirLoopHVAC differently from Plant/Condenser loops
            if loop_type == "AirLoopHVAC":
                topology_info = self._get_airloop_topology(idf, loop_obj, loop_name)
            else:
                # Handle Plant and Condenser loops (existing logic)
                topology_info = self._get_plant_condenser_topology(idf, loop_obj, loop_type, loop_name)
            
            logger.debug(f"Topology extracted for loop '{loop_name}' of type {loop_type}")
            return json.dumps(topology_info, indent=2)
            
        except Exception as e:
            logger.error(f"Error getting loop topology for {resolved_path}: {e}")
            raise RuntimeError(f"Error getting loop topology: {str(e)}")

    def _get_airloop_topology(self, idf, loop_obj, loop_name: str) -> Dict[str, Any]:
        """Get topology information specifically for AirLoopHVAC systems"""
        
        # Debug: Print all available fields in the loop object
        logger.debug(f"Loop object fields for {loop_name}:")
        for field in dir(loop_obj):
            if not field.startswith('_'):
                try:
                    value = getattr(loop_obj, field, None)
                    if isinstance(value, str) and value.strip():
                        logger.debug(f"  {field}: {value}")
                except:
                    pass
        
        topology_info = {
            "loop_name": loop_name,
            "loop_type": "AirLoopHVAC",
            "supply_side": {
                "branches": [],
                "inlet_node": getattr(loop_obj, 'Supply_Side_Inlet_Node_Name', 'Unknown'),
                "outlet_node": getattr(loop_obj, 'Supply_Side_Outlet_Node_Names', 'Unknown'),
                "components": [],
                "supply_paths": []
            },
            "demand_side": {
                "inlet_node": getattr(loop_obj, 'Demand_Side_Inlet_Node_Names', 'Unknown'),
                "outlet_node": getattr(loop_obj, 'Demand_Side_Outlet_Node_Name', 'Unknown'),
                "zone_splitters": [],
                "zone_mixers": [],
                "return_plenums": [],
                "zone_equipment": [],
                "supply_paths": [],
                "return_paths": []
            }
        }
        
        # Get supply side branches (main equipment) - try different possible field names
        supply_branch_list_name = (
            getattr(loop_obj, 'Branch_List_Name', '') or
            getattr(loop_obj, 'Supply_Side_Branch_List_Name', '') or
            getattr(loop_obj, 'Supply_Branch_List_Name', '')
        )
        logger.debug(f"Branch list name from loop object: '{supply_branch_list_name}'")
        
        if supply_branch_list_name:
            supply_branches = self._get_branches_from_list(idf, supply_branch_list_name)
            logger.debug(f"Found {len(supply_branches)} supply branches")
            topology_info["supply_side"]["branches"] = supply_branches
            
            # Also extract components from supply branches for easier access
            components = []
            for branch in supply_branches:
                components.extend(branch.get("components", []))
            topology_info["supply_side"]["components"] = components
            logger.debug(f"Found {len(components)} supply components")
        
        # Get AirLoopHVAC:SupplyPath objects - find by matching demand inlet node
        demand_inlet_node = topology_info["demand_side"]["inlet_node"]
        logger.debug(f"Looking for supply paths with inlet node: '{demand_inlet_node}'")
        supply_paths = self._get_airloop_supply_paths_by_node(idf, demand_inlet_node)
        topology_info["demand_side"]["supply_paths"] = supply_paths
        logger.debug(f"Found {len(supply_paths)} supply paths")
        
        # Get AirLoopHVAC:ReturnPath objects - find by matching demand outlet node
        demand_outlet_node = topology_info["demand_side"]["outlet_node"]
        logger.debug(f"Looking for return paths with outlet node: '{demand_outlet_node}'")
        return_paths = self._get_airloop_return_paths_by_node(idf, demand_outlet_node)
        topology_info["demand_side"]["return_paths"] = return_paths
        logger.debug(f"Found {len(return_paths)} return paths")
        
        # Get zone splitters from supply paths
        zone_splitters = []
        for supply_path in supply_paths:
            for component in supply_path.get("components", []):
                if component["type"] == "AirLoopHVAC:ZoneSplitter":
                    splitter_details = self._get_airloop_zone_splitter_details(idf, component["name"])
                    if splitter_details:
                        zone_splitters.append(splitter_details)
        topology_info["demand_side"]["zone_splitters"] = zone_splitters
        
        # Get zone mixers from return paths
        zone_mixers = []
        return_plenums = []
        for return_path in return_paths:
            for component in return_path.get("components", []):
                if component["type"] == "AirLoopHVAC:ZoneMixer":
                    mixer_details = self._get_airloop_zone_mixer_details(idf, component["name"])
                    if mixer_details:
                        zone_mixers.append(mixer_details)
                elif component["type"] == "AirLoopHVAC:ReturnPlenum":
                    plenum_details = self._get_airloop_return_plenum_details(idf, component["name"])
                    if plenum_details:
                        return_plenums.append(plenum_details)
        topology_info["demand_side"]["zone_mixers"] = zone_mixers
        topology_info["demand_side"]["return_plenums"] = return_plenums
        
        # Get zone equipment connected to splitters
        zone_equipment = []
        for splitter in zone_splitters:
            for outlet_node in splitter.get("outlet_nodes", []):
                equipment = self._get_zone_equipment_for_node(idf, outlet_node)
                zone_equipment.extend(equipment)
        topology_info["demand_side"]["zone_equipment"] = zone_equipment
        
        return topology_info

    def _get_plant_condenser_topology(self, idf, loop_obj, loop_type: str, loop_name: str) -> Dict[str, Any]:
        """Get topology information for Plant and Condenser loops (existing logic)"""
        topology_info = {
            "loop_name": loop_name,
            "loop_type": loop_type,
            "supply_side": {
                "branches": [],
                "inlet_node": "",
                "outlet_node": "",
                "connector_lists": []
            },
            "demand_side": {
                "branches": [],
                "inlet_node": "",
                "outlet_node": "",
                "connector_lists": []
            }
        }
        
        # Get supply side information
        if loop_type in ["PlantLoop", "CondenserLoop"]:
            topology_info["supply_side"]["inlet_node"] = getattr(loop_obj, f'{loop_type.replace("Loop", "")}_Side_Inlet_Node_Name', 'Unknown')
            topology_info["supply_side"]["outlet_node"] = getattr(loop_obj, f'{loop_type.replace("Loop", "")}_Side_Outlet_Node_Name', 'Unknown')
        
        # Get demand side information
        topology_info["demand_side"]["inlet_node"] = getattr(loop_obj, 'Demand_Side_Inlet_Node_Names', 'Unknown')
        topology_info["demand_side"]["outlet_node"] = getattr(loop_obj, 'Demand_Side_Outlet_Node_Name', 'Unknown')
        
        # Get branch information
        supply_branch_list_name = getattr(loop_obj, 'Plant_Side_Branch_List_Name' if loop_type == "PlantLoop" 
                                        else 'Condenser_Side_Branch_List_Name' if loop_type == "CondenserLoop"
                                        else 'Supply_Side_Branch_List_Name', '')
        
        demand_branch_list_name = getattr(loop_obj, 'Demand_Side_Branch_List_Name', '')
        
        # Get supply side branches
        if supply_branch_list_name:
            supply_branches = self._get_branches_from_list(idf, supply_branch_list_name)
            topology_info["supply_side"]["branches"] = supply_branches
        
        # Get demand side branches
        if demand_branch_list_name:
            demand_branches = self._get_branches_from_list(idf, demand_branch_list_name)
            topology_info["demand_side"]["branches"] = demand_branches
        
        # Get connector information (splitters/mixers)
        supply_connector_list = getattr(loop_obj, 'Plant_Side_Connector_List_Name' if loop_type == "PlantLoop"
                                    else 'Condenser_Side_Connector_List_Name' if loop_type == "CondenserLoop"
                                    else 'Supply_Side_Connector_List_Name', '')
        
        demand_connector_list = getattr(loop_obj, 'Demand_Side_Connector_List_Name', '')
        
        if supply_connector_list:
            topology_info["supply_side"]["connector_lists"] = self._get_connectors_from_list(idf, supply_connector_list)
        
        if demand_connector_list:
            topology_info["demand_side"]["connector_lists"] = self._get_connectors_from_list(idf, demand_connector_list)
        
        return topology_info

    def _get_airloop_supply_paths_by_node(self, idf, inlet_node: str) -> List[Dict[str, Any]]:
        """Get AirLoopHVAC:SupplyPath objects that match the specified inlet node"""
        supply_paths = []
        
        supply_path_objs = idf.idfobjects.get("AirLoopHVAC:SupplyPath", [])
        for supply_path in supply_path_objs:
            path_inlet_node = getattr(supply_path, 'Supply_Air_Path_Inlet_Node_Name', '')
            if path_inlet_node == inlet_node:
                path_info = {
                    "name": getattr(supply_path, 'Name', 'Unknown'),
                    "inlet_node": path_inlet_node,
                    "components": []
                }
                
                # Get components in the supply path
                for i in range(1, 10):  # Supply paths can have multiple components
                    comp_type_field = f"Component_{i}_Object_Type" if i > 1 else "Component_1_Object_Type"
                    comp_name_field = f"Component_{i}_Name" if i > 1 else "Component_1_Name"
                    
                    comp_type = getattr(supply_path, comp_type_field, None)
                    comp_name = getattr(supply_path, comp_name_field, None)
                    
                    if not comp_type or not comp_name:
                        break
                    
                    component_info = {
                        "type": comp_type,
                        "name": comp_name
                    }
                    path_info["components"].append(component_info)
                
                supply_paths.append(path_info)
        
        return supply_paths

    def _get_airloop_return_paths_by_node(self, idf, outlet_node: str) -> List[Dict[str, Any]]:
        """Get AirLoopHVAC:ReturnPath objects that match the specified outlet node"""
        return_paths = []
        
        return_path_objs = idf.idfobjects.get("AirLoopHVAC:ReturnPath", [])
        for return_path in return_path_objs:
            path_outlet_node = getattr(return_path, 'Return_Air_Path_Outlet_Node_Name', '')
            if path_outlet_node == outlet_node:
                path_info = {
                    "name": getattr(return_path, 'Name', 'Unknown'),
                    "outlet_node": path_outlet_node,
                    "components": []
                }
                
                # Get components in the return path
                for i in range(1, 10):  # Return paths can have multiple components
                    comp_type_field = f"Component_{i}_Object_Type" if i > 1 else "Component_1_Object_Type"
                    comp_name_field = f"Component_{i}_Name" if i > 1 else "Component_1_Name"
                    
                    comp_type = getattr(return_path, comp_type_field, None)
                    comp_name = getattr(return_path, comp_name_field, None)
                    
                    if not comp_type or not comp_name:
                        break
                    
                    component_info = {
                        "type": comp_type,
                        "name": comp_name
                    }
                    path_info["components"].append(component_info)
                
                return_paths.append(path_info)
        
        return return_paths

    def _get_zone_equipment_for_node(self, idf, inlet_node: str) -> List[Dict[str, Any]]:
        """Get zone equipment objects connected to the specified inlet node"""
        zone_equipment = []
        
        # Check common air terminal types
        air_terminal_types = [
            "AirTerminal:SingleDuct:VAV:Reheat",
            "AirTerminal:SingleDuct:VAV:NoReheat", 
            "AirTerminal:SingleDuct:ConstantVolume:Reheat",
            "AirTerminal:SingleDuct:ConstantVolume:NoReheat",
            "AirTerminal:DualDuct:VAV",
            "AirTerminal:DualDuct:ConstantVolume"
        ]
        
        for terminal_type in air_terminal_types:
            terminals = idf.idfobjects.get(terminal_type, [])
            for terminal in terminals:
                terminal_inlet = getattr(terminal, 'Air_Inlet_Node_Name', '') or getattr(terminal, 'Air_Inlet_Node', '')
                if terminal_inlet == inlet_node:
                    equipment_info = {
                        "type": terminal_type,
                        "name": getattr(terminal, 'Name', 'Unknown'),
                        "inlet_node": terminal_inlet,
                        "outlet_node": getattr(terminal, 'Air_Outlet_Node_Name', '') or getattr(terminal, 'Air_Outlet_Node', '')
                    }
                    zone_equipment.append(equipment_info)
        
        return zone_equipment

    def _get_airloop_zone_splitter_details(self, idf, splitter_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about an AirLoopHVAC:ZoneSplitter"""
        splitter_objs = idf.idfobjects.get("AirLoopHVAC:ZoneSplitter", [])
        
        for splitter in splitter_objs:
            if getattr(splitter, 'Name', '') == splitter_name:
                splitter_info = {
                    "name": splitter_name,
                    "type": "AirLoopHVAC:ZoneSplitter",
                    "inlet_node": getattr(splitter, 'Inlet_Node_Name', 'Unknown'),
                    "outlet_nodes": []
                }
                
                # Get all outlet nodes
                for i in range(1, 50):  # Zone splitters can have many outlets
                    outlet_field = f"Outlet_{i}_Node_Name" if i > 1 else "Outlet_1_Node_Name"
                    outlet_node = getattr(splitter, outlet_field, None)
                    if not outlet_node:
                        break
                    splitter_info["outlet_nodes"].append(outlet_node)
                
                return splitter_info
        
        return None

    def _get_airloop_zone_mixer_details(self, idf, mixer_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about an AirLoopHVAC:ZoneMixer"""
        mixer_objs = idf.idfobjects.get("AirLoopHVAC:ZoneMixer", [])
        
        for mixer in mixer_objs:
            if getattr(mixer, 'Name', '') == mixer_name:
                mixer_info = {
                    "name": mixer_name,
                    "type": "AirLoopHVAC:ZoneMixer",
                    "outlet_node": getattr(mixer, 'Outlet_Node_Name', 'Unknown'),
                    "inlet_nodes": []
                }
                
                # Get all inlet nodes
                for i in range(1, 50):  # Zone mixers can have many inlets
                    inlet_field = f"Inlet_{i}_Node_Name" if i > 1 else "Inlet_1_Node_Name"
                    inlet_node = getattr(mixer, inlet_field, None)
                    if not inlet_node:
                        break
                    mixer_info["inlet_nodes"].append(inlet_node)
                
                return mixer_info
        
        return None

    def _get_airloop_return_plenum_details(self, idf, plenum_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about an AirLoopHVAC:ReturnPlenum"""
        plenum_objs = idf.idfobjects.get("AirLoopHVAC:ReturnPlenum", [])
        
        for plenum in plenum_objs:
            if getattr(plenum, 'Name', '') == plenum_name:
                plenum_info = {
                    "name": plenum_name,
                    "type": "AirLoopHVAC:ReturnPlenum",
                    "zone_name": getattr(plenum, 'Zone_Name', 'Unknown'),
                    "zone_node_name": getattr(plenum, 'Zone_Node_Name', 'Unknown'),
                    "outlet_node": getattr(plenum, 'Outlet_Node_Name', 'Unknown'),
                    "induced_air_outlet_node": getattr(plenum, 'Induced_Air_Outlet_Node_or_NodeList_Name', ''),
                    "inlet_nodes": []
                }
                
                # Get all inlet nodes
                for i in range(1, 50):  # Return plenums can have many inlets
                    inlet_field = f"Inlet_{i}_Node_Name" if i > 1 else "Inlet_1_Node_Name"
                    inlet_node = getattr(plenum, inlet_field, None)
                    if not inlet_node:
                        break
                    plenum_info["inlet_nodes"].append(inlet_node)
                
                return plenum_info
        
        return None

    def _get_zone_equipment_for_node(self, idf, node_name: str) -> List[Dict[str, Any]]:
        """Get zone equipment connected to a specific node"""
        zone_equipment = []
        
        # Common zone equipment types that might be connected to air loop nodes
        equipment_types = [
            "AirTerminal:SingleDuct:Uncontrolled",
            "AirTerminal:SingleDuct:VAV:Reheat",
            "AirTerminal:SingleDuct:VAV:NoReheat",
            "AirTerminal:SingleDuct:ConstantVolume:Reheat",
            "AirTerminal:SingleDuct:ConstantVolume:NoReheat",
            "AirTerminal:DualDuct:VAV",
            "AirTerminal:DualDuct:ConstantVolume",
            "ZoneHVAC:Baseboard:Convective:Electric",
            "ZoneHVAC:Baseboard:Convective:Water",
            "ZoneHVAC:PackagedTerminalAirConditioner",
            "ZoneHVAC:PackagedTerminalHeatPump",
            "ZoneHVAC:WindowAirConditioner",
            "ZoneHVAC:UnitHeater",
            "ZoneHVAC:UnitVentilator",
            "ZoneHVAC:EnergyRecoveryVentilator",
            "ZoneHVAC:FourPipeFanCoil",
            "ZoneHVAC:IdealLoadsAirSystem"
        ]
        
        for equipment_type in equipment_types:
            equipment_objs = idf.idfobjects.get(equipment_type, [])
            for equipment in equipment_objs:
                # Check if this equipment is connected to the node
                # Different equipment types have different field names for inlet nodes
                inlet_node = None
                if hasattr(equipment, 'Air_Inlet_Node_Name'):
                    inlet_node = getattr(equipment, 'Air_Inlet_Node_Name', None)
                elif hasattr(equipment, 'Supply_Air_Inlet_Node_Name'):
                    inlet_node = getattr(equipment, 'Supply_Air_Inlet_Node_Name', None)
                elif hasattr(equipment, 'Zone_Supply_Air_Node_Name'):
                    inlet_node = getattr(equipment, 'Zone_Supply_Air_Node_Name', None)
                
                if inlet_node == node_name:
                    equipment_info = {
                        "type": equipment_type,
                        "name": getattr(equipment, 'Name', 'Unknown'),
                        "inlet_node": inlet_node,
                        "outlet_node": getattr(equipment, 'Air_Outlet_Node_Name', 
                                             getattr(equipment, 'Zone_Air_Node_Name', 'Unknown'))
                    }
                    
                    # Add zone name if available
                    if hasattr(equipment, 'Zone_Name'):
                        equipment_info["zone_name"] = getattr(equipment, 'Zone_Name', 'Unknown')
                    
                    zone_equipment.append(equipment_info)
        
        return zone_equipment


    def visualize_loop_diagram(self, idf_path: str, loop_name: str = None, 
                            output_path: Optional[str] = None, format: str = "png", 
                            show_legend: bool = True) -> str:
        """
        Generate and save a visual diagram of HVAC loop(s) using custom topology-based approach
        
        Args:
            idf_path: Path to the IDF file
            loop_name: Optional specific loop name (if None, creates diagram for first found loop)
            output_path: Optional custom output path (if None, creates one automatically)
            format: Image format for the diagram (png, jpg, pdf, svg)
            show_legend: Whether to include legend in topology-based diagrams (default: True)
        
        Returns:
            JSON string with diagram generation results and file path
        """
        resolved_path = self._resolve_idf_path(idf_path)
        
        try:
            logger.info(f"Creating custom loop diagram for: {resolved_path}")
            
            # Determine output path
            if output_path is None:
                path_obj = Path(resolved_path)
                diagram_name = f"{path_obj.stem}_hvac_diagram" if not loop_name else f"{path_obj.stem}_{loop_name}_diagram"
                output_path = str(path_obj.parent / f"{diagram_name}.{format}")
            
            # Method 1: Use topology data for custom diagram (PRIMARY)
            try:
                result = self._create_topology_based_diagram(resolved_path, loop_name, output_path, show_legend)
                if result["success"]:
                    logger.info(f"Custom topology diagram created: {output_path}")
                    return json.dumps(result, indent=2)
            except Exception as e:
                logger.warning(f"Topology-based diagram failed: {e}. Using simplified approach.")
            
            # Method 2: Simplified diagram (LAST RESORT)
            result = self._create_simplified_diagram(resolved_path, loop_name, output_path, format)
            logger.info(f"Simplified diagram created: {output_path}")
            return json.dumps(result, indent=2)
            
        except Exception as e:
            logger.error(f"Error creating loop diagram for {resolved_path}: {e}")
            raise RuntimeError(f"Error creating loop diagram: {str(e)}")


    def _create_topology_based_diagram(self, idf_path: str, loop_name: Optional[str], 
                                     output_path: str, show_legend: bool = True) -> Dict[str, Any]:
        """
        Create diagram using topology data from get_loop_topology
        """
        # Get available loops
        loops_info = json.loads(self.discover_hvac_loops(idf_path))
        
        # Determine which loop to diagram
        target_loop = None
        if loop_name:
            # Find specific loop
            for loop_type in ['plant_loops', 'condenser_loops', 'air_loops']:
                for loop in loops_info.get(loop_type, []):
                    if loop.get('name') == loop_name:
                        target_loop = loop_name
                        break
                if target_loop:
                    break
        else:
            # Use first available loop
            for loop_type in ['plant_loops', 'condenser_loops', 'air_loops']:
                loops = loops_info.get(loop_type, [])
                if loops:
                    target_loop = loops[0].get('name')
                    break
        
        if not target_loop:
            raise ValueError("No HVAC loops found or specified loop not found")
        
        # Get detailed topology for the target loop
        topology_json = self.get_loop_topology(idf_path, target_loop)
        
        # Create custom diagram using the topology data
        result = self.diagram_generator.create_diagram_from_topology(
            topology_json, output_path, f"Custom HVAC Diagram - {target_loop}", show_legend=show_legend
        )
        
        # Add additional metadata
        result.update({
            "input_file": idf_path,
            "method": "topology_based",
            "total_loops_available": sum(len(loops_info.get(key, [])) 
                                       for key in ['plant_loops', 'condenser_loops', 'air_loops'])
        })
        
        return result
    

    def _create_simplified_diagram(self, idf_path: str, loop_name: str, 
                                output_path: str, format: str) -> Dict[str, Any]:
        """Create a simplified diagram when eppy's full functionality isn't available"""
        idf = IDF(idf_path)
        
        # Get basic loop information
        loops_info = []
        
        # Plant loops
        plant_loops = idf.idfobjects.get("PlantLoop", [])
        for loop in plant_loops:
            if not loop_name or getattr(loop, 'Name', '') == loop_name:
                loops_info.append({
                    "name": getattr(loop, 'Name', 'Unknown'),
                    "type": "PlantLoop"
                })
        
        # Create a simple matplotlib diagram
        fig, ax = plt.subplots(figsize=(10, 6))
        
        if loops_info:
            # Simple box diagram
            for i, loop_info in enumerate(loops_info):
                y_pos = len(loops_info) - i - 1
                
                # Draw supply side
                supply_box = FancyBboxPatch((0, y_pos), 3, 0.8, 
                                        boxstyle="round,pad=0.1", 
                                        facecolor='lightblue', 
                                        edgecolor='black')
                ax.add_patch(supply_box)
                ax.text(1.5, y_pos + 0.4, f"{loop_info['name']}\nSupply Side", 
                    ha='center', va='center', fontsize=10)
                
                # Draw demand side
                demand_box = FancyBboxPatch((4, y_pos), 3, 0.8, 
                                        boxstyle="round,pad=0.1", 
                                        facecolor='lightcoral', 
                                        edgecolor='black')
                ax.add_patch(demand_box)
                ax.text(5.5, y_pos + 0.4, f"{loop_info['name']}\nDemand Side", 
                    ha='center', va='center', fontsize=10)
                
                # Draw connections
                ax.arrow(3, y_pos + 0.6, 1, 0, head_width=0.1, 
                        head_length=0.1, fc='black', ec='black')
                ax.arrow(4, y_pos + 0.2, -1, 0, head_width=0.1, 
                        head_length=0.1, fc='black', ec='black')
        
        ax.set_xlim(-0.5, 7.5)
        ax.set_ylim(-0.5, len(loops_info))
        ax.set_title(f"HVAC Loops: {loop_name or 'All Loops'}")
        ax.axis('off')
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        return {
            "success": True,
            "input_file": idf_path,
            "output_file": output_path,
            "loop_name": loop_name or "all_loops",
            "format": format,
            "loops_found": len(loops_info),
            "diagram_type": "simplified"
        }        
    
    # ------------------------ Model Modification Methods ------------------------
    def modify_simulation_settings(self, idf_path: str, object_type: str, field_updates: Dict[str, Any], 
                                 run_period_index: int = 0, output_path: Optional[str] = None) -> str:
        """
        Modify SimulationControl or RunPeriod settings and save to a new file
        
        Args:
            idf_path: Path to the input IDF file
            object_type: "SimulationControl" or "RunPeriod"
            field_updates: Dictionary of field names and new values
            run_period_index: Index of RunPeriod to modify (default 0, ignored for SimulationControl)
            output_path: Path for output file (if None, creates one with _modified suffix)
        """
        resolved_path = self._resolve_idf_path(idf_path)
        
        try:
            logger.info(f"Modifying {object_type} settings for: {resolved_path}")
            idf = IDF(resolved_path)
            
            # Determine output path
            if output_path is None:
                path_obj = Path(resolved_path)
                output_path = str(path_obj.parent / f"{path_obj.stem}_modified{path_obj.suffix}")
            
            modifications_made = []
            
            if object_type == "SimulationControl":
                sim_objs = idf.idfobjects.get("SimulationControl", [])
                if not sim_objs:
                    raise ValueError("No SimulationControl object found in the IDF file")
                
                sim_obj = sim_objs[0]
                
                # Valid SimulationControl fields
                valid_fields = {
                    "Do_Zone_Sizing_Calculation", "Do_System_Sizing_Calculation", 
                    "Do_Plant_Sizing_Calculation", "Run_Simulation_for_Sizing_Periods",
                    "Run_Simulation_for_Weather_File_Run_Periods", 
                    "Do_HVAC_Sizing_Simulation_for_Sizing_Periods",
                    "Maximum_Number_of_HVAC_Sizing_Simulation_Passes"
                }
                
                for field_name, new_value in field_updates.items():
                    if field_name not in valid_fields:
                        logger.warning(f"Invalid field name for SimulationControl: {field_name}")
                        continue
                    
                    try:
                        old_value = getattr(sim_obj, field_name, "Not set")
                        setattr(sim_obj, field_name, new_value)
                        modifications_made.append({
                            "field": field_name,
                            "old_value": old_value,
                            "new_value": new_value
                        })
                        logger.debug(f"Updated {field_name}: {old_value} -> {new_value}")
                    except Exception as e:
                        logger.error(f"Error setting {field_name} to {new_value}: {e}")
            
            elif object_type == "RunPeriod":
                run_objs = idf.idfobjects.get("RunPeriod", [])
                if not run_objs:
                    raise ValueError("No RunPeriod objects found in the IDF file")
                
                if run_period_index >= len(run_objs):
                    raise ValueError(f"RunPeriod index {run_period_index} out of range (0-{len(run_objs)-1})")
                
                run_obj = run_objs[run_period_index]
                
                # Valid RunPeriod fields
                valid_fields = {
                    "Name", "Begin_Month", "Begin_Day_of_Month", "Begin_Year",
                    "End_Month", "End_Day_of_Month", "End_Year", "Day_of_Week_for_Start_Day",
                    "Use_Weather_File_Holidays_and_Special_Days", "Use_Weather_File_Daylight_Saving_Period",
                    "Apply_Weekend_Holiday_Rule", "Use_Weather_File_Rain_Indicators", 
                    "Use_Weather_File_Snow_Indicators"
                }
                
                for field_name, new_value in field_updates.items():
                    if field_name not in valid_fields:
                        logger.warning(f"Invalid field name for RunPeriod: {field_name}")
                        continue
                    
                    try:
                        old_value = getattr(run_obj, field_name, "Not set")
                        setattr(run_obj, field_name, new_value)
                        modifications_made.append({
                            "field": field_name,
                            "old_value": old_value,
                            "new_value": new_value
                        })
                        logger.debug(f"Updated {field_name}: {old_value} -> {new_value}")
                    except Exception as e:
                        logger.error(f"Error setting {field_name} to {new_value}: {e}")
            
            else:
                raise ValueError(f"Invalid object_type: {object_type}. Must be 'SimulationControl' or 'RunPeriod'")
            
            # Save the modified IDF
            idf.save(output_path)
            
            result = {
                "success": True,
                "input_file": resolved_path,
                "output_file": output_path,
                "object_type": object_type,
                "run_period_index": run_period_index if object_type == "RunPeriod" else None,
                "modifications_made": modifications_made,
                "total_modifications": len(modifications_made)
            }
            
            logger.info(f"Successfully modified {object_type} and saved to: {output_path}")
            return json.dumps(result, indent=2)
            
        except Exception as e:
            logger.error(f"Error modifying simulation settings for {resolved_path}: {e}")
            raise RuntimeError(f"Error modifying simulation settings: {str(e)}")


    def add_coating_outside(self, idf_path: str, location, solar_abs=0.4, thermal_abs=0.9, 
                            output_path: Optional[str] = None) -> str:

        """
        Add exterior coating to all exterior surfaces of the specified location (wall or roof)
        The default u_value, shgc, and visible_transmittance are from CBES

        Args:
            idf_path: Path to the input IDF file
            solar_abs: Solar Absorptance of the exterior coating
            thermal_abs: Thermal Absorptance of the exterior coating
            output_path: Path for output file (if None, creates one with _modified suffix)

        """
        resolved_path = self._resolve_idf_path(idf_path)
        
        modifications_made = []

        try:
            idf = IDF(resolved_path)
            
            # Determine output path
            if output_path is None:
                path_obj = Path(resolved_path)
                output_path = str(path_obj.parent / f"{path_obj.stem}_modified{path_obj.suffix}")
            
            all_surfs = idf.idfobjects['BuildingSurface:Detailed']
            if location.casefold() == "wall":
                all_surfs.extend(idf.idfobjects['Wall:Detailed'])
            elif location.casefold() == "roof":
                all_surfs.extend(idf.idfobjects['Roof'])
            else:
                logger.error(f"location input must be wall or roof: currently '{location}'")
            ext_surfs = [x for x in all_surfs if (x.Surface_Type.casefold() == location.casefold() and
                                                    x.Outside_Boundary_Condition.casefold() == "Outdoors".casefold())]
            if location.casefold() == "wall":
                ext_surfs.extend(idf.idfobjects['Wall:Exterior'])
            ext_surf_names = [x.Name for x in ext_surfs]

            construction_names = set([x.Construction_Name for x in ext_surfs])
            constructions = [x for x in idf.idfobjects["Construction"] if x.Name in construction_names]
            ext_layer_names = set([x.Outside_Layer for x in constructions])
            materials = idf.idfobjects['Material']
            materials.extend(idf.idfobjects['Material:NoMass'])
            ext_layers = [x for x in materials if x.Name in ext_layer_names]
            logger.debug(f"Found {len(ext_layers)} exterior layers for {location} surfaces: {ext_surf_names}")
            logger.debug("construction names: {}".format(construction_names))
            logger.debug("exterior layer names: {}".format(ext_layer_names))

            for ext_layer in ext_layers:
                try:
                    old_value = getattr(ext_layer, 'Solar_Absorptance')
                    new_value = solar_abs
                    setattr(ext_layer, 'Solar_Absorptance', new_value)
                    modifications_made.append({
                        "layer": ext_layer.Name,
                        "field": 'Solar_Absorptance',
                        "old_value": old_value,
                        "new_value": new_value
                    })
                    old_value = getattr(ext_layer, 'Thermal_Absorptance')
                    new_value = thermal_abs
                    setattr(ext_layer, 'Thermal_Absorptance', new_value)
                    modifications_made.append({
                        "layer": ext_layer.Name,
                        "field": 'Thermal_Absorptance',
                        "old_value": old_value,
                        "new_value": new_value
                    })
                except Exception as e:
                    logger.error(f"Error setting Solar and Thermal Absorptance of {ext_layer.Name}: {e}")

            # Save the modified IDF
            idf.save(output_path)
            
            result = {
                "success": True,
                "input_file": resolved_path,
                "output_file": output_path,
                "solar": solar_abs,
                "thermal": thermal_abs,
                "modifications_made": modifications_made,
                "total_modifications": len(modifications_made)
            }
            
            logger.info(f"Successfully modified exterior coating and saved to: {output_path}")
            return json.dumps(result, indent=2)
            
        except Exception as e:
            logger.error(f"Error modifying exterior coating for {resolved_path}: {e}")
            raise RuntimeError(f"Error modifying exterior coating: {str(e)}")


    def add_window_film_outside(self, idf_path: str, u_value = 4.94, shgc = 0.45, visible_transmittance = 0.66,
                                output_path: Optional[str] = None) -> str:
        """
        Use WindowMaterial:SimpleGlazingSystem to mimic the outside window film with specified U-value, SHGC, and visible transmittance
        The default u_value, shgc, and visible_transmittance are from CBES

        Args:
            idf_path: Path to the input IDF file
            u_value: U-value of the window film
            shgc: Solar Heat Gain Coefficient of the window film
            visible_transmittance: Visible transmittance of the window film
            output_path: Path for output file (if None, creates one with _modified suffix)

        """
        # helper, generate a random suffix so that the window surface name won't collide with others
        def generate_random_string(length):
            characters = string.ascii_letters + string.digits
            # Generate a random string
            random_string = ''.join(random.choices(characters, k=length))
            return random_string

        resolved_path = self._resolve_idf_path(idf_path)
        
        modifications_made = []

        try:
            idf = IDF(resolved_path)
            
            # Determine output path
            if output_path is None:
                path_obj = Path(resolved_path)
                output_path = str(path_obj.parent / f"{path_obj.stem}_modified{path_obj.suffix}")
            
            window_surfs = idf.idfobjects['FenestrationSurface:Detailed']
            window_surfs = [x for x in window_surfs if x.Surface_Type.casefold() == "Window".casefold()]
            window_surfs.extend(idf.idfobjects['Window'])
            non_window_surfs = idf.idfobjects['BuildingSurface:Detailed']
            exterior_surf_names = [x.Name for x in non_window_surfs if x.Outside_Boundary_Condition.casefold() == "Outdoors".casefold()]
            ext_window_surfs = [x for x in window_surfs if x.Building_Surface_Name in exterior_surf_names]
            logger.debug(f"exterior surfaces: {exterior_surf_names}")
            logger.debug(f"window surfaces: {[x.Name for x in window_surfs]}")
            logger.debug(f"Found {len(ext_window_surfs)} exterior window surfaces")

            # create window film object
            window_film_name = 'outside_window_film_{}'.format(generate_random_string(10))
            window_film = idf.newidfobject('WindowMaterial:SimpleGlazingSystem', Name=window_film_name)
            setattr(window_film, 'UFactor', u_value)
            setattr(window_film, 'Solar_Heat_Gain_Coefficient', shgc)
            setattr(window_film, 'Visible_Transmittance', visible_transmittance)
            logger.debug(f"create window film: {window_film_name}")

            # create window fillm construction
            window_film_construction_name = 'cons_' + window_film_name
            window_film_construction = idf.newidfobject('Construction', Name=window_film_construction_name)
            setattr(window_film_construction, 'Outside_Layer', window_film_name)
            # print("construction name: {}, outside layer: {}".format(window_film_construction_name, window_film_name))

            for surf in ext_window_surfs:
                logger.debug(f"Updating surface: {surf.Name}")
                try:
                    old_value = getattr(surf, 'Construction_Name')
                    new_value = window_film_construction_name
                    setattr(surf, 'Construction_Name', new_value)
                    modifications_made.append({
                        "surface": surf.Name,
                        "field": 'Construction_Name',
                        "old_value": old_value,
                        "new_value": new_value
                    })
                    logger.debug(f"Updated Construction_Name of {surf.Name}: {old_value} -> {new_value}")
                except Exception as e:
                    logger.error(f"Error setting Construction_Name of {surf.Name} to {new_value}: {e}")
            if (len(ext_window_surfs) > 1):
                logger.debug(f"change construction of {ext_window_surfs[0].Name} to {window_film_construction_name}")

            # Save the modified IDF
            idf.save(output_path)
            
            result = {
                "success": True,
                "input_file": resolved_path,
                "output_file": output_path,
                "u_value": u_value,
                "shgc": shgc,
                "visible_transmittance": visible_transmittance,
                "modifications_made": modifications_made,
                "total_modifications": len(modifications_made)
            }
            
            logger.info(f"Successfully modified {window_film_construction_name} and saved to: {output_path}")
            return json.dumps(result, indent=2)
            
        except Exception as e:
            logger.error(f"Error modifying window film properties for {resolved_path}: {e}")
            raise RuntimeError(f"Error modifying window film properties: {str(e)}")


    def change_infiltration_by_mult(self, idf_path: str, mult = 0.9,
                                 output_path: Optional[str] = None) -> str:
        """
        Modify infiltration rates in the IDF file by a multiplier

        Args:
            idf_path: Path to the input IDF file
            mult: multiplier for infiltration rates
            output_path: Path for output file (if None, creates one with _modified suffix)
        """
        resolved_path = self._resolve_idf_path(idf_path)
        
        modifications_made = []

        try:
            idf = IDF(resolved_path)
            
            # Determine output path
            if output_path is None:
                path_obj = Path(resolved_path)
                output_path = str(path_obj.parent / f"{path_obj.stem}_modified{path_obj.suffix}")
            
            object_type = "ZoneInfiltration:DesignFlowRate"
            infiltration_objs = idf.idfobjects[object_type]

            for i in range(len(infiltration_objs)):
                infiltration_obj = infiltration_objs[i]
                name = infiltration_obj.Name
                design_flow_method =  infiltration_obj.Design_Flow_Rate_Calculation_Method
                # print("design_flow_method is {}".format(design_flow_method))
                if design_flow_method.casefold() == "Flow/ExteriorArea".casefold(): # ignore case
                    flow_field = "Flow_Rate_per_Exterior_Surface_Area"
                elif design_flow_method.casefold() == "Flow/Area".casefold(): # ignore case
                    flow_field = "Flow_Rate_per_Floor_Area"
                elif design_flow_method.casefold() == "Flow/Zone".casefold(): # ignore case
                    flow_field = "Design_Flow_Rate"
                elif design_flow_method.casefold() == "Flow/ExteriorWallArea".casefold(): # ignore case
                    flow_field = "Flow_Rate_per_Exterior_Surface_Area"
                elif design_flow_method.casefold() == "AirChanges/Hour".casefold(): # ignore case
                    flow_field = "Air_Changes_per_Hour"
                else:
                    print("didn't find the flow rate!!!!")

                try:
                    old_value = getattr(infiltration_obj, flow_field)
                    new_value = old_value * mult
                    setattr(infiltration_obj,  flow_field, old_value * mult)
                    modifications_made.append({
                        "field": flow_field,
                        "old_value": old_value,
                        "new_value": new_value
                    })
                    logger.debug(f"Updated {flow_field}: {old_value} -> {new_value}")
                except Exception as e:
                    logger.error(f"Error setting {flow_field} to {new_value}: {e}")

            # Save the modified IDF
            idf.save(output_path)
            
            result = {
                "success": True,
                "input_file": resolved_path,
                "output_file": output_path,
                "mult": mult,
                "modifications_made": modifications_made,
                "total_modifications": len(modifications_made)
            }
            
            logger.info(f"Successfully modified {object_type} and saved to: {output_path}")
            return json.dumps(result, indent=2)
            
        except Exception as e:
            logger.error(f"Error modifying infiltration rate for {resolved_path}: {e}")
            raise RuntimeError(f"Error modifying infiltration rate: {str(e)}")
    
    
    # ------------------------ Simulation Execution ------------------------
    def run_simulation(self, idf_path: str, weather_file: str = None, 
                       output_directory: str = None, annual: bool = True,
                       design_day: bool = False, readvars: bool = True,
                       expandobjects: bool = True) -> str:
            """
            Run EnergyPlus simulation with specified IDF and weather file
            
            Args:
                idf_path: Path to the IDF file
                weather_file: Path to weather file (.epw). If None, searches for weather files in sample_files
                output_directory: Directory for simulation outputs. If None, creates one in outputs/
                annual: Run annual simulation (default: True)
                design_day: Run design day only simulation (default: False)
                readvars: Run ReadVarsESO after simulation (default: True)
                expandobjects: Run ExpandObjects prior to simulation (default: True)
            
            Returns:
                JSON string with simulation results and output file paths
            """
            resolved_idf_path = self._resolve_idf_path(idf_path)
            
            try:
                logger.info(f"Starting simulation for: {resolved_idf_path}")
                
                # Resolve weather file path
                resolved_weather_path = None
                if weather_file:
                    resolved_weather_path = self._resolve_weather_file_path(weather_file)
                    logger.info(f"Using weather file: {resolved_weather_path}")
                
                # Set up output directory
                if output_directory is None:
                    idf_name = Path(resolved_idf_path).stem
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    output_directory = str(Path(self.config.paths.output_dir) / f"{idf_name}_simulation_{timestamp}")
                
                # Create output directory if it doesn't exist
                os.makedirs(output_directory, exist_ok=True)
                logger.info(f"Output directory: {output_directory}")
                
                # Load IDF file
                if resolved_weather_path:
                    idf = IDF(resolved_idf_path, resolved_weather_path)
                else:
                    idf = IDF(resolved_idf_path)
                
                # Configure simulation options
                simulation_options = {
                    'output_directory': output_directory,
                    'annual': annual,
                    'design_day': design_day,
                    'readvars': readvars,
                    'expandobjects': expandobjects,
                    'output_prefix': Path(resolved_idf_path).stem,
                    'output_suffix': 'C',  # Capital suffix style
                    'verbose': 'v'  # Verbose output
                }
                
                # Add weather file to options if provided
                if resolved_weather_path:
                    simulation_options['weather'] = resolved_weather_path
                
                logger.info("Starting EnergyPlus simulation...")
                start_time = datetime.now()
                
                # Run the simulation
                try:
                    result = idf.run(**simulation_options)
                    end_time = datetime.now()
                    duration = end_time - start_time
                    
                    # Check for common output files
                    output_files = self._find_simulation_outputs(output_directory)
                    
                    simulation_result = {
                        "success": True,
                        "input_idf": resolved_idf_path,
                        "weather_file": resolved_weather_path,
                        "output_directory": output_directory,
                        "simulation_duration": str(duration),
                        "simulation_options": simulation_options,
                        "output_files": output_files,
                        "energyplus_result": str(result) if result else "Simulation completed",
                        "timestamp": end_time.isoformat()
                    }
                    
                    logger.info(f"Simulation completed successfully in {duration}")
                    return json.dumps(simulation_result, indent=2)
                    
                except Exception as e:
                    # Try to find error file for more detailed error information
                    error_file = Path(output_directory) / f"{Path(resolved_idf_path).stem}.err"
                    error_details = ""
                    
                    if error_file.exists():
                        try:
                            with open(error_file, 'r') as f:
                                error_details = f.read()
                        except Exception:
                            error_details = "Could not read error file"
                    
                    simulation_result = {
                        "success": False,
                        "input_idf": resolved_idf_path,
                        "weather_file": resolved_weather_path,
                        "output_directory": output_directory,
                        "error": str(e),
                        "error_details": error_details,
                        "simulation_options": simulation_options,
                        "timestamp": datetime.now().isoformat()
                    }
                    
                    logger.error(f"Simulation failed: {str(e)}")
                    return json.dumps(simulation_result, indent=2)
                    
            except Exception as e:
                logger.error(f"Error setting up simulation for {resolved_idf_path}: {e}")
                raise RuntimeError(f"Error running simulation: {str(e)}")
        

    def _resolve_weather_file_path(self, weather_file: str) -> str:
        """Resolve weather file path (handle relative paths, sample files, EnergyPlus weather data, etc.)"""
        from .utils.path_utils import resolve_path
        return resolve_path(self.config, weather_file, file_types=['.epw'], description="weather file", 
                           enable_fuzzy_weather_matching=True)
    


    

    def _find_simulation_outputs(self, output_directory: str) -> Dict[str, Any]:
        """Find and categorize simulation output files"""
        output_dir = Path(output_directory)
        if not output_dir.exists():
            return {}
        
        output_files = {
            "summary_reports": [],
            "time_series_outputs": [],
            "error_files": [],
            "other_files": []
        }
        
        # Common EnergyPlus output file patterns
        file_patterns = {
            "summary_reports": ["*Table.html", "*Table.htm", "*Table.csv", "*Summary.csv"],
            "time_series_outputs": ["*.csv", "*.eso", "*.mtr"],
            "error_files": ["*.err", "*.audit", "*.bnd"]
        }
        
        for file_path in output_dir.iterdir():
            if file_path.is_file():
                file_info = {
                    "name": file_path.name,
                    "path": str(file_path),
                    "size_bytes": file_path.stat().st_size,
                    "modified": file_path.stat().st_mtime
                }
                
                categorized = False
                for category, patterns in file_patterns.items():
                    for pattern in patterns:
                        if file_path.match(pattern):
                            output_files[category].append(file_info)
                            categorized = True
                            break
                    if categorized:
                        break
                
                if not categorized:
                    output_files["other_files"].append(file_info)
        
        return output_files

    # ------------------------ Post-Processing and Visualization ------------------------
    def create_interactive_plot(self, output_directory: str, idf_name: str = None, 
                                file_type: str = "auto", custom_title: str = None) -> str:
        """
        Create interactive HTML plot from EnergyPlus output files (meter or variable outputs)
        
        Args:
            output_directory: Directory containing the output files
            idf_name: Name of the IDF file (without extension). If None, tries to detect from directory
            file_type: "meter", "variable", or "auto" to detect automatically
            custom_title: Custom title for the plot
        
        Returns:
            JSON string with plot creation results
        """
        try:
            logger.info(f"Creating interactive plot from: {output_directory}")
            
            output_dir = Path(output_directory)
            if not output_dir.exists():
                raise FileNotFoundError(f"Output directory not found: {output_directory}")
            
            # Auto-detect IDF name if not provided
            if not idf_name:
                csv_files = list(output_dir.glob("*.csv"))
                if csv_files:
                    # Try to find the pattern
                    for csv_file in csv_files:
                        if csv_file.name.endswith("Meter.csv"):
                            idf_name = csv_file.name[:-9]  # Remove "Meter.csv"
                            break
                        elif not csv_file.name.endswith("Meter.csv"):
                            idf_name = csv_file.stem  # Remove .csv
                            break
                
                if not idf_name:
                    raise ValueError("Could not auto-detect IDF name. Please specify idf_name parameter.")
            
            # Determine which file to process
            meter_file = output_dir / f"{idf_name}Meter.csv"
            variable_file = output_dir / f"{idf_name}.csv"
            
            csv_file = None
            data_type = None
            
            if file_type == "auto":
                if meter_file.exists():
                    csv_file = meter_file
                    data_type = "Meter"
                elif variable_file.exists():
                    csv_file = variable_file  
                    data_type = "Variable"
            elif file_type == "meter":
                csv_file = meter_file
                data_type = "Meter"
            elif file_type == "variable":
                csv_file = variable_file
                data_type = "Variable"
            
            if not csv_file or not csv_file.exists():
                raise FileNotFoundError(f"Output CSV file not found. Checked: {meter_file}, {variable_file}")
            
            logger.info(f"Processing {data_type} file: {csv_file}")
            
            # Read CSV file
            df = pd.read_csv(csv_file)
            
            if df.empty:
                raise ValueError(f"CSV file is empty: {csv_file}")
            
            # Try to parse Date/Time column
            datetime_col = None
            datetime_parsed = False
            
            # Look for Date/Time column (case insensitive)
            for col in df.columns:
                if 'date' in col.lower() and 'time' in col.lower():
                    datetime_col = col
                    break
            
            if datetime_col:
                try:
                    # Try MM/DD HH:MM:SS format first
                    def parse_datetime_mmdd(dt_str):
                        try:
                            # Add current year and parse
                            current_year = datetime.now().year
                            full_dt_str = f"{current_year}/{dt_str}"
                            return pd.to_datetime(full_dt_str, format="%Y/%m/%d  %H:%M:%S")
                        except:
                            return None
                    
                    # Try monthly format
                    def parse_monthly(dt_str):
                        try:
                            dt_str = dt_str.strip()
                            if dt_str in calendar.month_name[1:]:  # Full month names
                                month_num = list(calendar.month_name).index(dt_str)
                                return pd.to_datetime(f"2023-{month_num:02d}-01")  # Use 2023 as default year
                            return None
                        except:
                            return None
                    
                    # Try to parse datetime
                    sample_value = str(df[datetime_col].iloc[0]).strip()
                    
                    if '/' in sample_value and ':' in sample_value:
                        # MM/DD HH:MM:SS format
                        df['parsed_datetime'] = df[datetime_col].apply(parse_datetime_mmdd)
                    elif sample_value in calendar.month_name[1:]:
                        # Monthly format
                        df['parsed_datetime'] = df[datetime_col].apply(parse_monthly)
                    else:
                        df['parsed_datetime'] = pd.to_datetime(df[datetime_col], errors='coerce')
                    
                    # Check if parsing was successful
                    if df['parsed_datetime'].notna().any():
                        datetime_parsed = True
                        x_values = df['parsed_datetime']
                        x_title = "Date/Time"
                        logger.info("Successfully parsed datetime column")
                    else:
                        logger.warning("DateTime parsing failed, using index")
                        
                except Exception as e:
                    logger.warning(f"DateTime parsing error: {e}, falling back to index")
            
            # Fallback to simple version if datetime parsing failed
            if not datetime_parsed:
                x_values = df.index
                x_title = "Index"
            
            # Create plotly figure
            fig = go.Figure()
            
            # Add traces for all numeric columns (except datetime)
            numeric_cols = df.select_dtypes(include=['number']).columns
            colors = ['blue', 'red', 'green', 'orange', 'purple', 'brown', 'pink', 'gray', 'olive', 'cyan']
            
            for i, col in enumerate(numeric_cols):
                if col != datetime_col:  # Skip original datetime column
                    color = colors[i % len(colors)]
                    fig.add_trace(go.Scatter(
                        x=x_values,
                        y=df[col],
                        mode='lines',
                        name=col,
                        line=dict(color=color),
                        hovertemplate=f'<b>{col}</b><br>Value: %{{y}}<br>Time: %{{x}}<extra></extra>'
                    ))
            
            # Update layout
            title = custom_title or f"EnergyPlus {data_type} Output - {idf_name}"
            fig.update_layout(
                title=dict(text=title, x=0.5),
                xaxis_title=x_title,
                yaxis_title="Value",
                hovermode='x unified',
                template='plotly_white',
                legend=dict(
                    orientation="v",
                    yanchor="top",
                    y=1,
                    xanchor="left",
                    x=1.02
                )
            )
            
            # Save as HTML
            html_filename = f"{idf_name}_{data_type.lower()}_plot.html"
            html_path = output_dir / html_filename
            
            fig.write_html(str(html_path))
            
            result = {
                "success": True,
                "input_file": str(csv_file),
                "output_file": str(html_path),
                "data_type": data_type,
                "idf_name": idf_name,
                "datetime_parsed": datetime_parsed,
                "columns_plotted": list(numeric_cols),
                "total_data_points": len(df),
                "title": title
            }
            
            logger.info(f"Interactive plot created: {html_path}")
            return json.dumps(result, indent=2)
            
        except Exception as e:
            logger.error(f"Error creating interactive plot: {e}")
            raise RuntimeError(f"Error creating interactive plot: {str(e)}")

    def _get_branches_from_list(self, idf, branch_list_name: str) -> List[Dict[str, Any]]:
        """Helper method to get branch information from a branch list"""
        branches = []
        
        branch_lists = idf.idfobjects.get("BranchList", [])
        for branch_list in branch_lists:
            if getattr(branch_list, 'Name', '') == branch_list_name:
                # Get all branch names from the list
                for i in range(1, 50):  # EnergyPlus can have many branches
                    branch_name_field = f"Branch_{i}_Name" if i > 1 else "Branch_1_Name"
                    branch_name = getattr(branch_list, branch_name_field, None)
                    if not branch_name:
                        break
                    
                    # Get detailed branch information
                    branch_info = self._get_branch_details(idf, branch_name)
                    if branch_info:
                        branches.append(branch_info)
                break
        
        return branches


    def _get_branch_details(self, idf, branch_name: str) -> Optional[Dict[str, Any]]:
        """Helper method to get detailed information about a specific branch"""
        branch_objs = idf.idfobjects.get("Branch", [])
        
        for branch in branch_objs:
            if getattr(branch, 'Name', '') == branch_name:
                branch_info = {
                    "name": branch_name,
                    "components": []
                }
                
                # Get all components in the branch
                for i in range(1, 20):  # EnergyPlus branches can have multiple components
                    comp_type_field = f"Component_{i}_Object_Type" if i > 1 else "Component_1_Object_Type"
                    comp_name_field = f"Component_{i}_Name" if i > 1 else "Component_1_Name"
                    comp_inlet_field = f"Component_{i}_Inlet_Node_Name" if i > 1 else "Component_1_Inlet_Node_Name"
                    comp_outlet_field = f"Component_{i}_Outlet_Node_Name" if i > 1 else "Component_1_Outlet_Node_Name"
                    
                    comp_type = getattr(branch, comp_type_field, None)
                    comp_name = getattr(branch, comp_name_field, None)
                    
                    if not comp_type or not comp_name:
                        break
                    
                    component_info = {
                        "type": comp_type,
                        "name": comp_name,
                        "inlet_node": getattr(branch, comp_inlet_field, 'Unknown'),
                        "outlet_node": getattr(branch, comp_outlet_field, 'Unknown')
                    }
                    branch_info["components"].append(component_info)
                
                return branch_info
        
        return None


    def _get_connectors_from_list(self, idf, connector_list_name: str) -> List[Dict[str, Any]]:
        """Helper method to get connector information (splitters/mixers) from a connector list"""
        connectors = []
        
        connector_lists = idf.idfobjects.get("ConnectorList", [])
        for connector_list in connector_lists:
            if getattr(connector_list, 'Name', '') == connector_list_name:
                # Get splitter information
                splitter_name = getattr(connector_list, 'Connector_1_Name', None)
                splitter_type = getattr(connector_list, 'Connector_1_Object_Type', None)
                
                if splitter_name and splitter_type:
                    splitter_info = self._get_connector_details(idf, splitter_name, splitter_type)
                    if splitter_info:
                        connectors.append(splitter_info)
                
                # Get mixer information
                mixer_name = getattr(connector_list, 'Connector_2_Name', None)
                mixer_type = getattr(connector_list, 'Connector_2_Object_Type', None)
                
                if mixer_name and mixer_type:
                    mixer_info = self._get_connector_details(idf, mixer_name, mixer_type)
                    if mixer_info:
                        connectors.append(mixer_info)
                
                break
        
        return connectors


    def _get_connector_details(self, idf, connector_name: str, connector_type: str) -> Optional[Dict[str, Any]]:
        """Helper method to get detailed information about splitters/mixers"""
        connector_objs = idf.idfobjects.get(connector_type, [])
        
        for connector in connector_objs:
            if getattr(connector, 'Name', '') == connector_name:
                if connector_type.lower().endswith('splitter'):
                    # For splitters: one inlet branch, multiple outlet branches
                    connector_info = {
                        "name": connector_name,
                        "type": connector_type,
                        "inlet_branch": getattr(connector, 'Inlet_Branch_Name', 'Unknown'),
                        "outlet_branches": []
                    }
                    
                    # Get outlet branches for splitters
                    for i in range(1, 20):  # Can have many outlet branches
                        branch_field = f"Outlet_Branch_{i}_Name" if i > 1 else "Outlet_Branch_1_Name"
                        branch_name = getattr(connector, branch_field, None)
                        if not branch_name:
                            break
                        connector_info["outlet_branches"].append(branch_name)
                
                else:  # mixer
                    # For mixers: multiple inlet branches, one outlet branch
                    connector_info = {
                        "name": connector_name,
                        "type": connector_type,
                        "outlet_branch": getattr(connector, 'Outlet_Branch_Name', 'Unknown'),
                        "inlet_branches": []
                    }
                    
                    # Get inlet branches for mixers
                    for i in range(1, 20):  # Can have many inlet branches
                        branch_field = f"Inlet_Branch_{i}_Name" if i > 1 else "Inlet_Branch_1_Name"
                        branch_name = getattr(connector, branch_field, None)
                        if not branch_name:
                            break
                        connector_info["inlet_branches"].append(branch_name)
                
                return connector_info
        
        return None
