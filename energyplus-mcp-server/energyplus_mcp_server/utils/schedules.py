"""
Schedule value parser and modifier utilities for EnergyPlus schedule objects.
Handles extraction and formatting of schedule values from different schedule types.

EnergyPlus Model Context Protocol Server (EnergyPlus-MCP)
Copyright (c) 2025, The Regents of the University of California,
through Lawrence Berkeley National Laboratory (subject to receipt of
any required approvals from the U.S. Dept. of Energy). All rights reserved.

See License.txt in the parent directory for license details.
Provides simple natural language parsing and schedule type conversions.
"""

import re
import logging
from typing import Dict, List, Any, Optional, Tuple, Union
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class ScheduleValueParser:
    """Parser for extracting values from different EnergyPlus schedule objects"""
    
    @staticmethod
    def parse_day_hourly(schedule_obj) -> Dict[str, Any]:
        """
        Parse Schedule:Day:Hourly values
        
        Args:
            schedule_obj: eppy schedule object
            
        Returns:
            Dictionary with hourly values and metadata
        """
        try:
            values = []
            time_labels = []
            
            # Extract 24 hourly values
            for hour in range(1, 25):
                field_name = f"Hour_{hour}_Value" if hour > 1 else "Hour_1_Value"
                try:
                    value = getattr(schedule_obj, field_name, 0.0)
                    # Handle empty strings and non-numeric values
                    if value == '' or value is None:
                        value = 0.0
                    else:
                        value = float(value)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid value for {field_name}: {value}, using 0.0")
                    value = 0.0
                
                values.append(value)
                time_labels.append(f"{hour-1:02d}:00")
            
            # Validate we have 24 values
            if len(values) != 24:
                logger.warning(f"Expected 24 hourly values, got {len(values)}")
                # Pad with zeros or truncate as needed
                values = (values + [0.0] * 24)[:24]
            
            return {
                "format": "hourly",
                "data": values,
                "time_labels": time_labels,
                "total_hours": 24,
                "min_value": min(values) if values else 0.0,
                "max_value": max(values) if values else 0.0,
                "average_value": sum(values) / len(values) if values else 0.0
            }
            
        except Exception as e:
            logger.error(f"Error parsing Schedule:Day:Hourly values: {e}")
            return {"format": "hourly", "error": str(e)}

    @staticmethod
    def parse_day_interval(schedule_obj) -> Dict[str, Any]:
        """
        Parse Schedule:Day:Interval values
        
        Args:
            schedule_obj: eppy schedule object
            
        Returns:
            Dictionary with interval values and metadata
        """
        try:
            intervals = []
            
            # Extract time-value pairs (extensible object)
            for i in range(1, 50):  # EnergyPlus supports many intervals
                time_field = f"Time_{i}" if i > 1 else "Time_1"
                value_field = f"Value_Until_Time_{i}" if i > 1 else "Value_Until_Time_1"
                
                time_val = getattr(schedule_obj, time_field, None)
                value_val = getattr(schedule_obj, value_field, None)
                
                if time_val is None or time_val == '':
                    break
                
                # Clean up time format (remove "Until:" prefix if present)
                time_str = str(time_val).replace("Until:", "").strip()
                
                # Validate time format
                if not ScheduleValueParser._validate_time_format(time_str):
                    logger.warning(f"Invalid time format: {time_str}, skipping interval")
                    continue
                
                try:
                    value = float(value_val) if value_val not in [None, ''] else 0.0
                except (ValueError, TypeError):
                    logger.warning(f"Invalid value for interval {i}: {value_val}, using 0.0")
                    value = 0.0
                
                intervals.append({
                    "until": time_str,
                    "value": value
                })
            
            values = [interval["value"] for interval in intervals]
            
            return {
                "format": "intervals",
                "data": intervals,
                "total_intervals": len(intervals),
                "interpolate_to_timestep": getattr(schedule_obj, 'Interpolate_to_Timestep', 'No'),
                "min_value": min(values) if values else 0.0,
                "max_value": max(values) if values else 0.0,
                "average_value": sum(values) / len(values) if values else 0.0
            }
            
        except Exception as e:
            logger.error(f"Error parsing Schedule:Day:Interval values: {e}")
            return {"format": "intervals", "error": str(e)}

    @staticmethod
    def _validate_time_format(time_str: str) -> bool:
        """Validate time format (HH:MM or H:MM)"""
        try:
            time_pattern = r'^([0-1]?[0-9]|2[0-4]):([0-5][0-9])$'
            return bool(re.match(time_pattern, time_str))
        except:
            return False

    @staticmethod
    def parse_day_list(schedule_obj) -> Dict[str, Any]:
        """
        Parse Schedule:Day:List values
        
        Args:
            schedule_obj: eppy schedule object
            
        Returns:
            Dictionary with list values and metadata
        """
        try:
            values = []
            minutes_per_item = getattr(schedule_obj, 'Minutes_Per_Item', 60)
            
            # Validate and convert minutes_per_item
            try:
                minutes_per_item = int(minutes_per_item) if minutes_per_item != '' else 60
                if minutes_per_item <= 0 or minutes_per_item > 1440:
                    logger.warning(f"Invalid minutes_per_item: {minutes_per_item}, using 60")
                    minutes_per_item = 60
            except (ValueError, TypeError):
                logger.warning(f"Invalid minutes_per_item: {minutes_per_item}, using 60")
                minutes_per_item = 60
            
            # Extract values (up to 1440 for minute-by-minute)
            max_values = 1440 // minutes_per_item  # Maximum possible values for a day
            
            for i in range(1, max_values + 1):
                value_field = f"Value_{i}" if i > 1 else "Value_1"
                value = getattr(schedule_obj, value_field, None)
                
                if value is None or value == '':
                    break
                
                try:
                    values.append(float(value))
                except (ValueError, TypeError):
                    logger.warning(f"Invalid value for {value_field}: {value}, using 0.0")
                    values.append(0.0)
            
            # Generate time labels
            time_labels = []
            for i, _ in enumerate(values):
                start_minute = i * minutes_per_item
                hours = start_minute // 60
                minutes = start_minute % 60
                time_labels.append(f"{hours:02d}:{minutes:02d}")
            
            return {
                "format": "list",
                "data": values,
                "time_labels": time_labels,
                "minutes_per_item": minutes_per_item,
                "total_items": len(values),
                "interpolate_to_timestep": getattr(schedule_obj, 'Interpolate_to_Timestep', 'No'),
                "min_value": min(values) if values else 0.0,
                "max_value": max(values) if values else 0.0,
                "average_value": sum(values) / len(values) if values else 0.0
            }
            
        except Exception as e:
            logger.error(f"Error parsing Schedule:Day:List values: {e}")
            return {"format": "list", "error": str(e)}

    @staticmethod
    def parse_compact_schedule(schedule_obj) -> Dict[str, Any]:
        """
        Parse Schedule:Compact values
        
        Args:
            schedule_obj: eppy schedule object
            
        Returns:
            Dictionary with parsed compact schedule structure
        """
        try:
            # Get all fields from the schedule object
            # Schedule:Compact is an extensible object with variable fields
            periods = []
            current_period = None
            
            # Extract field values - improved approach to get all extensible fields
            field_values = []
            
            # Get field names from the object (eppy objects have fieldnames attribute)
            if hasattr(schedule_obj, 'fieldnames'):
                field_names = schedule_obj.fieldnames[2:]  # Skip Name and Schedule_Type_Limits_Name
                for field_name in field_names:
                    try:
                        value = getattr(schedule_obj, field_name, None)
                        if value is not None and str(value).strip() != '':
                            field_values.append(str(value).strip())
                    except Exception:
                        continue
            else:
                # Fallback to the original method
                field_names = [attr for attr in dir(schedule_obj) if not attr.startswith('_')]
                for field_name in field_names:
                    if field_name.lower() not in ['name', 'schedule_type_limits_name']:
                        try:
                            value = getattr(schedule_obj, field_name, None)
                            if value is not None and str(value).strip() != '':
                                field_values.append(str(value).strip())
                        except Exception:
                            continue
            
            # Parse the field values to extract periods
            i = 0
            while i < len(field_values):
                field_val = field_values[i]
                
                # Look for "Through:" entries
                if field_val.startswith("Through:"):
                    if current_period:
                        periods.append(current_period)
                    
                    current_period = {
                        "through_date": field_val.replace("Through:", "").strip(),
                        "day_types": [],
                        "time_value_pairs": []
                    }
                
                # Look for "For:" entries  
                elif field_val.startswith("For:"):
                    if current_period:
                        current_day_type = {
                            "days": field_val.replace("For:", "").strip(),
                            "schedule": []
                        }
                        current_period["day_types"].append(current_day_type)
                
                # Look for "Until:" entries followed by values
                elif field_val.startswith("Until:") and current_period and current_period["day_types"]:
                    time_str = field_val.replace("Until:", "").strip()
                    # Next field should be the value
                    if i + 1 < len(field_values):
                        try:
                            value = float(field_values[i + 1])
                            current_period["day_types"][-1]["schedule"].append({
                                "until": time_str,
                                "value": value
                            })
                            i += 1  # Skip the value field in next iteration
                        except (ValueError, TypeError):
                            logger.warning(f"Invalid value after Until: {field_values[i + 1]}")
                
                i += 1
            
            # Add the last period
            if current_period:
                periods.append(current_period)
            
            # Calculate some summary statistics
            all_values = []
            for period in periods:
                for day_type in period["day_types"]:
                    for schedule_item in day_type["schedule"]:
                        all_values.append(schedule_item["value"])
            
            return {
                "format": "compact",
                "periods": periods,
                "total_periods": len(periods),
                "min_value": min(all_values) if all_values else 0.0,
                "max_value": max(all_values) if all_values else 0.0,
                "average_value": sum(all_values) / len(all_values) if all_values else 0.0,
                "total_time_value_pairs": len(all_values)
            }
            
        except Exception as e:
            logger.error(f"Error parsing Schedule:Compact values: {e}")
            return {"format": "compact", "error": str(e)}

    @staticmethod
    def parse_constant_schedule(schedule_obj) -> Dict[str, Any]:
        """
        Parse Schedule:Constant values
        
        Args:
            schedule_obj: eppy schedule object
            
        Returns:
            Dictionary with constant value
        """
        try:
            value = getattr(schedule_obj, 'Hourly_Value', 0.0)
            value = float(value) if value != '' else 0.0
            
            return {
                "format": "constant",
                "value": value,
                "description": f"Constant value {value} for all hours"
            }
            
        except Exception as e:
            logger.error(f"Error parsing Schedule:Constant values: {e}")
            return {"format": "constant", "error": str(e)}

    @classmethod
    def parse_schedule_values(cls, schedule_obj, object_type: str) -> Optional[Dict[str, Any]]:
        """
        Main entry point for parsing schedule values based on object type
        
        Args:
            schedule_obj: eppy schedule object
            object_type: Type of schedule object
            
        Returns:
            Dictionary with parsed values or None if not supported
        """
        try:
            if object_type == "Schedule:Day:Hourly":
                return cls.parse_day_hourly(schedule_obj)
            elif object_type == "Schedule:Day:Interval":
                return cls.parse_day_interval(schedule_obj)
            elif object_type == "Schedule:Day:List":
                return cls.parse_day_list(schedule_obj)
            elif object_type == "Schedule:Compact":
                return cls.parse_compact_schedule(schedule_obj)
            elif object_type == "Schedule:Constant":
                return cls.parse_constant_schedule(schedule_obj)
            else:
                # For Schedule:Year, Schedule:Week:*, etc. we don't extract values
                # as they are structural objects that reference other schedules
                return None
                
        except Exception as e:
            logger.error(f"Error parsing {object_type} values: {e}")
            return {"error": str(e)}


