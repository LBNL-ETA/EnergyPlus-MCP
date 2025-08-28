"""Master tools registration.

Each tool group exposes `register(mcp, ep_manager, config)`.
Use `register_all` to register all master tools based on config.
"""
from typing import Any


def register_all(mcp: Any, ep_manager: Any, config: Any) -> None:
    from . import inspect as _inspect
    from . import preflight as _preflight
    from . import outputs as _outputs
    from . import modify as _modify
    from . import simulation as _simulation
    from . import post as _post
    from . import files as _files
    from . import hvac_loop as _hvac_loop
    from . import server as _server

    _inspect.register(mcp, ep_manager, config)
    _preflight.register(mcp, ep_manager, config)
    _outputs.register(mcp, ep_manager, config)
    _modify.register(mcp, ep_manager, config)
    _simulation.register(mcp, ep_manager, config)
    _post.register(mcp, ep_manager, config)
    _files.register(mcp, ep_manager, config)
    _hvac_loop.register(mcp, ep_manager, config)
    _server.register(mcp, ep_manager, config)

