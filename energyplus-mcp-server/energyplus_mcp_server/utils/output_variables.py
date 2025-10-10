"""
Output variables utility module for EnergyPlus MCP Server.
Handles discovery, validation, and addition of EnergyPlus output variables.

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
from typing import Dict, List, Any, Optional, Set, Tuple
from pathlib import Path
from datetime import datetime
import shutil
from difflib import get_close_matches

from eppy.modeleditor import IDF

logger = logging.getLogger(__name__)


class ValidationCache:
    """Cache expensive discovery results to improve performance"""
    
    def __init__(self):
        self._available_vars_cache = {}
        self._configured_vars_cache = {}
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


class OutputVariableManager:
    """Manager for EnergyPlus output variable discovery and manipulation"""
    
    def __init__(self, config):
        """Initialize with configuration"""
        self.config = config
        self._validation_cache = ValidationCache()
        
        # Valid frequencies for EnergyPlus output variables
        self.VALID_FREQUENCIES = {
            "detailed": "Each HVAC system timestep",
            "timestep": "Each zone timestep", 
            "hourly": "Each hour",
            "daily": "Each day",
            "monthly": "Each month", 
            "runperiod": "End of run period",
            "annual": "Annual summary"
        }
    
    def discover_available_variables(self, idf_path: str, run_days: int = 1) -> Dict[str, Any]:
        """
        Discover all available output variables by running simulation with Output:VariableDictionary
        
        Args:
            idf_path: Path to the IDF file
            run_days: Number of days to run simulation (default: 1 for speed)
        
        Returns:
            Dictionary with discovered variables and metadata
        """
        try:
            logger.info(f"Discovering available output variables for: {idf_path}")
            
            # Create temporary modified IDF with Output:VariableDictionary
            temp_idf_path = self._create_temp_idf_with_variable_dictionary(idf_path, run_days)
            
            # Run short simulation
            logger.info("Running short simulation to generate variable dictionary...")
            sim_result = self._run_variable_discovery_simulation(temp_idf_path)
            
            if not sim_result["success"]:
                return {
                    "success": False,
                    "error": "Failed to run simulation for variable discovery",
                    "simulation_error": sim_result.get("error", "Unknown error")
                }
            
            # Parse .rdd file
            rdd_file_path = self._find_rdd_file(sim_result["output_directory"])
            if not rdd_file_path:
                return {
                    "success": False,
                    "error": "Could not find .rdd file in simulation output"
                }
            
            # Extract variables from .rdd file
            variables = self._parse_rdd_file(rdd_file_path)
            
            # Clean up temporary files
            self._cleanup_temp_files(temp_idf_path, sim_result["output_directory"])
            
            result = {
                "success": True,
                "discovery_mode": True,
                "input_file": idf_path,
                "total_variables": len(variables),
                "run_days": run_days,
                "categories": self._categorize_variables(variables),
                "variables": variables
            }
            
            logger.info(f"Discovered {len(variables)} available output variables")
            return result
            
        except Exception as e:
            logger.error(f"Error discovering available output variables: {e}")
            raise RuntimeError(f"Error discovering available output variables: {str(e)}")
    
    def get_configured_variables(self, idf_path: str) -> Dict[str, Any]:
        """
        Get currently configured output variables from the IDF file
        
        Args:
            idf_path: Path to the IDF file
        
        Returns:
            Dictionary with currently configured variables
        """
        try:
            logger.debug(f"Getting configured output variables for: {idf_path}")
            idf = IDF(idf_path)
            
            output_vars = idf.idfobjects.get("Output:Variable", [])
            output_meters = idf.idfobjects.get("Output:Meter", [])
            
            variables_info = {
                "success": True,
                "discovery_mode": False,
                "input_file": idf_path,
                "output_variables": [],
                "output_meters": [],
                "summary": {
                    "total_variables": len(output_vars),
                    "total_meters": len(output_meters)
                }
            }
            
            # Process Output:Variable objects
            for var in output_vars:
                var_info = {
                    "key_value": getattr(var, 'Key_Value', 'Unknown'),
                    "variable_name": getattr(var, 'Variable_Name', 'Unknown'),
                    "reporting_frequency": getattr(var, 'Reporting_Frequency', 'Unknown')
                }
                variables_info["output_variables"].append(var_info)
            
            # Process Output:Meter objects
            for meter in output_meters:
                meter_info = {
                    "key_name": getattr(meter, 'Key_Name', 'Unknown'),
                    "reporting_frequency": getattr(meter, 'Reporting_Frequency', 'Unknown')
                }
                variables_info["output_meters"].append(meter_info)
            
            logger.debug(f"Found {len(output_vars)} output variables and {len(output_meters)} output meters")
            return variables_info
            
        except Exception as e:
            logger.error(f"Error getting configured output variables: {e}")
            raise RuntimeError(f"Error getting configured output variables: {str(e)}")
    
    def _create_temp_idf_with_variable_dictionary(self, idf_path: str, run_days: int) -> str:
        """Create temporary IDF with Output:VariableDictionary and short run period"""
        idf = IDF(idf_path)
        
        # Check if Output:VariableDictionary already exists
        existing_var_dict = idf.idfobjects.get('Output:VariableDictionary', [])
        
        if existing_var_dict:
            # Update existing Output:VariableDictionary to use 'IDF' key field
            var_dict = existing_var_dict[0]  # Use the first one if multiple exist
            var_dict.Key_Field = 'IDF'
            logger.debug(f"Updated existing Output:VariableDictionary Key_Field to 'IDF'")
        else:
            # Add new Output:VariableDictionary object
            var_dict = idf.newidfobject('Output:VariableDictionary')
            var_dict.Key_Field = 'IDF'
            logger.debug(f"Added new Output:VariableDictionary with Key_Field 'IDF'")
        
        # Remove any additional Output:VariableDictionary objects to avoid conflicts
        if len(existing_var_dict) > 1:
            for extra_dict in existing_var_dict[1:]:
                idf.removeidfobject(extra_dict)
            logger.debug(f"Removed {len(existing_var_dict) - 1} extra Output:VariableDictionary objects")
        
        # Modify run period to be short (1 day by default)
        run_periods = idf.idfobjects.get("RunPeriod", [])
        if run_periods:
            run_period = run_periods[0]
            # Set to run for specified days in January
            run_period.Begin_Month = 1
            run_period.Begin_Day_of_Month = 1
            run_period.End_Month = 1
            run_period.End_Day_of_Month = run_days
        
        # Create temporary file
        temp_path = os.path.join(
            self.config.paths.temp_dir, 
            f"temp_variable_discovery_{datetime.now().strftime('%Y%m%d_%H%M%S')}.idf"
        )
        idf.save(temp_path)
        
        return temp_path
    
    def _run_variable_discovery_simulation(self, temp_idf_path: str) -> Dict[str, Any]:
        """Run a minimal simulation just to generate the .rdd file"""
        try:
            # Create output directory
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = os.path.join(self.config.paths.temp_dir, f"variable_discovery_{timestamp}")
            os.makedirs(output_dir, exist_ok=True)
            
            # Check for weather file
            weather_file = None
            if os.path.exists(self.config.energyplus.default_weather_file):
                weather_file = self.config.energyplus.default_weather_file
                logger.info(f"Using default weather file: {weather_file}")
            else:
                logger.warning("Default weather file not found, running without weather data")
            
            # Load IDF for simulation (with weather file if available)
            if weather_file:
                idf = IDF(temp_idf_path, weather_file)
            else:
                idf = IDF(temp_idf_path)
            
            # Run simulation with minimal options
            simulation_options = {
                'output_directory': output_dir,
                'annual': False,  # Use RunPeriod only
                'design_day': False,
                'readvars': False,  # Don't need variable processing
                'expandobjects': False,  # Speed up
                'output_prefix': 'variable_discovery',
                'output_suffix': 'C'
            }
            
            # Add weather file to options if available
            if weather_file:
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
            logger.error(f"Simulation failed during variable discovery: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def _find_rdd_file(self, output_directory: str) -> Optional[str]:
        """Find the .rdd file in the simulation output directory"""
        output_dir = Path(output_directory)
        rdd_files = list(output_dir.glob("*.rdd"))
        
        if rdd_files:
            return str(rdd_files[0])
        return None
    
    def _parse_rdd_file(self, rdd_file_path: str) -> List[Dict[str, Any]]:
        """Parse the .rdd file to extract available output variables"""
        variables = []
        
        try:
            with open(rdd_file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    
                    # Skip comments and empty lines
                    if line.startswith('!') or not line:
                        continue
                    
                    # Look for Output:Variable lines
                    if line.startswith('Output:Variable,'):
                        try:
                            # Parse the CSV-like format
                            # Format: Output:Variable,*,Variable Name,frequency; !- Units [Unit]
                            parts = line.split(',')
                            if len(parts) >= 4:
                                key_value = parts[1].strip()
                                variable_name = parts[2].strip()
                                frequency_part = parts[3].strip()
                                
                                # Extract frequency (remove semicolon and comment)
                                frequency = frequency_part.split(';')[0].strip()
                                
                                # Extract units from comment if present
                                units = ""
                                if '!-' in line:
                                    comment_part = line.split('!-')[1].strip()
                                    if '[' in comment_part and ']' in comment_part:
                                        units = comment_part.split('[')[1].split(']')[0]
                                
                                variables.append({
                                    "key_value": key_value,
                                    "variable_name": variable_name,
                                    "default_frequency": frequency,
                                    "units": units,
                                    "output_variable_line": f"Output:Variable,{key_value},{variable_name},{frequency};"
                                })
                        except Exception as e:
                            logger.warning(f"Could not parse .rdd line: {line} - Error: {e}")
                            continue
        
        except Exception as e:
            logger.error(f"Error reading .rdd file {rdd_file_path}: {e}")
            raise
        
        return variables
    
    def _categorize_variables(self, variables: List[Dict[str, Any]]) -> Dict[str, int]:
        """Categorize variables by type for summary statistics"""
        categories = {}
        
        for var in variables:
            var_name = var["variable_name"].lower()
            
            # Simple categorization based on variable name
            if 'temperature' in var_name:
                categories['Temperature'] = categories.get('Temperature', 0) + 1
            elif 'energy' in var_name or 'electricity' in var_name or 'gas' in var_name:
                categories['Energy'] = categories.get('Energy', 0) + 1
            elif 'flow' in var_name or 'mass' in var_name:
                categories['Flow/Mass'] = categories.get('Flow/Mass', 0) + 1
            elif 'humidity' in var_name or 'moisture' in var_name:
                categories['Humidity'] = categories.get('Humidity', 0) + 1
            elif 'zone' in var_name:
                categories['Zone'] = categories.get('Zone', 0) + 1
            elif 'system' in var_name or 'hvac' in var_name:
                categories['HVAC System'] = categories.get('HVAC System', 0) + 1
            elif 'surface' in var_name:
                categories['Surface'] = categories.get('Surface', 0) + 1
            elif 'site' in var_name or 'outdoor' in var_name:
                categories['Site/Outdoor'] = categories.get('Site/Outdoor', 0) + 1
            else:
                categories['Other'] = categories.get('Other', 0) + 1
        
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

    def _get_available_variables_cached(self, idf_path: str, force_refresh: bool = False) -> List[Dict]:
        """Get available variables using discovery tool with intelligent caching"""
        cache_key = self._validation_cache.get_cache_key(idf_path)
        
        # Check cache first
        if (not force_refresh and 
            cache_key in self._validation_cache._available_vars_cache and
            self._validation_cache.is_cache_valid(cache_key)):
            
            logger.debug(f"Using cached available variables for {idf_path}")
            return self._validation_cache._available_vars_cache[cache_key]
        
        logger.info(f"Discovering available variables for validation: {idf_path}")
        
        try:
            # Use existing discovery method
            discovery_result = self.discover_available_variables(idf_path, run_days=1)
            
            if discovery_result.get("success"):
                available_vars = discovery_result.get("variables", [])
                # Cache the results
                self._validation_cache._available_vars_cache[cache_key] = available_vars
                self._validation_cache._cache_timestamps[cache_key] = time.time()
                logger.info(f"Cached {len(available_vars)} available variables")
                return available_vars
            else:
                logger.warning(f"Failed to discover available variables: {discovery_result.get('error')}")
                return []
                
        except Exception as e:
            logger.error(f"Error during variable discovery: {e}")
            return []
    
    def _get_configured_variables_cached(self, idf_path: str) -> List[Dict]:
        """Get currently configured variables with caching"""
        cache_key = self._validation_cache.get_cache_key(idf_path)
        
        # Check cache first
        if (cache_key in self._validation_cache._configured_vars_cache and
            self._validation_cache.is_cache_valid(cache_key)):
            return self._validation_cache._configured_vars_cache[cache_key]
        
        try:
            # Use existing method
            configured_result = self.get_configured_variables(idf_path)
            
            if configured_result.get("success"):
                configured_vars = configured_result.get("output_variables", [])
                # Cache the results
                self._validation_cache._configured_vars_cache[cache_key] = configured_vars
                self._validation_cache._cache_timestamps[cache_key] = time.time()
                return configured_vars
            else:
                return []
                
        except Exception as e:
            logger.error(f"Error getting configured variables: {e}")
            return []
    
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
            return {
                "is_valid": False,
                "error": f"Invalid frequency '{frequency}'",
                "valid_options": list(self.VALID_FREQUENCIES.keys()),
                "suggestions": get_close_matches(freq_lower, self.VALID_FREQUENCIES.keys(), n=3, cutoff=0.6)
            }
    
    def validate_variable_name(self, idf_path: str, variable_name: str, 
                             available_vars: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """Validate variable name against available variables in the model"""
        if not variable_name or not isinstance(variable_name, str):
            return {
                "is_valid": False,
                "error": "Variable name must be a non-empty string"
            }
        
        # Get available variables if not provided
        if available_vars is None:
            available_vars = self._get_available_variables_cached(idf_path)
        
        available_names = {var["variable_name"] for var in available_vars}
        variable_lookup = {var["variable_name"]: var for var in available_vars}
        
        if variable_name in available_names:
            return {
                "is_valid": True,
                "metadata": variable_lookup[variable_name]
            }
        else:
            result = {
                "is_valid": False,
                "error": f"Variable '{variable_name}' not available in this model"
            }
            
            # Find similar variable names
            suggestions = get_close_matches(variable_name, available_names, n=5, cutoff=0.6)
            if suggestions:
                result["suggestions"] = suggestions
            
            return result
    
    def validate_key_value(self, idf_path: str, key_value: str, variable_name: str) -> Dict[str, Any]:
        """Validate key value against model objects (basic implementation)"""
        if not key_value or not isinstance(key_value, str):
            return {
                "is_valid": False,
                "error": "Key value must be a non-empty string"
            }
        
        key_value = key_value.strip()
        
        # "*" is always valid (applies to all applicable objects)
        if key_value == "*":
            return {
                "is_valid": True,
                "resolved_keys": ["*"],
                "note": "Will apply to all applicable objects"
            }
        
        # For now, accept any non-empty string as potentially valid
        # Advanced validation would require loading the IDF and checking object names
        # This could be enhanced later with model introspection
        return {
            "is_valid": True,
            "resolved_keys": [key_value],
            "note": f"Will apply to object '{key_value}' if it exists in the model"
        }
    
    def auto_resolve_variable_specs(self, variables: List) -> List[Dict]:
        """Convert various input formats to standardized variable specifications"""
        resolved = []
        
        for var_spec in variables:
            if isinstance(var_spec, str):
                # Simple string -> full specification
                resolved.append({
                    "key_value": "*",
                    "variable_name": var_spec,
                    "frequency": "hourly"
                })
            elif isinstance(var_spec, list) and len(var_spec) >= 2:
                # [variable_name, frequency] -> full specification
                resolved.append({
                    "key_value": "*",
                    "variable_name": var_spec[0],
                    "frequency": var_spec[1]
                })
            elif isinstance(var_spec, dict):
                # Already a dict, ensure required fields
                spec = {
                    "key_value": var_spec.get("key_value", "*"),
                    "variable_name": var_spec.get("variable_name", ""),
                    "frequency": var_spec.get("frequency", "hourly")
                }
                resolved.append(spec)
            else:
                logger.warning(f"Invalid variable specification format: {var_spec}")
                continue
        
        return resolved
    
    def validate_variable_specifications(self, idf_path: str, variables: List[Dict], 
                                       validation_level: str = "moderate") -> Dict[str, Any]:
        """Validate a batch of variable specifications"""
        start_time = time.time()
        
        validation_report = {
            "total_requested": len(variables),
            "validation_level": validation_level,
            "valid_variables": [],
            "invalid_variables": [],
            "warnings": [],
            "performance": {}
        }
        
        # Get available variables for validation (cached)
        available_vars = []
        if validation_level in ["strict", "moderate"]:
            available_vars = self._get_available_variables_cached(idf_path)
            validation_report["performance"]["available_variables_found"] = len(available_vars)
        
        validation_report["performance"]["discovery_time"] = time.time() - start_time
        
        # Validate each variable specification
        for i, var_spec in enumerate(variables):
            var_validation = self._validate_single_variable(
                var_spec, i, available_vars, validation_level, idf_path
            )
            
            if var_validation["is_valid"]:
                validation_report["valid_variables"].append(var_validation)
            else:
                validation_report["invalid_variables"].append(var_validation)
            
            # Collect warnings
            validation_report["warnings"].extend(var_validation.get("warnings", []))
        
        return validation_report
    
    def _validate_single_variable(self, var_spec: Dict, index: int, available_vars: List[Dict],
                                 validation_level: str, idf_path: str) -> Dict[str, Any]:
        """Validate a single variable specification"""
        result = {
            "index": index,
            "specification": var_spec,
            "is_valid": True,
            "warnings": [],
            "errors": [],
            "validation_details": {}
        }
        
        variable_name = var_spec.get("variable_name", "")
        key_value = var_spec.get("key_value", "*")
        frequency = var_spec.get("frequency", "hourly")
        
        # Skip validation if variable name is empty
        if not variable_name:
            result["is_valid"] = False
            result["errors"].append("Variable name cannot be empty")
            return result
        
        # 1. Frequency validation (always done)
        freq_validation = self.validate_frequency(frequency)
        result["validation_details"]["frequency"] = freq_validation
        if not freq_validation["is_valid"]:
            result["is_valid"] = False
            result["errors"].append(freq_validation["error"])
        
        # 2. Variable name validation (moderate and strict)
        if validation_level in ["strict", "moderate"]:
            var_validation = self.validate_variable_name(idf_path, variable_name, available_vars)
            result["validation_details"]["variable_name"] = var_validation
            if not var_validation["is_valid"]:
                result["is_valid"] = False
                result["errors"].append(var_validation["error"])
                if "suggestions" in var_validation:
                    result["suggestions"] = var_validation["suggestions"]
            elif "metadata" in var_validation:
                result["metadata"] = var_validation["metadata"]
        
        # 3. Key value validation (strict only)
        if validation_level == "strict":
            key_validation = self.validate_key_value(idf_path, key_value, variable_name)
            result["validation_details"]["key_value"] = key_validation
            if not key_validation["is_valid"]:
                result["is_valid"] = False
                result["errors"].append(key_validation["error"])
            else:
                result["warnings"].extend(key_validation.get("warnings", []))
        
        return result
    
    def check_duplicate_variables(self, idf_path: str, variables: List[Dict], 
                                allow_duplicates: bool = False) -> Dict[str, Any]:
        """Check for duplicate variables against existing configuration"""
        # Get currently configured variables
        configured_vars = self._get_configured_variables_cached(idf_path)
        
        # Create set of existing specifications
        existing_specs = set()
        for var in configured_vars:
            spec = (
                var.get("key_value", ""),
                var.get("variable_name", ""),
                var.get("reporting_frequency", "")
            )
            existing_specs.add(spec)
        
        new_variables = []
        duplicate_variables = []
        
        for var_spec in variables:
            spec = (
                var_spec.get("key_value", ""),
                var_spec.get("variable_name", ""),
                var_spec.get("frequency", "")
            )
            
            if spec in existing_specs:
                duplicate_variables.append(var_spec)
                if allow_duplicates:
                    new_variables.append(var_spec)
            else:
                new_variables.append(var_spec)
        
        return {
            "new_variables": new_variables,
            "duplicate_variables": duplicate_variables,
            "duplicates_found": len(duplicate_variables),
            "will_add": len(new_variables)
        }
    
    def add_variables_to_idf(self, idf_path: str, variables: List[Dict], 
                           output_path: str) -> Dict[str, Any]:
        """Add output variables to IDF file and save"""
        try:
            # Load IDF
            idf = IDF(idf_path)
            
            added_variables = []
            
            # Add each variable
            for var_spec in variables:
                # Create new Output:Variable object
                output_var = idf.newidfobject('Output:Variable')
                output_var.Key_Value = var_spec["key_value"]
                output_var.Variable_Name = var_spec["variable_name"]
                output_var.Reporting_Frequency = var_spec["frequency"]
                
                added_variables.append(var_spec)
                logger.debug(f"Added Output:Variable: {var_spec}")
            
            # Save modified IDF
            idf.save(output_path)
            
            return {
                "success": True,
                "added_count": len(added_variables),
                "added_variables": added_variables,
                "output_file": output_path
            }
            
        except Exception as e:
            logger.error(f"Error adding variables to IDF: {e}")
            return {
                "success": False,
                "error": str(e),
                "added_count": 0
            }
