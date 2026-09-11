"""Master tools registration.

Each tool group exposes `register(mcp, ep_manager, config)`.
Use `register_all` to register all master tools based on config.
"""
from typing import Any


def register_all(mcp: Any, ep_manager: Any, config: Any) -> None:
    from . import inspect as _inspect
    from . import outputs as _outputs
    from . import modify as _modify
    from . import hvac_loop as _hvac_loop

    _inspect.register(mcp, ep_manager, config)
    _outputs.register(mcp, ep_manager, config)
    _modify.register(mcp, ep_manager, config)
    _hvac_loop.register(mcp, ep_manager, config)
