"""Domain manager tool registration.

Each domain module exposes `register(mcp, ep_manager, config)` which defines
and registers its tools using the provided FastMCP instance.
"""

from typing import Any
import logging

logger = logging.getLogger(__name__)


def register_all(mcp: Any, ep_manager: Any, config: Any,
                 envelope: bool = True,
                 internal_loads: bool = True,
                 hvac: bool = True,
                 outputs: bool = False) -> None:
    logger.info("Registering domain managers: envelope=%s, internal_loads=%s, hvac=%s", envelope, internal_loads, hvac)
    if envelope:
        from . import envelope as _env
        _env.register(mcp, ep_manager, config)
        logger.info("Registered envelope_manager tool")
    if internal_loads:
        from . import internal_loads as _il
        _il.register(mcp, ep_manager, config)
        logger.info("Registered internal_load_manager tool")
    if hvac:
        from . import hvac as _hv
        _hv.register(mcp, ep_manager, config)
        logger.info("Registered hvac_manager tool")
    if outputs:
        from . import outputs as _out
        _out.register(mcp, ep_manager, config)
        logger.info("Registered outputs_manager tool")
