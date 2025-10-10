"""
Path utilities for EnergyPlus MCP Server
Provides centralized path resolution for various file types

EnergyPlus Model Context Protocol Server (EnergyPlus-MCP)
Copyright (c) 2025, The Regents of the University of California,
through Lawrence Berkeley National Laboratory (subject to receipt of
any required approvals from the U.S. Dept. of Energy). All rights reserved.

See License.txt in the parent directory for license details.
"""

import os
from pathlib import Path
from typing import List, Optional, Union
import fnmatch
import difflib

from ..config import Config


class PathResolver:
    """Helper class for path resolution with fuzzy matching capabilities"""
    
    def __init__(self, config: Config):
        self.config = config
    
    def suggest_similar_paths(self, target_path: str, extensions: List[str] = None) -> List[str]:
        """
        Suggest similar file paths when exact match is not found
        
        Args:
            target_path: The path that wasn't found
            extensions: List of file extensions to filter by (e.g., ['.idf', '.epw'])
        
        Returns:
            List of similar paths sorted by similarity
        """
        suggestions = []
        search_dirs = [
            self.config.paths.sample_files_path,
            self.config.paths.workspace_root,
            self.config.energyplus.example_files_path,
            self.config.energyplus.weather_data_path
        ]
        
        target_name = os.path.basename(target_path).lower()
        
        for search_dir in search_dirs:
            if not search_dir or not os.path.exists(search_dir):
                continue
                
            try:
                for root, dirs, files in os.walk(search_dir):
                    for file in files:
                        file_lower = file.lower()
                        
                        # Filter by extensions if provided
                        if extensions and not any(file_lower.endswith(ext.lower()) for ext in extensions):
                            continue
                        
                        # Calculate similarity
                        similarity = difflib.SequenceMatcher(None, target_name, file_lower).ratio()
                        
                        if similarity > 0.3:  # Threshold for similarity
                            full_path = os.path.join(root, file)
                            suggestions.append((full_path, similarity))
            except (PermissionError, OSError):
                continue
        
        # Sort by similarity and return paths only
        suggestions.sort(key=lambda x: x[1], reverse=True)
        return [path for path, _ in suggestions[:10]]  # Return top 10 matches


def resolve_path(config: Config, file_path: str, file_types: List[str] = None, 
                 description: str = "file", must_exist: bool = True, 
                 default_dir: str = None, enable_fuzzy_weather_matching: bool = False) -> str:
    """
    Generic path resolution with support for various file types and use cases
    
    Args:
        config: Configuration object
        file_path: Input file path (can be relative, filename only, etc.)
        file_types: List of acceptable file extensions (e.g., ['.idf', '.epw'])
        description: Description of file type for error messages
        must_exist: If True, file must exist. If False, can be a target path for creation
        default_dir: Default directory to use if file_path is just a filename
        enable_fuzzy_weather_matching: Enable fuzzy city name matching for weather files
    
    Returns:
        Resolved absolute path
    
    Raises:
        FileNotFoundError: If must_exist=True and file cannot be found
        ValueError: If file_path is empty or has wrong extension
    """
    if not file_path:
        raise ValueError(f"{description} path cannot be empty")
    
    # If it's already an absolute path
    if os.path.isabs(file_path):
        if must_exist and not os.path.exists(file_path):
            raise FileNotFoundError(f"{description} not found: {file_path}")
        if file_types and not any(file_path.lower().endswith(ext.lower()) for ext in file_types):
            raise ValueError(f"File '{file_path}' does not have expected extension: {file_types}")
        return file_path
    
    # For output paths (must_exist=False), handle path construction
    if not must_exist:
        # If it contains directory separators, treat as relative to workspace
        if os.path.dirname(file_path):
            base_path = config.paths.workspace_root
            return os.path.join(base_path, file_path)
        
        # If it's just a filename, use default directory or output directory
        if default_dir:
            return os.path.join(default_dir, file_path)
        else:
            return os.path.join(config.paths.output_dir, file_path)
    
    # For input paths (must_exist=True), search in various locations
    search_paths = [
        # 1. Relative to sample files directory
        config.paths.sample_files_path,
        # 2. Relative to workspace root
        config.paths.workspace_root,
        # 3. Relative to EnergyPlus example files (if applicable)
        config.energyplus.example_files_path if file_types and '.idf' in file_types else None,
        # 4. Relative to EnergyPlus weather data (if applicable)
        config.energyplus.weather_data_path if file_types and '.epw' in file_types else None,
    ]
    
    # Remove None values
    search_paths = [path for path in search_paths if path]
    
    # Try each search path
    for search_path in search_paths:
        if not search_path or not os.path.exists(search_path):
            continue
            
        candidate_path = os.path.join(search_path, file_path)
        if os.path.exists(candidate_path):
            if file_types and not any(candidate_path.lower().endswith(ext.lower()) for ext in file_types):
                continue
            return os.path.abspath(candidate_path)
    
    # Try as-is (relative to current directory)
    if os.path.exists(file_path):
        abs_path = os.path.abspath(file_path)
        if file_types and not any(abs_path.lower().endswith(ext.lower()) for ext in file_types):
            raise ValueError(f"File '{file_path}' does not have expected extension: {file_types}")
        return abs_path
    
    # If fuzzy weather matching is enabled and we haven't found the file
    if enable_fuzzy_weather_matching and file_types and '.epw' in file_types:
        weather_files = find_weather_files_by_name(config, file_path)
        if weather_files:
            return weather_files[0]
    
    # If we get here, the file doesn't exist anywhere we looked
    raise FileNotFoundError(f"{description} not found: {file_path}")