@dataclass
class SimpleScheduleFormat:
    """
    Simplified intermediate format for schedule modifications.
    Focuses on daily patterns with basic weekly/seasonal support.
    """
    name: str = ""
    schedule_type_limits: str = ""
    daily_pattern: List[Tuple[str, float]] = field(default_factory=list)  # [(time, value), ...]
    weekday_pattern: Optional[List[Tuple[str, float]]] = None
    weekend_pattern: Optional[List[Tuple[str, float]]] = None
    default_value: float = 0.0
    
    def __post_init__(self):
        if not self.daily_pattern:
            self.daily_pattern = [("00:00", self.default_value), ("24:00", self.default_value)]


class ScheduleLanguageParser:
    """Basic natural language parser for schedule modifications."""
    
    # Time patterns
    TIME_PATTERNS = {
        r'(\d{1,2}):?(\d{0,2})\s*(am|pm)': 'time_12h',
        r'(\d{1,2}):(\d{2})': 'time_24h',
        r'(\d{1,2})\s*(am|pm)': 'time_12h_simple',
        r'business\s+hours?': 'business_hours',
        r'office\s+hours?': 'business_hours',
        r'lunch\s+time': 'lunch_time',
        r'overnight': 'overnight',
        r'all\s+day': 'all_day'
    }
    
    # Day type patterns
    DAY_PATTERNS = {
        r'weekdays?': 'weekday',
        r'weekends?': 'weekend', 
        r'monday\s*-?\s*friday': 'weekday',
        r'sat\w*\s+sun\w*': 'weekend',
        r'holidays?': 'holiday',
        r'all\s+days?': 'all'
    }
    
    # Operation patterns
    OPERATION_PATTERNS = {
        r'set\s+to\s+([\d.]+)': 'set_value',
        r'increase\s+by\s+([\d.]+)%?': 'increase_percent',
        r'decrease\s+by\s+([\d.]+)%?': 'decrease_percent',
        r'turn\s+off': 'turn_off',
        r'turn\s+on': 'turn_on',
        r'reduce\s+by\s+([\d.]+)%?': 'decrease_percent'
    }
    
    @classmethod
    def parse_time_range(cls, text: str) -> Tuple[str, str]:
        """Parse time range from text like '8am-6pm' or '08:00-18:00'."""
        if not text or not isinstance(text, str):
            logger.warning("Invalid text input for time range parsing")
            return "08:00", "18:00"
        
        # Handle range patterns
        range_patterns = [
            r'(\d{1,2}):?(\d{0,2})\s*(am|pm)\s*[-–—]\s*(\d{1,2}):?(\d{0,2})\s*(am|pm)',
            r'(\d{1,2}):(\d{2})\s*[-–—]\s*(\d{1,2}):(\d{2})',
            r'from\s+(\d{1,2}):?(\d{0,2})\s*(am|pm)\s+to\s+(\d{1,2}):?(\d{0,2})\s*(am|pm)'
        ]
        
        for pattern in range_patterns:
            match = re.search(pattern, text.lower())
            if match:
                groups = match.groups()
                try:
                    if len(groups) >= 6:  # 12-hour format with am/pm
                        start_time = cls._convert_to_24h(groups[0], groups[1] or '00', groups[2])
                        end_time = cls._convert_to_24h(groups[3], groups[4] or '00', groups[5])
                    elif len(groups) >= 4:  # 24-hour format
                        start_time = f"{int(groups[0]):02d}:{groups[1]}"
                        end_time = f"{int(groups[2]):02d}:{groups[3]}"
                    else:
                        continue
                    
                    # Validate the times
                    if cls._validate_time_string(start_time) and cls._validate_time_string(end_time):
                        return start_time, end_time
                except Exception as e:
                    logger.warning(f"Error parsing time range from '{text}': {e}")
                    continue
        
        # Handle predefined patterns
        if 'business' in text.lower() or 'office' in text.lower():
            return "08:00", "18:00"
        elif 'lunch' in text.lower():
            return "12:00", "13:00"
        elif 'overnight' in text.lower():
            return "22:00", "06:00"
        elif 'morning' in text.lower():
            return "06:00", "12:00"
        elif 'afternoon' in text.lower():
            return "12:00", "18:00"
        elif 'evening' in text.lower():
            return "18:00", "22:00"
        
        # Default fallback
        return "08:00", "18:00"
    
    @classmethod
    def _convert_to_24h(cls, hour: str, minute: str, ampm: str) -> str:
        """Convert 12-hour time to 24-hour format."""
        try:
            hour = int(hour)
            minute = minute or '00'
            
            # Validate hour and minute
            if hour < 1 or hour > 12:
                raise ValueError(f"Invalid hour: {hour}")
            if int(minute) < 0 or int(minute) > 59:
                raise ValueError(f"Invalid minute: {minute}")
            
            if ampm.lower() == 'pm' and hour != 12:
                hour += 12
            elif ampm.lower() == 'am' and hour == 12:
                hour = 0
            
            return f"{hour:02d}:{minute}"
        except Exception as e:
            logger.warning(f"Error converting time {hour}:{minute} {ampm}: {e}")
            return "08:00"  # fallback
    
    @classmethod
    def _validate_time_string(cls, time_str: str) -> bool:
        """Validate time string format and values"""
        try:
            parts = time_str.split(':')
            if len(parts) != 2:
                return False
            hour, minute = int(parts[0]), int(parts[1])
            return 0 <= hour <= 24 and 0 <= minute <= 59
        except:
            return False
    
    @classmethod
    def parse_day_types(cls, text: str) -> List[str]:
        """Extract day types from text."""
        if not text or not isinstance(text, str):
            return ['all']
        
        day_types = []
        for pattern, day_type in cls.DAY_PATTERNS.items():
            if re.search(pattern, text.lower()):
                day_types.append(day_type)
        
        return day_types if day_types else ['all']
    
    @classmethod
    def parse_operation(cls, text: str) -> Tuple[str, Optional[float]]:
        """Extract operation and value from text."""
        if not text or not isinstance(text, str):
            return 'unknown', None
        
        for pattern, operation in cls.OPERATION_PATTERNS.items():
            match = re.search(pattern, text.lower())
            if match:
                try:
                    if operation in ['set_value', 'increase_percent', 'decrease_percent']:
                        value = float(match.group(1))
                        # Validate percentage values
                        if operation in ['increase_percent', 'decrease_percent'] and value < 0:
                            logger.warning(f"Negative percentage value: {value}, using absolute value")
                            value = abs(value)
                        return operation, value
                    elif operation == 'turn_off':
                        return operation, 0.0
                    elif operation == 'turn_on':
                        return operation, 1.0
                except (ValueError, IndexError) as e:
                    logger.warning(f"Error parsing operation value: {e}")
                    continue
        
        # Default - try to extract any number as a set value
        number_match = re.search(r'([\d.]+)', text)
        if number_match:
            try:
                value = float(number_match.group(1))
                return 'set_value', value
            except ValueError:
                pass
        
        return 'unknown', None
    
    @classmethod
    def parse_modification(cls, text: str) -> Dict[str, Any]:
        """Parse a complete modification instruction."""
        if not text or not isinstance(text, str):
            return {
                'operation': 'unknown',
                'value': None,
                'time_range': ("00:00", "24:00"),
                'day_types': ['all'],
                'original_text': text or '',
                'error': 'Invalid input text'
            }
        
        operation, value = cls.parse_operation(text)
        day_types = cls.parse_day_types(text)
        
        # Check if time range is specified
        # First check for "all hours", "all day", etc.
        if any(phrase in text.lower() for phrase in ['all hours', 'all day', 'all days', 'entire day', '24 hours']):
            start_time, end_time = "00:00", "24:00"
        elif any(word in text.lower() for word in ['from', 'during', '-', 'to', 'am', 'pm', ':']):
            start_time, end_time = cls.parse_time_range(text)
        else:
            start_time, end_time = "00:00", "24:00"  # Default to all day if not specified
        
        return {
            'operation': operation,
            'value': value,
            'time_range': (start_time, end_time),
            'day_types': day_types,
            'original_text': text
        }


