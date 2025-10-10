"""
Output meters utility module for EnergyPlus MCP Server.
Handles discovery and management of EnergyPlus output meters.

EnergyPlus Model Context Protocol Server (EnergyPlus-MCP)
Copyright (c) 2025, The Regents of the University of California,
through Lawrence Berkeley National Laboratory (subject to receipt of
any required approvals from the U.S. Dept. of Energy). All rights reserved.

See License.txt in the parent directory for license details.
"""

import os
import json
import logging
import time
from typing import Dict, List, Any, Optional
from pathlib import Path
from datetime import datetime
import shutil
import re

from eppy.modeleditor import IDF

logger = logging.getLogger(__name__)


class ValidationCache:
    """Cache expensive discovery results to improve performance"""
    
    def __init__(self):
        self._available_meters_cache = {}
        self._configured_meters_cache = {}
        self._cache_timestamps = {}
    
    def get_cache_key(self, idf_path: str) -> str:
        """Generate cache key based on file path and modification time"""
        try:
            path_obj = Path(idf_path)
            if path_obj.exists():
                mtime = os.path.getmtime(idf_path)
                return f"{idf_path}:{mtime}"
            return idf_path
        except Exception:
            return idf_path
    
    def is_cache_valid(self, cache_key: str, max_age_seconds: int = 300) -> bool:
        """Check if cache entry is still valid (default: 5 minutes)"""
        if cache_key not in self._cache_timestamps:
            return False
        
        age = time.time() - self._cache_timestamps[cache_key]
        return age < max_age_seconds


