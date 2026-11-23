"""Deprecated compatibility import for generic semantic parameter planning.

Workflow-specific behavior lives outside this module.  It remains only for
older in-process consumers while the optional ``calibration_manager`` façade
is retired.
"""

from .model_parameters import *  # noqa: F401,F403