class ScheduleConverter:
    """Convert between EnergyPlus schedule types and SimpleScheduleFormat."""
    
    @staticmethod
    def from_energyplus(schedule_obj, schedule_type: str) -> SimpleScheduleFormat:
        """Convert EnergyPlus schedule to SimpleScheduleFormat."""
        if not schedule_obj:
            logger.error("Invalid schedule object provided")
            return SimpleScheduleFormat()
        
        if not schedule_type:
            logger.error("Schedule type not provided")
            return SimpleScheduleFormat()
        
        ssf = SimpleScheduleFormat()
        ssf.name = getattr(schedule_obj, 'Name', 'Unknown')
        ssf.schedule_type_limits = getattr(schedule_obj, 'Schedule_Type_Limits_Name', '')
        
        try:
            if schedule_type == "Schedule:Constant":
                value = getattr(schedule_obj, 'Hourly_Value', 0.0)
                try:
                    value = float(value) if value not in [None, ''] else 0.0
                except (ValueError, TypeError):
                    logger.warning(f"Invalid constant value: {value}, using 0.0")
                    value = 0.0
                
                ssf.default_value = value
                ssf.daily_pattern = [("00:00", value), ("24:00", value)]
                
            elif schedule_type == "Schedule:Day:Hourly":
                hourly_values = []
                for hour in range(1, 25):
                    field_name = f"Hour_{hour}_Value" if hour > 1 else "Hour_1_Value"
                    try:
                        value = getattr(schedule_obj, field_name, 0.0)
                        value = float(value) if value not in [None, ''] else 0.0
                    except (ValueError, TypeError):
                        logger.warning(f"Invalid hourly value for {field_name}: {value}, using 0.0")
                        value = 0.0
                    hourly_values.append(value)
                
                # Convert hourly values to time-value pairs (compress consecutive same values)
                ssf.daily_pattern = ScheduleConverter._compress_hourly_values(hourly_values)
                
            elif schedule_type == "Schedule:Day:Interval":
                intervals = []
                for i in range(1, 50):
                    time_field = f"Time_{i}" if i > 1 else "Time_1"
                    value_field = f"Value_Until_Time_{i}" if i > 1 else "Value_Until_Time_1"
                    
                    time_val = getattr(schedule_obj, time_field, None)
                    value_val = getattr(schedule_obj, value_field, None)
                    
                    if time_val is None or time_val == '':
                        break
                    
                    time_str = str(time_val).replace("Until:", "").strip()
                    
                    # Validate time format
                    if not ScheduleValueParser._validate_time_format(time_str):
                        logger.warning(f"Invalid time format in interval: {time_str}, skipping")
                        continue
                    
                    try:
                        value = float(value_val) if value_val not in [None, ''] else 0.0
                    except (ValueError, TypeError):
                        logger.warning(f"Invalid interval value: {value_val}, using 0.0")
                        value = 0.0
                    
                    intervals.append((time_str, value))
                
                ssf.daily_pattern = intervals
                
            elif schedule_type == "Schedule:Compact":
                # Parse Schedule:Compact - handle the actual format where Until: time,value are combined
                intervals = []
                
                # Get all field values from the schedule object
                field_values = []
                if hasattr(schedule_obj, 'fieldnames'):
                    field_names = schedule_obj.fieldnames[2:]  # Skip Name and Schedule_Type_Limits_Name
                    for field_name in field_names:
                        try:
                            value = getattr(schedule_obj, field_name, None)
                            if value is not None and str(value).strip() != '':
                                field_values.append(str(value).strip())
                        except Exception:
                            continue
                
                # Parse field values looking for weekday schedule patterns
                in_weekday_section = False
                
                for field_val in field_values:
                    field_val = field_val.strip()
                    
                    # Check if we're entering a weekday section
                    if field_val.startswith("For:") and any(day in field_val.lower() for day in ['weekday', 'weekdays']):
                        in_weekday_section = True
                        continue
                    
                    # Check if we're entering a weekend section
                    elif field_val.startswith("For:") and any(day in field_val.lower() for day in ['weekend', 'weekends', 'holiday']):
                        in_weekday_section = False
                        continue
                    
                    # Parse Until: entries when in weekday section
                    elif in_weekday_section and field_val.startswith("Until:"):
                        # Format: "Until: 8:00,0.0" or "Until: 8:00" followed by separate value
                        until_part = field_val.replace("Until:", "").strip()
                        
                        if ',' in until_part:
                            # Combined format: "8:00,0.0"
                            try:
                                time_str, value_str = until_part.split(',', 1)
                                time_str = time_str.strip()
                                value = float(value_str.strip())
                                
                                # Normalize time format to HH:MM
                                if ':' in time_str and len(time_str.split(':')[0]) == 1:
                                    hour, minute = time_str.split(':')
                                    time_str = f"{int(hour):02d}:{minute}"
                                
                                intervals.append((time_str, value))
                            except (ValueError, IndexError) as e:
                                logger.warning(f"Could not parse Until entry: '{field_val}': {e}")
                        else:
                            # Time only, value might be in next field or standalone
                            time_str = until_part.strip()
                            
                            # Normalize time format to HH:MM
                            if ':' in time_str and len(time_str.split(':')[0]) == 1:
                                hour, minute = time_str.split(':')
                                time_str = f"{int(hour):02d}:{minute}"
                            
                            # Use a default value for now, this might need refinement
                            intervals.append((time_str, 0.0))
                    
                    # Handle standalone numeric values that might be schedule values
                    elif in_weekday_section and field_val.replace('.', '').replace('-', '').isdigit():
                        try:
                            value = float(field_val)
                            # If the previous interval has a 0.0 value, update it
                            if intervals and intervals[-1][1] == 0.0:
                                time_str, _ = intervals[-1]
                                intervals[-1] = (time_str, value)
                        except ValueError:
                            pass
                
                if intervals:
                    ssf.daily_pattern = intervals
                else:
                    # Fallback if parsing failed
                    logger.warning(f"Could not parse Schedule:Compact '{ssf.name}', using default pattern")
                    ssf.default_value = 1.0
                    ssf.daily_pattern = [("00:00", 1.0), ("24:00", 1.0)]
                
            else:
                # For other types, create a simple default pattern
                logger.warning(f"Unsupported schedule type for conversion: {schedule_type}")
                ssf.default_value = 1.0
                ssf.daily_pattern = [("00:00", 1.0), ("24:00", 1.0)]
        
        except Exception as e:
            logger.error(f"Error converting schedule from EnergyPlus: {e}")
            ssf.default_value = 0.0
            ssf.daily_pattern = [("00:00", 0.0), ("24:00", 0.0)]
        
        return ssf
    
    @staticmethod
    def _compress_hourly_values(hourly_values: List[float]) -> List[Tuple[str, float]]:
        """Compress hourly values into time-value pairs."""
        if not hourly_values:
            return [("00:00", 0.0), ("24:00", 0.0)]
        
        # Ensure we have exactly 24 values
        if len(hourly_values) != 24:
            logger.warning(f"Expected 24 hourly values, got {len(hourly_values)}")
            hourly_values = (hourly_values + [0.0] * 24)[:24]
        
        compressed = []
        current_value = hourly_values[0]
        
        for hour, value in enumerate(hourly_values):
            if value != current_value:
                compressed.append((f"{hour:02d}:00", current_value))
                current_value = value
        
        # Add final value
        compressed.append(("24:00", current_value))
        
        # Always start at 00:00
        if not compressed or compressed[0][0] != "00:00":
            compressed.insert(0, ("00:00", hourly_values[0]))
        
        return compressed
    
    @staticmethod
    def to_energyplus(ssf: SimpleScheduleFormat, target_type: str, idf_obj=None) -> Dict[str, Any]:
        """Convert SimpleScheduleFormat to EnergyPlus schedule object."""
        if not ssf or not target_type:
            logger.error("Invalid arguments for schedule conversion")
            return {}
        
        modifications = {}
        
        try:
            if target_type == "Schedule:Constant":
                # Use the most common value or default
                values = [value for _, value in ssf.daily_pattern]
                if values:
                    # Get most common value
                    most_common_value = max(set(values), key=values.count)
                else:
                    most_common_value = ssf.default_value
                modifications['Hourly_Value'] = most_common_value
                
            elif target_type == "Schedule:Day:Hourly":
                # Expand to 24 hourly values
                hourly_values = ScheduleConverter._expand_to_hourly(ssf.daily_pattern)
                for hour in range(24):
                    field_name = f"Hour_{hour + 1}_Value" if hour > 0 else "Hour_1_Value"
                    modifications[field_name] = hourly_values[hour]
                    
            elif target_type == "Schedule:Day:Interval":
                # Use the time-value pairs directly
                modifications['Interpolate_to_Timestep'] = 'No'
                
                # Limit to reasonable number of intervals (EnergyPlus limit)
                max_intervals = min(len(ssf.daily_pattern), 25)
                
                for i, (time_str, value) in enumerate(ssf.daily_pattern[:max_intervals]):
                    time_field = f"Time_{i + 1}" if i > 0 else "Time_1"
                    value_field = f"Value_Until_Time_{i + 1}" if i > 0 else "Value_Until_Time_1"
                    modifications[time_field] = time_str
                    modifications[value_field] = value
            
            elif target_type == "Schedule:Compact":
                # Create a Schedule:Compact format
                # Build the field values for a simple weekday/weekend pattern
                field_values = []
                
                # Add the period header
                field_values.append("Through: 12/31")
                field_values.append("For: WeekDays SummerDesignDay CustomDay1 CustomDay2")
                
                # Add time-value pairs
                for time_str, value in ssf.daily_pattern:
                    field_values.append(f"Until: {time_str},{value}")
                
                # Add weekend schedule (simplified to 0.0 for all times)
                field_values.append("For: Weekends WinterDesignDay Holiday")
                field_values.append("Until: 24:00,0.0")
                
                # Set the fields in the modifications dictionary
                for i, field_value in enumerate(field_values):
                    field_name = f"Field_{i + 1}" if i > 0 else "Field_1"
                    modifications[field_name] = field_value
            
            else:
                logger.warning(f"Unsupported target schedule type: {target_type}")
                return {}
        
        except Exception as e:
            logger.error(f"Error converting schedule to EnergyPlus format: {e}")
            return {}
        
        return modifications
    
    @staticmethod
    def _expand_to_hourly(time_value_pairs: List[Tuple[str, float]]) -> List[float]:
        """Expand time-value pairs to 24 hourly values."""
        hourly_values = [0.0] * 24
        
        if not time_value_pairs:
            return hourly_values
        
        try:
            # Sort by time and validate
            valid_pairs = []
            for time_str, value in time_value_pairs:
                if ScheduleValueParser._validate_time_format(time_str):
                    valid_pairs.append((time_str, value))
                else:
                    logger.warning(f"Invalid time format in expansion: {time_str}")
            
            if not valid_pairs:
                return hourly_values
            
            sorted_pairs = sorted(valid_pairs, key=lambda x: x[0])
            
            current_value = sorted_pairs[0][1]
            for hour in range(24):
                hour_time = f"{hour:02d}:00"
                
                # Check if we need to update the current value
                for time_str, value in sorted_pairs:
                    if time_str <= hour_time:
                        current_value = value
                    else:
                        break
                
                hourly_values[hour] = current_value
        
        except Exception as e:
            logger.error(f"Error expanding to hourly values: {e}")
            return [0.0] * 24
        
        return hourly_values
    
    @staticmethod
    def apply_modification(ssf: SimpleScheduleFormat, modification: Dict[str, Any]) -> SimpleScheduleFormat:
        """Apply a modification to a SimpleScheduleFormat."""
        if not ssf or not modification:
            logger.error("Invalid arguments for applying modification")
            return ssf
        
        try:
            operation = modification.get('operation', 'unknown')
            value = modification.get('value', 0.0)
            time_range = modification.get('time_range', ("00:00", "24:00"))
            day_types = modification.get('day_types', ['all'])
            
            if len(time_range) != 2:
                logger.warning("Invalid time range format, using full day")
                time_range = ("00:00", "24:00")
            
            start_time, end_time = time_range
            
            # Validate time range
            if not (ScheduleValueParser._validate_time_format(start_time) and 
                   ScheduleValueParser._validate_time_format(end_time)):
                logger.warning(f"Invalid time range: {start_time}-{end_time}, using full day")
                start_time, end_time = "00:00", "24:00"
            
            # For now, handle simple daily modifications (ignore day types)
            if operation == 'set_value':
                ssf.daily_pattern = ScheduleConverter._set_value_in_range(
                    ssf.daily_pattern, start_time, end_time, value
                )
                
            elif operation == 'increase_percent':
                if value is None or value < 0:
                    logger.warning(f"Invalid percentage value: {value}")
                    return ssf
                ssf.daily_pattern = ScheduleConverter._apply_percentage_change(
                    ssf.daily_pattern, start_time, end_time, value, increase=True
                )
                
            elif operation == 'decrease_percent':
                if value is None or value < 0:
                    logger.warning(f"Invalid percentage value: {value}")
                    return ssf
                ssf.daily_pattern = ScheduleConverter._apply_percentage_change(
                    ssf.daily_pattern, start_time, end_time, value, increase=False
                )
                
            elif operation == 'turn_off':
                ssf.daily_pattern = ScheduleConverter._set_value_in_range(
                    ssf.daily_pattern, start_time, end_time, 0.0
                )
                
            elif operation == 'turn_on':
                ssf.daily_pattern = ScheduleConverter._set_value_in_range(
                    ssf.daily_pattern, start_time, end_time, 1.0
                )
            
            else:
                logger.warning(f"Unknown operation: {operation}")
        
        except Exception as e:
            logger.error(f"Error applying modification: {e}")
        
        return ssf
    
    @staticmethod
    def _apply_percentage_change(pattern: List[Tuple[str, float]], start_time: str, 
                               end_time: str, percentage: float, increase: bool) -> List[Tuple[str, float]]:
        """Apply percentage change to values in a time range."""
        new_pattern = []
        multiplier = 1 + (percentage / 100) if increase else 1 - (percentage / 100)
        
        for time_str, value in pattern:
            if start_time <= time_str < end_time:
                new_value = value * multiplier
                new_pattern.append((time_str, new_value))
            else:
                new_pattern.append((time_str, value))
        
        return new_pattern
    
    @staticmethod
    def _set_value_in_range(pattern: List[Tuple[str, float]], start_time: str, 
                          end_time: str, new_value: float) -> List[Tuple[str, float]]:
        """Set a specific value in a time range."""
        if not pattern:
            return [(start_time, new_value), (end_time, 0.0)]
        
        new_pattern = []
        
        # Add all intervals before the modification start time
        for time_str, value in pattern:
            if time_str < start_time:
                new_pattern.append((time_str, value))
        
        # Add the modification interval
        new_pattern.append((start_time, new_value))
        
        # If end_time is not 24:00, we need to restore the original value after the modification
        if end_time != "24:00":
            # Find what value should be restored after the modification
            restore_value = 0.0  # default
            for time_str, value in pattern:
                if time_str <= end_time:
                    restore_value = value
                else:
                    break
            
            new_pattern.append((end_time, restore_value))
        
        # Add all intervals after the modification end time
        for time_str, value in pattern:
            if time_str > end_time:
                new_pattern.append((time_str, value))
        
        return new_pattern
    
    @staticmethod
    def determine_optimal_type(ssf: SimpleScheduleFormat) -> str:
        """Determine the optimal EnergyPlus schedule type for the given pattern."""
        # Count unique values
        values = [value for _, value in ssf.daily_pattern]
        unique_values = set(values)
        
        if len(unique_values) == 1:
            return "Schedule:Constant"
        elif len(ssf.daily_pattern) <= 4:
            return "Schedule:Day:Interval"
        else:
            return "Schedule:Day:Hourly"


 