class OutputMeterManager:
    """Manager for EnergyPlus output meter discovery and manipulation"""
    
    def __init__(self, config):
        """Initialize with configuration"""
        self.config = config
        self._validation_cache = ValidationCache()
        
        # Valid frequencies for EnergyPlus output meters
        self.VALID_FREQUENCIES = {
            "detailed": "Each HVAC system timestep",
            "timestep": "Each zone timestep", 
            "hourly": "Each hour",
            "daily": "Each day",
            "monthly": "Each month", 
            "runperiod": "End of run period",
            "annual": "Annual summary"
        }
        
        # Valid meter types
        self.VALID_METER_TYPES = {
            "Output:Meter": "Standard meter output",
            "Output:Meter:MeterFileOnly": "Meter output to file only (not to standard output)",
            "Output:Meter:Cumulative": "Cumulative meter values",
            "Output:Meter:Cumulative:MeterFileOnly": "Cumulative meter output to file only"
        }
    
    def get_output_meters(self, idf_path: str, discover_available: bool = False, run_days: int = 1) -> Dict[str, Any]:
        """
        Get output meters from the model - either configured meters or discover all available ones
        
        Args:
            idf_path: Path to the IDF file
            discover_available: If True, runs simulation to discover all available meters.
                              If False, returns currently configured meters in the IDF (default: False)
            run_days: Number of days to run for discovery simulation (default: 1)
        
        Returns:
            Dictionary with meter information. When discover_available=True, includes
            all possible meters with units, frequencies, and ready-to-use Output:Meter lines.
            When discover_available=False, shows only currently configured Output:Meter objects.
        """
        if discover_available:
            return self.discover_available_meters(idf_path, run_days)
        else:
            return self.get_configured_meters(idf_path)
    
    def discover_available_meters(self, idf_path: str, run_days: int = 1) -> Dict[str, Any]:
        """
        Discover all available output meters by running simulation with minimal configuration
        
        Args:
            idf_path: Path to the IDF file
            run_days: Number of days to run simulation (default: 1 for speed)
        
        Returns:
            Dictionary with discovered meters and metadata
        """
        try:
            logger.info(f"Discovering available output meters for: {idf_path}")
            
            # Create temporary modified IDF for meter discovery
            temp_idf_path = self._create_temp_idf_for_meter_discovery(idf_path, run_days)
            
            # Run short simulation
            logger.info("Running short simulation to generate meter data dictionary...")
            sim_result = self._run_meter_discovery_simulation(temp_idf_path)
            
            if not sim_result["success"]:
                return {
                    "success": False,
                    "error": "Failed to run simulation for meter discovery",
                    "simulation_error": sim_result.get("error", "Unknown error")
                }
            
            # Parse .mdd file for meters (Meter Data Dictionary)
            mdd_file_path = self._find_mdd_file(sim_result["output_directory"])
            if not mdd_file_path:
                return {
                    "success": False,
                    "error": "Could not find .mdd file in simulation output"
                }
            
            # Extract meters from .mdd file
            meters = self._parse_mdd_file_for_meters(mdd_file_path)
            
            # Clean up temporary files
            self._cleanup_temp_files(temp_idf_path, sim_result["output_directory"])
            
            result = {
                "success": True,
                "discovery_mode": True,
                "input_file": idf_path,
                "total_meters": len(meters),
                "run_days": run_days,
                "categories": self._categorize_meters(meters),
                "meters": meters
            }
            
            logger.info(f"Discovered {len(meters)} available output meters")
            return result
            
        except Exception as e:
            logger.error(f"Error discovering available output meters: {e}")
            raise RuntimeError(f"Error discovering available output meters: {str(e)}")
    
    def get_configured_meters(self, idf_path: str) -> Dict[str, Any]:
        """
        Get currently configured output meters from the IDF file
        
        Args:
            idf_path: Path to the IDF file
        
        Returns:
            Dictionary with currently configured meters
        """
        try:
            logger.debug(f"Getting configured output meters for: {idf_path}")
            idf = IDF(idf_path)
            
            output_meters = idf.idfobjects.get("Output:Meter", [])
            output_meter_fileonly = idf.idfobjects.get("Output:Meter:MeterFileOnly", [])
            output_meter_cumulative = idf.idfobjects.get("Output:Meter:Cumulative", [])
            output_meter_cumulative_fileonly = idf.idfobjects.get("Output:Meter:Cumulative:MeterFileOnly", [])
            
            meters_info = {
                "success": True,
                "discovery_mode": False,
                "input_file": idf_path,
                "output_meters": [],
                "output_meter_fileonly": [],
                "output_meter_cumulative": [],
                "output_meter_cumulative_fileonly": [],
                "summary": {
                    "total_output_meters": len(output_meters),
                    "total_output_meter_fileonly": len(output_meter_fileonly),
                    "total_output_meter_cumulative": len(output_meter_cumulative),
                    "total_output_meter_cumulative_fileonly": len(output_meter_cumulative_fileonly),
                    "total_meters": len(output_meters) + len(output_meter_fileonly) + len(output_meter_cumulative) + len(output_meter_cumulative_fileonly)
                }
            }
            
            # Process Output:Meter objects
            for meter in output_meters:
                meter_info = {
                    "key_name": getattr(meter, 'Key_Name', 'Unknown'),
                    "reporting_frequency": getattr(meter, 'Reporting_Frequency', 'Unknown'),
                    "meter_type": "Output:Meter"
                }
                meters_info["output_meters"].append(meter_info)
            
            # Process Output:Meter:MeterFileOnly objects
            for meter in output_meter_fileonly:
                meter_info = {
                    "key_name": getattr(meter, 'Key_Name', 'Unknown'),
                    "reporting_frequency": getattr(meter, 'Reporting_Frequency', 'Unknown'),
                    "meter_type": "Output:Meter:MeterFileOnly"
                }
                meters_info["output_meter_fileonly"].append(meter_info)
            
            # Process Output:Meter:Cumulative objects
            for meter in output_meter_cumulative:
                meter_info = {
                    "key_name": getattr(meter, 'Key_Name', 'Unknown'),
                    "reporting_frequency": getattr(meter, 'Reporting_Frequency', 'Unknown'),
                    "meter_type": "Output:Meter:Cumulative"
                }
                meters_info["output_meter_cumulative"].append(meter_info)
            
            # Process Output:Meter:Cumulative:MeterFileOnly objects
            for meter in output_meter_cumulative_fileonly:
                meter_info = {
                    "key_name": getattr(meter, 'Key_Name', 'Unknown'),
                    "reporting_frequency": getattr(meter, 'Reporting_Frequency', 'Unknown'),
                    "meter_type": "Output:Meter:Cumulative:MeterFileOnly"
                }
                meters_info["output_meter_cumulative_fileonly"].append(meter_info)
            
            total_configured = meters_info["summary"]["total_meters"]
            logger.debug(f"Found {total_configured} total configured meter objects")
            return meters_info
            
        except Exception as e:
            logger.error(f"Error getting configured output meters: {e}")
            raise RuntimeError(f"Error getting configured output meters: {str(e)}")
    
    def _create_temp_idf_for_meter_discovery(self, idf_path: str, run_days: int) -> str:
        """Create temporary IDF optimized for meter discovery simulation"""
        idf = IDF(idf_path)
        
        # Remove existing Output:VariableDictionary to avoid conflicts
        existing_var_dict = idf.idfobjects.get('Output:VariableDictionary', [])
        for var_dict in existing_var_dict:
            idf.removeidfobject(var_dict)
        
        # Add Output:VariableDictionary for meter discovery (IDF generates .mdd file)
        var_dict = idf.newidfobject('Output:VariableDictionary')
        var_dict.Key_Field = 'IDF'
        logger.debug(f"Added Output:VariableDictionary with Key_Field 'IDF' for meter discovery")
        
        # Modify run period to be very short for fast discovery
        run_periods = idf.idfobjects.get("RunPeriod", [])
        if run_periods:
            run_period = run_periods[0]
            # Set to run for specified days in January
            run_period.Begin_Month = 1
            run_period.Begin_Day_of_Month = 1
            run_period.End_Month = 1
            run_period.End_Day_of_Month = min(run_days, 7)  # Cap at 7 days max
            run_period.Use_Weather_File_Holidays_and_Special_Days = 'No'
            run_period.Use_Weather_File_Daylight_Saving_Period = 'No'
            run_period.Apply_Weekend_Holiday_Rule = 'No'
            run_period.Use_Weather_File_Rain_Indicators = 'No'
            run_period.Use_Weather_File_Snow_Indicators = 'No'
        
        # Disable design day simulations to speed up
        sim_control = idf.idfobjects.get("SimulationControl", [])
        if sim_control:
            control = sim_control[0]
            control.Run_Simulation_for_Sizing_Periods = 'No'
            control.Run_Simulation_for_Weather_File_Run_Periods = 'Yes'
        
        # Create temporary file
        temp_path = os.path.join(
            self.config.paths.temp_dir, 
            f"temp_meter_discovery_{datetime.now().strftime('%Y%m%d_%H%M%S')}.idf"
        )
        idf.save(temp_path)
        
        return temp_path
    
    def _run_meter_discovery_simulation(self, temp_idf_path: str) -> Dict[str, Any]:
        """Run a minimal simulation to generate the .mdd file with meter information"""
        try:
            # Create output directory
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = os.path.join(self.config.paths.temp_dir, f"meter_discovery_{timestamp}")
            os.makedirs(output_dir, exist_ok=True)
            
            # Try to find a weather file
            weather_file = None
            
            # First, check if there's a default weather file configured
            if hasattr(self.config, 'energyplus') and hasattr(self.config.energyplus, 'default_weather_file'):
                if os.path.exists(self.config.energyplus.default_weather_file):
                    weather_file = self.config.energyplus.default_weather_file
                    logger.info(f"Using configured default weather file: {weather_file}")
            
            # If no configured weather file, look for one in sample_files
            if not weather_file:
                sample_files_dir = os.path.join(os.path.dirname(temp_idf_path), '..', '..', 'sample_files')
                sample_files_dir = os.path.abspath(sample_files_dir)
                if os.path.exists(sample_files_dir):
                    epw_files = list(Path(sample_files_dir).glob('*.epw'))
                    if epw_files:
                        weather_file = str(epw_files[0])
                        logger.info(f"Using sample weather file: {weather_file}")
            
            if not weather_file:
                logger.warning("No weather file found, running design day simulation only")
            
            # Load IDF for simulation
            if weather_file and os.path.exists(weather_file):
                idf = IDF(temp_idf_path, weather_file)
            else:
                idf = IDF(temp_idf_path)
            
            # Run simulation with minimal options optimized for meter discovery
            simulation_options = {
                'output_directory': output_dir,
                'annual': False,
                'design_day': not bool(weather_file),  # Only use design day if no weather file
                'readvars': False,  # Don't need variable processing
                'expandobjects': True,  # May be needed for proper meter enumeration
                'output_prefix': 'meter_discovery',
                'output_suffix': 'C',
                'verbose': 'v'  # Minimal verbosity
            }
            
            # Add weather file to options if available
            if weather_file and os.path.exists(weather_file):
                simulation_options['weather'] = weather_file
            
            start_time = datetime.now()
            result = idf.run(**simulation_options)
            end_time = datetime.now()
            
            return {
                "success": True,
                "output_directory": output_dir,
                "duration": str(end_time - start_time),
                "weather_file": weather_file,
                "result": str(result) if result else "Completed"
            }
            
        except Exception as e:
            logger.error(f"Simulation failed during meter discovery: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def _find_mdd_file(self, output_directory: str) -> Optional[str]:
        """Find the .mdd (Meter Data Dictionary) file in the simulation output directory"""
        output_dir = Path(output_directory)
        mdd_files = list(output_dir.glob("*.mdd"))
        
        if mdd_files:
            return str(mdd_files[0])
        return None
    
    def _parse_mdd_file_for_meters(self, mdd_file_path: str) -> List[Dict[str, Any]]:
        """
        Parse the .mdd (Meter Data Dictionary) file to extract available output meters
        
        The .mdd file can have two formats:
        1. CSV format:
           Program Version,EnergyPlus, Version X.X.X, YMD=YYYY.MM.DD HH:MM,
           Var Type (reported time step),Var Report Type,Variable Name [Units]
           Zone,Meter,MeterName [Units]
           Zone,Meter,AnotherMeter [Units]
           ...
        2. Output:Meter format:
           ! Program Version,EnergyPlus, Version X.X.X, YMD=YYYY.MM.DD HH:MM,
           ! Output:Meter Objects (applicable to this run)
           Output:Meter,MeterName,hourly; !- [Units]
           Output:Meter:Cumulative,MeterName,hourly; !- [Units]
           ...
        """
        meters = []
        
        try:
            with open(mdd_file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Determine format by checking if we have Output:Meter lines
            has_output_meter_format = any(line.strip().startswith('Output:Meter') for line in lines)
            
            if has_output_meter_format:
                # Parse Output:Meter format
                meters = self._parse_output_meter_format(lines)
            else:
                # Parse CSV format
                meters = self._parse_csv_format(lines)
                
        except Exception as e:
            logger.error(f"Error reading .mdd file {mdd_file_path}: {e}")
            raise
        
        # Remove duplicates and sort by meter name
        unique_meters = {}
        for meter in meters:
            key = meter["meter_name"]
            if key not in unique_meters:
                unique_meters[key] = meter
        
        sorted_meters = sorted(unique_meters.values(), key=lambda x: x["meter_name"])
        logger.info(f"Parsed {len(sorted_meters)} unique meters from .mdd file")
        
        return sorted_meters
    
    def _parse_output_meter_format(self, lines: List[str]) -> List[Dict[str, Any]]:
        """Parse .mdd file in Output:Meter format"""
        meters = []
        
        for line in lines:
            line = line.strip()
            
            # Skip empty lines and comments
            if not line or line.startswith('!'):
                continue
            
            # Process Output:Meter lines (but not cumulative ones to avoid duplicates)
            if line.startswith('Output:Meter,') and not line.startswith('Output:Meter:Cumulative'):
                try:
                    # Parse: Output:Meter,MeterName,frequency; !- [Units]
                    # Remove the "Output:Meter," prefix
                    meter_part = line[len('Output:Meter,'):]
                    
                    # Split by comma to get meter name and frequency
                    parts = meter_part.split(',')
                    if len(parts) >= 2:
                        meter_name = parts[0].strip()
                        frequency_part = parts[1].strip()
                        
                        # Remove frequency (everything after first semicolon or before comment)
                        if ';' in frequency_part:
                            frequency = frequency_part.split(';')[0].strip()
                        else:
                            frequency = frequency_part.strip()
                        
                        # Extract units from comment if present
                        units = ""
                        if '!-' in line and '[' in line and ']' in line:
                            comment_part = line.split('!-')[1]
                            if '[' in comment_part and ']' in comment_part:
                                units_start = comment_part.find('[') + 1
                                units_end = comment_part.find(']')
                                units = comment_part[units_start:units_end].strip()
                        
                        # Skip empty meter names
                        if not meter_name:
                            continue
                        
                        # Determine resource type from meter name
                        resource_type = self._infer_resource_type(meter_name)
                        
                        meter_info = {
                            "meter_name": meter_name,
                            "units": units,
                            "resource_type": resource_type,
                            "var_type": "Zone",  # Default for this format
                            "default_frequency": frequency if frequency else "hourly",
                            "output_meter_line": f"Output:Meter,{meter_name},hourly;",
                            "output_meter_fileonly_line": f"Output:Meter:MeterFileOnly,{meter_name},hourly;",
                            "output_meter_cumulative_line": f"Output:Meter:Cumulative,{meter_name},hourly;",
                            "output_meter_cumulative_fileonly_line": f"Output:Meter:Cumulative:MeterFileOnly,{meter_name},hourly;"
                        }
                        
                        meters.append(meter_info)
                        
                except Exception as e:
                    logger.warning(f"Could not parse .mdd Output:Meter line: {line} - Error: {e}")
                    continue
        
        return meters
    
    def _parse_csv_format(self, lines: List[str]) -> List[Dict[str, Any]]:
        """Parse .mdd file in CSV format"""
        meters = []
        
        # Skip header lines and find the data
        data_started = False
        for line in lines:
            line = line.strip()
            
            # Skip empty lines
            if not line:
                continue
            
            # Skip program version line
            if line.startswith('Program Version,'):
                continue
            
            # Skip column header line
            if 'Var Type' in line and 'Var Report Type' in line and 'Variable Name' in line:
                data_started = True
                continue
            
            # Process meter data lines
            if data_started and line:
                try:
                    # Parse CSV line: Var Type, Var Report Type, Variable Name [Units]
                    parts = [part.strip() for part in line.split(',')]
                    
                    if len(parts) >= 3:
                        var_type = parts[0]  # Usually "Zone"
                        report_type = parts[1]  # Should be "Meter"
                        variable_with_units = parts[2]  # "MeterName [Units]"
                        
                        # Only process lines that are meters
                        if report_type.lower() == 'meter':
                            # Extract meter name and units
                            if '[' in variable_with_units and ']' in variable_with_units:
                                # Split on the last occurrence of '['
                                meter_name = variable_with_units.rsplit('[', 1)[0].strip()
                                units_part = variable_with_units.rsplit('[', 1)[1]
                                units = units_part.replace(']', '').strip()
                            else:
                                meter_name = variable_with_units.strip()
                                units = ""
                            
                            # Skip empty meter names
                            if not meter_name:
                                continue
                            
                            # Determine resource type from meter name
                            resource_type = self._infer_resource_type(meter_name)
                            
                            meter_info = {
                                "meter_name": meter_name,
                                "units": units,
                                "resource_type": resource_type,
                                "var_type": var_type,
                                "default_frequency": "hourly",  # Default frequency
                                "output_meter_line": f"Output:Meter,{meter_name},hourly;",
                                "output_meter_fileonly_line": f"Output:Meter:MeterFileOnly,{meter_name},hourly;",
                                "output_meter_cumulative_line": f"Output:Meter:Cumulative,{meter_name},hourly;",
                                "output_meter_cumulative_fileonly_line": f"Output:Meter:Cumulative:MeterFileOnly,{meter_name},hourly;"
                            }
                            
                            meters.append(meter_info)
                            
                except Exception as e:
                    logger.warning(f"Could not parse .mdd meter line: {line} - Error: {e}")
                    continue
        
        return meters
    
    def _infer_resource_type(self, meter_name: str) -> str:
        """Infer resource type from meter name"""
        meter_lower = meter_name.lower()
        
        if 'electricity' in meter_lower:
            return 'Electricity'
        elif 'naturalgas' in meter_lower or ':gas' in meter_lower:
            return 'NaturalGas'
        elif 'water' in meter_lower:
            if 'mains' in meter_lower:
                return 'MainsWater'
            else:
                return 'Water'
        elif 'steam' in meter_lower:
            return 'Steam'
        elif 'energytransfer' in meter_lower or 'energy transfer' in meter_lower:
            return 'EnergyTransfer'
        elif 'carbon' in meter_lower or 'co2' in meter_lower:
            return 'Carbon Equivalent'
        elif 'purchased' in meter_lower:
            return 'ElectricityPurchased'
        elif 'surplus' in meter_lower:
            return 'ElectricitySurplusSold'
        elif 'net' in meter_lower:
            return 'ElectricityNet'
        else:
            return 'Other'
    
    def _categorize_meters(self, meters: List[Dict[str, Any]]) -> Dict[str, int]:
        """Categorize meters by resource type and other characteristics"""
        categories = {}
        
        for meter in meters:
            meter_name = meter["meter_name"].lower()
            resource_type = meter.get("resource_type", "").lower()
            
            # Primary categorization by resource type
            if resource_type:
                category_key = resource_type.replace("_", " ").title()
                categories[category_key] = categories.get(category_key, 0) + 1
            
            # Secondary categorization by function/end use
            if 'facility' in meter_name:
                categories['Facility Total'] = categories.get('Facility Total', 0) + 1
            elif 'building' in meter_name:
                categories['Building Total'] = categories.get('Building Total', 0) + 1
            elif 'hvac' in meter_name:
                categories['HVAC Systems'] = categories.get('HVAC Systems', 0) + 1
            elif 'lighting' in meter_name or 'lights' in meter_name:
                categories['Lighting'] = categories.get('Lighting', 0) + 1
            elif 'heating' in meter_name:
                categories['Heating'] = categories.get('Heating', 0) + 1
            elif 'cooling' in meter_name:
                categories['Cooling'] = categories.get('Cooling', 0) + 1
            elif 'zone:' in meter_name:
                categories['Zone-Specific'] = categories.get('Zone-Specific', 0) + 1
            elif 'fans' in meter_name:
                categories['Fans'] = categories.get('Fans', 0) + 1
            elif 'pumps' in meter_name:
                categories['Pumps'] = categories.get('Pumps', 0) + 1
            elif 'plant' in meter_name:
                categories['Plant Equipment'] = categories.get('Plant Equipment', 0) + 1
            elif 'cogeneration' in meter_name:
                categories['Cogeneration'] = categories.get('Cogeneration', 0) + 1
            elif 'carbon' in meter_name or 'co2' in meter_name or 'emissions' in meter_name:
                categories['Environmental'] = categories.get('Environmental', 0) + 1
        
        return categories
    
    def _cleanup_temp_files(self, temp_idf_path: str, temp_output_dir: str):
        """Clean up temporary files and directories"""
        try:
            # Remove temporary IDF file
            if os.path.exists(temp_idf_path):
                os.remove(temp_idf_path)
                logger.debug(f"Cleaned up temporary IDF: {temp_idf_path}")
            
            # Remove temporary output directory
            if os.path.exists(temp_output_dir):
                shutil.rmtree(temp_output_dir)
                logger.debug(f"Cleaned up temporary output directory: {temp_output_dir}")
        
        except Exception as e:
            logger.warning(f"Error cleaning up temporary files: {e}")
    
    def _get_available_meters_cached(self, idf_path: str, force_refresh: bool = False) -> List[Dict]:
        """Get available meters using discovery tool with intelligent caching"""
        cache_key = self._validation_cache.get_cache_key(idf_path)
        
        # Check cache first
        if (not force_refresh and 
            cache_key in self._validation_cache._available_meters_cache and
            self._validation_cache.is_cache_valid(cache_key)):
            
            logger.debug(f"Using cached available meters for {idf_path}")
            return self._validation_cache._available_meters_cache[cache_key]
        
        logger.info(f"Discovering available meters for validation: {idf_path}")
        
        try:
            # Use existing discovery method
            discovery_result = self.discover_available_meters(idf_path, run_days=1)
            
            if discovery_result.get("success"):
                available_meters = discovery_result.get("meters", [])
                # Cache the results
                self._validation_cache._available_meters_cache[cache_key] = available_meters
                self._validation_cache._cache_timestamps[cache_key] = time.time()
                logger.info(f"Cached {len(available_meters)} available meters")
                return available_meters
            else:
                logger.warning(f"Failed to discover available meters: {discovery_result.get('error')}")
                return []
                
        except Exception as e:
            logger.error(f"Error during meter discovery: {e}")
            return []
    
    def _get_configured_meters_cached(self, idf_path: str) -> List[Dict]:
        """Get currently configured meters with caching"""
        cache_key = self._validation_cache.get_cache_key(idf_path)
        
        # Check cache first
        if (cache_key in self._validation_cache._configured_meters_cache and
            self._validation_cache.is_cache_valid(cache_key)):
            return self._validation_cache._configured_meters_cache[cache_key]
        
        try:
            # Use existing method
            configured_result = self.get_configured_meters(idf_path)
            
            if configured_result.get("success"):
                # Flatten all meter types into one list for easier caching
                all_configured_meters = []
                for meter_type_key in ["output_meters", "output_meter_fileonly", 
                                     "output_meter_cumulative", "output_meter_cumulative_fileonly"]:
                    meters = configured_result.get(meter_type_key, [])
                    for meter in meters:
                        meter["meter_type"] = meter.get("meter_type", meter_type_key)
                        all_configured_meters.append(meter)
                
                # Cache the results
                self._validation_cache._configured_meters_cache[cache_key] = all_configured_meters
                self._validation_cache._cache_timestamps[cache_key] = time.time()
                return all_configured_meters
            else:
                return []
                
        except Exception as e:
            logger.error(f"Error getting configured meters: {e}")
            return []
    
    def auto_resolve_meter_specs(self, meters: List) -> List[Dict]:
        """Convert various input formats to standardized meter specifications"""
        resolved = []
        
        for meter_spec in meters:
            if isinstance(meter_spec, str):
                # Simple string -> full specification
                resolved.append({
                    "meter_name": meter_spec,
                    "frequency": "hourly",
                    "meter_type": "Output:Meter"
                })
            elif isinstance(meter_spec, list) and len(meter_spec) >= 2:
                # [meter_name, frequency] -> full specification
                meter_type = "Output:Meter"
                if len(meter_spec) >= 3:
                    meter_type = meter_spec[2]
                resolved.append({
                    "meter_name": meter_spec[0],
                    "frequency": meter_spec[1],
                    "meter_type": meter_type
                })
            elif isinstance(meter_spec, dict):
                # Already a dict, ensure required fields
                spec = {
                    "meter_name": meter_spec.get("meter_name", ""),
                    "frequency": meter_spec.get("frequency", "hourly"),
                    "meter_type": meter_spec.get("meter_type", "Output:Meter")
                }
                resolved.append(spec)
            else:
                logger.warning(f"Invalid meter specification format: {meter_spec}")
                continue
        
        return resolved
    
    def validate_frequency(self, frequency: str) -> Dict[str, Any]:
        """Validate reporting frequency against EnergyPlus specifications"""
        if not frequency or not isinstance(frequency, str):
            return {
                "is_valid": False,
                "error": "Frequency must be a non-empty string",
                "valid_options": list(self.VALID_FREQUENCIES.keys())
            }
        
        freq_lower = frequency.lower().strip()
        
        if freq_lower in self.VALID_FREQUENCIES:
            return {
                "is_valid": True,
                "normalized": freq_lower,
                "description": self.VALID_FREQUENCIES[freq_lower]
            }
        else:
            # Try to find close matches
            from difflib import get_close_matches
            suggestions = get_close_matches(freq_lower, self.VALID_FREQUENCIES.keys(), n=3, cutoff=0.6)
            return {
                "is_valid": False,
                "error": f"Invalid frequency '{frequency}'",
                "valid_options": list(self.VALID_FREQUENCIES.keys()),
                "suggestions": suggestions
            }
    
    def validate_meter_type(self, meter_type: str) -> Dict[str, Any]:
        """Validate meter type against EnergyPlus specifications"""
        if not meter_type or not isinstance(meter_type, str):
            return {
                "is_valid": False,
                "error": "Meter type must be a non-empty string",
                "valid_options": list(self.VALID_METER_TYPES.keys())
            }
        
        if meter_type in self.VALID_METER_TYPES:
            return {
                "is_valid": True,
                "description": self.VALID_METER_TYPES[meter_type]
            }
        else:
            # Try to find close matches
            from difflib import get_close_matches
            suggestions = get_close_matches(meter_type, self.VALID_METER_TYPES.keys(), n=3, cutoff=0.6)
            return {
                "is_valid": False,
                "error": f"Invalid meter type '{meter_type}'",
                "valid_options": list(self.VALID_METER_TYPES.keys()),
                "suggestions": suggestions
            }
    
    def validate_meter_name(self, idf_path: str, meter_name: str, 
                           available_meters: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """Validate meter name against available meters in the model"""
        if not meter_name or not isinstance(meter_name, str):
            return {
                "is_valid": False,
                "error": "Meter name must be a non-empty string"
            }
        
        # Get available meters if not provided (using cached method)
        if available_meters is None:
            available_meters = self._get_available_meters_cached(idf_path)
            
            if not available_meters:
                # If discovery fails, skip detailed validation
                return {
                    "is_valid": True,
                    "note": "Meter name validation skipped (discovery failed)"
                }
        
        available_names = {meter["meter_name"] for meter in available_meters}
        meter_lookup = {meter["meter_name"]: meter for meter in available_meters}
        
        if meter_name in available_names:
            return {
                "is_valid": True,
                "metadata": meter_lookup[meter_name]
            }
        else:
            result = {
                "is_valid": False,
                "error": f"Meter '{meter_name}' not available in this model"
            }
            
            # Find similar meter names
            from difflib import get_close_matches
            suggestions = get_close_matches(meter_name, available_names, n=5, cutoff=0.6)
            if suggestions:
                result["suggestions"] = suggestions
            
            return result
    
    def validate_meter_specifications(self, idf_path: str, meters: List[Dict], 
                                     validation_level: str = "moderate") -> Dict[str, Any]:
        """Validate a batch of meter specifications"""
        import time
        start_time = time.time()
        
        validation_report = {
            "total_requested": len(meters),
            "validation_level": validation_level,
            "valid_meters": [],
            "invalid_meters": [],
            "warnings": [],
            "performance": {}
        }
        
        # Get available meters for validation (only for strict/moderate, using cache)
        available_meters = []
        if validation_level in ["strict", "moderate"]:
            available_meters = self._get_available_meters_cached(idf_path)
            if available_meters:
                validation_report["performance"]["available_meters_found"] = len(available_meters)
            else:
                validation_report["warnings"].append("Failed to discover available meters for validation")
        
        validation_report["performance"]["discovery_time"] = time.time() - start_time
        
        # Validate each meter specification
        for i, meter_spec in enumerate(meters):
            meter_validation = self._validate_single_meter(
                meter_spec, i, available_meters, validation_level, idf_path
            )
            
            if meter_validation["is_valid"]:
                validation_report["valid_meters"].append(meter_validation)
            else:
                validation_report["invalid_meters"].append(meter_validation)
            
            # Collect warnings
            validation_report["warnings"].extend(meter_validation.get("warnings", []))
        
        return validation_report
    
    def _validate_single_meter(self, meter_spec: Dict, index: int, available_meters: List[Dict],
                              validation_level: str, idf_path: str) -> Dict[str, Any]:
        """Validate a single meter specification"""
        result = {
            "index": index,
            "specification": meter_spec,
            "is_valid": True,
            "warnings": [],
            "errors": [],
            "validation_details": {}
        }
        
        meter_name = meter_spec.get("meter_name", "")
        frequency = meter_spec.get("frequency", "hourly")
        meter_type = meter_spec.get("meter_type", "Output:Meter")
        
        # Skip validation if meter name is empty
        if not meter_name:
            result["is_valid"] = False
            result["errors"].append("Meter name cannot be empty")
            return result
        
        # 1. Frequency validation (always done)
        freq_validation = self.validate_frequency(frequency)
        result["validation_details"]["frequency"] = freq_validation
        if not freq_validation["is_valid"]:
            result["is_valid"] = False
            result["errors"].append(freq_validation["error"])
        
        # 2. Meter type validation (always done)
        type_validation = self.validate_meter_type(meter_type)
        result["validation_details"]["meter_type"] = type_validation
        if not type_validation["is_valid"]:
            result["is_valid"] = False
            result["errors"].append(type_validation["error"])
        
        # 3. Meter name validation (moderate and strict)
        if validation_level in ["strict", "moderate"] and available_meters:
            meter_validation = self.validate_meter_name(idf_path, meter_name, available_meters)
            result["validation_details"]["meter_name"] = meter_validation
            if not meter_validation["is_valid"]:
                if validation_level == "strict":
                    result["is_valid"] = False
                    result["errors"].append(meter_validation["error"])
                else:  # moderate
                    result["warnings"].append(f"Meter '{meter_name}' may not be available in model")
                
                if "suggestions" in meter_validation:
                    result["suggestions"] = meter_validation["suggestions"]
            elif "metadata" in meter_validation:
                result["metadata"] = meter_validation["metadata"]
        
        return result
    
    def check_duplicate_meters(self, idf_path: str, meters: List[Dict], 
                              allow_duplicates: bool = False) -> Dict[str, Any]:
        """Check for duplicate meters against existing configuration"""
        # Get currently configured meters using cached method
        configured_meters = self._get_configured_meters_cached(idf_path)
        
        if not configured_meters:
            logger.warning("Failed to get configured meters for duplicate checking")
            return {
                "new_meters": meters,
                "duplicate_meters": [],
                "duplicates_found": 0,
                "will_add": len(meters),
                "note": "Duplicate checking skipped (failed to get configured meters)"
            }
        
        # Create set of existing specifications
        existing_specs = set()
        
        for meter in configured_meters:
            spec = (
                meter.get("key_name", ""),
                meter.get("reporting_frequency", ""),
                meter.get("meter_type", "")
            )
            existing_specs.add(spec)
        
        new_meters = []
        duplicate_meters = []
        
        for meter_spec in meters:
            spec = (
                meter_spec.get("meter_name", ""),
                meter_spec.get("frequency", ""),
                meter_spec.get("meter_type", "")
            )
            
            if spec in existing_specs:
                duplicate_meters.append(meter_spec)
                if allow_duplicates:
                    new_meters.append(meter_spec)
            else:
                new_meters.append(meter_spec)
        
        return {
            "new_meters": new_meters,
            "duplicate_meters": duplicate_meters,
            "duplicates_found": len(duplicate_meters),
            "will_add": len(new_meters)
        }
    
    def add_meters_to_idf(self, idf_path: str, meters: List[Dict], 
                         output_path: str) -> Dict[str, Any]:
        """Add output meters to IDF file and save"""
        try:
            # Load IDF
            idf = IDF(idf_path)
            
            added_meters = []
            
            # Add each meter
            for meter_spec in meters:
                meter_type = meter_spec.get("meter_type", "Output:Meter")
                
                # Create new meter object of the specified type
                output_meter = idf.newidfobject(meter_type)
                
                # Set fields based on meter type
                if meter_type in ["Output:Meter", "Output:Meter:MeterFileOnly"]:
                    output_meter.Key_Name = meter_spec["meter_name"]
                    output_meter.Reporting_Frequency = meter_spec["frequency"]
                elif meter_type in ["Output:Meter:Cumulative", "Output:Meter:Cumulative:MeterFileOnly"]:
                    output_meter.Key_Name = meter_spec["meter_name"]
                    output_meter.Reporting_Frequency = meter_spec["frequency"]
                
                added_meters.append(meter_spec)
                logger.debug(f"Added {meter_type}: {meter_spec}")
            
            # Save modified IDF
            idf.save(output_path)
            
            return {
                "success": True,
                "added_count": len(added_meters),
                "added_meters": added_meters,
                "output_file": output_path
            }
            
        except Exception as e:
            logger.error(f"Error adding meters to IDF: {e}")
            return {
                "success": False,
                "error": str(e),
                "added_count": 0
            }