# Convenience functions for common use cases
def resolve_idf_path(config: Config, idf_path: str) -> str:
    """Resolve IDF file path (existing file)"""
    return resolve_path(config, idf_path, file_types=['.idf'], description="IDF file")


def resolve_weather_file_path(config: Config, weather_path: str) -> str:
    """Resolve weather file path with fuzzy city name matching"""
    return resolve_path(config, weather_path, file_types=['.epw'], description="weather file", 
                       enable_fuzzy_weather_matching=True)


def resolve_output_path(config: Config, output_path: str, default_dir: str = None) -> str:
    """Resolve output file path (for file creation)"""
    return resolve_path(config, output_path, must_exist=False, default_dir=default_dir, description="output file")


def find_weather_files_by_name(config: Config, partial_name: str) -> List[str]:
    """
    Find weather files that match a partial name (e.g., 'San Francisco' -> matching .epw files)
    
    Args:
        config: Configuration object
        partial_name: Partial name or city name to search for
    
    Returns:
        List of matching weather file paths, sorted by relevance
    """
    matching_files = []
    partial_lower = partial_name.lower()
    
    # Search directories
    search_dirs = [
        config.paths.sample_files_path,
        config.energyplus.weather_data_path
    ]
    
    for search_dir in search_dirs:
        if not search_dir or not os.path.exists(search_dir):
            continue
            
        search_path = Path(search_dir)
        for file_path in search_path.glob("*.epw"):
            file_name_lower = file_path.name.lower()
            
            # Check if partial name is in the file name (case insensitive)
            if partial_lower in file_name_lower:
                matching_files.append(str(file_path))
            else:
                # Check if individual words from partial name are in file name
                partial_words = partial_lower.replace('_', ' ').replace('-', ' ').split()
                if partial_words and all(word in file_name_lower for word in partial_words):
                    matching_files.append(str(file_path))
    
    # Sort by length (shorter names are likely more relevant)
    matching_files.sort(key=lambda x: len(os.path.basename(x)))
    
    return matching_files


def validate_file_path(file_path: str, must_exist: bool = True, expected_extensions: List[str] = None) -> bool:
    """
    Validate a file path
    
    Args:
        file_path: Path to validate
        must_exist: Whether the file must exist
        expected_extensions: List of acceptable file extensions
    
    Returns:
        True if valid, False otherwise
    """
    if not file_path:
        return False
    
    if must_exist and not os.path.exists(file_path):
        return False
    
    if expected_extensions:
        if not any(file_path.lower().endswith(ext.lower()) for ext in expected_extensions):
            return False
    
    return True


def ensure_directory_exists(dir_path: str) -> None:
    """
    Ensure a directory exists, creating it if necessary
    
    Args:
        dir_path: Directory path to create
    """
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)


def get_file_info(file_path: str) -> dict:
    """
    Get detailed information about a file
    
    Args:
        file_path: Path to the file
    
    Returns:
        Dictionary with file information
    """
    if not os.path.exists(file_path):
        return {"exists": False}
    
    stat = os.stat(file_path)
    return {
        "exists": True,
        "path": os.path.abspath(file_path),
        "name": os.path.basename(file_path),
        "size_bytes": stat.st_size,
        "modified_time": stat.st_mtime,
        "is_readable": os.access(file_path, os.R_OK),
        "is_writable": os.access(file_path, os.W_OK),
        "extension": os.path.splitext(file_path)[1].lower()
    }