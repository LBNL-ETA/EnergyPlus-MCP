"""
EnergyPlus MCP Server Package

EnergyPlus Model Context Protocol Server (EnergyPlus-MCP)
Copyright (c) 2025, The Regents of the University of California,
through Lawrence Berkeley National Laboratory (subject to receipt of
any required approvals from the U.S. Dept. of Energy). All rights reserved.

See License.txt in the parent directory for license details.
"""

# Memoize eppy's field-name helpers before anything parses an IDF.
from .utils import eppy_speedups as _eppy_speedups

_eppy_speedups.apply()

from .energyplus_tools import EnergyPlusManager  # noqa: E402
from .config import Config, get_config  # noqa: E402

__version__ = "0.2.0"
__all__ = ["EnergyPlusManager", "Config", "get_config"]