"""
Error parser utility module for EnergyPlus MCP Server.
Handles parsing and analysis of EnergyPlus error files (.err).
"""

import re
import logging
from typing import Dict, List, Any, Optional
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class EnergyPlusError:
    """Represents a single error from EnergyPlus output"""
    severity: str  # Warning, Severe, Fatal
    message: str
    context: List[str] = field(default_factory=list)
    line_number: int = 0
    object_reference: Optional[str] = None


class ErrorParser:
    """Parser for EnergyPlus error files"""
    
    def __init__(self):
        self.error_patterns = {
            'warning': re.compile(r'\*\*\s+Warning\s+\*\*\s+(.+)'),
            'severe': re.compile(r'\*\*\s+Severe\s+\*\*\s+(.+)'),
            'fatal': re.compile(r'\*\*\s+Fatal\s+\*\*\s+(.+)'),
            'context': re.compile(r'\*\*\s+~~~\s+\*\*\s+(.+)'),
            'summary': re.compile(r'\*{5,}(.+)'),
            'object_ref': re.compile(r'([A-Za-z:]+)="([^"]+)"')
        }
    
    def parse_error_file(self, err_path: str) -> Dict[str, Any]:
        """Parse an EnergyPlus .err file and return structured error data"""
        err_file = Path(err_path)
        
        if not err_file.exists():
            return {
                "file_path": str(err_path),
                "exists": False,
                "error": "Error file not found"
            }
        
        errors = {
            "warnings": [],
            "severe_errors": [],
            "fatal_errors": []
        }
        
        current_error = None
        version_info = None
        summary_info = []
        
        try:
            with open(err_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                
            for line_num, line in enumerate(lines, 1):
                line = line.rstrip()
                
                # Skip empty lines
                if not line:
                    continue
                
                # Parse version info
                if line_num == 1 and line.startswith("Program Version"):
                    version_info = line
                    continue
                
                # Check for warning
                warning_match = self.error_patterns['warning'].match(line)
                if warning_match:
                    if current_error:
                        self._store_error(errors, current_error)
                    current_error = EnergyPlusError(
                        severity="Warning",
                        message=warning_match.group(1),
                        line_number=line_num
                    )
                    self._extract_object_reference(current_error)
                    continue
                
                # Check for severe error
                severe_match = self.error_patterns['severe'].match(line)
                if severe_match:
                    if current_error:
                        self._store_error(errors, current_error)
                    current_error = EnergyPlusError(
                        severity="Severe",
                        message=severe_match.group(1),
                        line_number=line_num
                    )
                    self._extract_object_reference(current_error)
                    continue
                
                # Check for fatal error
                fatal_match = self.error_patterns['fatal'].match(line)
                if fatal_match:
                    if current_error:
                        self._store_error(errors, current_error)
                    current_error = EnergyPlusError(
                        severity="Fatal",
                        message=fatal_match.group(1),
                        line_number=line_num
                    )
                    self._extract_object_reference(current_error)
                    continue
                
                # Check for context lines
                context_match = self.error_patterns['context'].match(line)
                if context_match and current_error:
                    current_error.context.append(context_match.group(1))
                    continue
                
                # Check for summary lines
                summary_match = self.error_patterns['summary'].match(line)
                if summary_match:
                    if current_error:
                        self._store_error(errors, current_error)
                        current_error = None
                    summary_info.append(line)
            
            # Store last error if exists
            if current_error:
                self._store_error(errors, current_error)
            
            # Parse summary statistics
            stats = self._parse_summary(summary_info)
            
            return {
                "file_path": str(err_path),
                "exists": True,
                "version": version_info,
                "warnings": [self._error_to_dict(e) for e in errors["warnings"]],
                "severe_errors": [self._error_to_dict(e) for e in errors["severe_errors"]],
                "fatal_errors": [self._error_to_dict(e) for e in errors["fatal_errors"]],
                "counts": {
                    "warnings": len(errors["warnings"]),
                    "severe": len(errors["severe_errors"]),
                    "fatal": len(errors["fatal_errors"])
                },
                "summary": stats
            }
            
        except Exception as e:
            logger.error(f"Error parsing file {err_path}: {e}")
            return {
                "file_path": str(err_path),
                "exists": True,
                "error": f"Failed to parse: {str(e)}"
            }
    
    def _store_error(self, errors: Dict, error: EnergyPlusError):
        """Store error in appropriate category"""
        if error.severity == "Warning":
            errors["warnings"].append(error)
        elif error.severity == "Severe":
            errors["severe_errors"].append(error)
        elif error.severity == "Fatal":
            errors["fatal_errors"].append(error)
    
    def _extract_object_reference(self, error: EnergyPlusError):
        """Extract object reference from error message"""
        match = self.error_patterns['object_ref'].search(error.message)
        if match:
            error.object_reference = f"{match.group(1)}={match.group(2)}"
    
    def _error_to_dict(self, error: EnergyPlusError) -> Dict[str, Any]:
        """Convert error object to dictionary"""
        return {
            "severity": error.severity,
            "message": error.message,
            "context": error.context,
            "line_number": error.line_number,
            "object_reference": error.object_reference
        }
    
    def _parse_summary(self, summary_lines: List[str]) -> Dict[str, Any]:
        """Parse summary statistics from error file"""
        stats = {}
        
        for line in summary_lines:
            # Parse error counts from summary
            if "Warning" in line and "Severe" in line:
                # Extract counts from lines like "During Warmup: 2 Warning; 6 Severe Errors"
                warning_match = re.search(r'(\d+)\s+Warning', line)
                severe_match = re.search(r'(\d+)\s+Severe', line)
                
                if warning_match:
                    stats.setdefault("phase_counts", {}).setdefault("warnings", 0)
                    stats["phase_counts"]["warnings"] += int(warning_match.group(1))
                if severe_match:
                    stats.setdefault("phase_counts", {}).setdefault("severe", 0)
                    stats["phase_counts"]["severe"] += int(severe_match.group(1))
            
            # Parse elapsed time
            if "Elapsed Time" in line:
                time_match = re.search(r'Elapsed Time=(.+)', line)
                if time_match:
                    stats["elapsed_time"] = time_match.group(1).strip()
            
            # Check for termination
            if "Terminated--Fatal Error" in line:
                stats["terminated"] = True
        
        return stats
    
    def analyze_root_cause(self, parsed_errors: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze errors to identify root causes and patterns"""
        analysis = {
            "primary_issue": None,
            "patterns": [],
            "affected_objects": set()
        }
        
        # Identify primary issue (first fatal or severe error)
        if parsed_errors.get("fatal_errors"):
            analysis["primary_issue"] = parsed_errors["fatal_errors"][0]["message"]
        elif parsed_errors.get("severe_errors"):
            analysis["primary_issue"] = parsed_errors["severe_errors"][0]["message"]
        
        # Find common patterns
        all_errors = (
            parsed_errors.get("severe_errors", []) + 
            parsed_errors.get("fatal_errors", [])
        )
        
        # Check for zone reference errors
        zone_errors = [e for e in all_errors if "invalid Zone Name" in e["message"]]
        if zone_errors:
            analysis["patterns"].append({
                "type": "zone_reference",
                "count": len(zone_errors),
                "description": "Multiple surfaces reference non-existent zone"
            })
        
        # Collect affected objects
        for error in all_errors:
            if error.get("object_reference"):
                analysis["affected_objects"].add(error["object_reference"])
        
        analysis["affected_objects"] = list(analysis["affected_objects"])
        
        return analysis