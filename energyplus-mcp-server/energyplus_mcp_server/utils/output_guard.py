"""Keep curated inputs read-only across every registered MCP tool.

Tools receive their destinations through a few argument names. Wrapping each
tool at registration checks those arguments in one place, so a new tool with an
``output_path`` is covered without remembering to call the check itself.
"""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable

from .path_utils import check_writable_path

OUTPUT_ARGUMENTS = ("output_path", "output_directory", "target_path", "runs_dir")


def guard_tool(fn: Callable[..., Any], config: Any) -> Callable[..., Any]:
    """Reject calls whose output arguments point into a read-only input tree."""
    signature = inspect.signature(fn)
    guarded = [name for name in OUTPUT_ARGUMENTS if name in signature.parameters]
    if not guarded:
        return fn

    def check(args: tuple, kwargs: dict) -> None:
        arguments = signature.bind_partial(*args, **kwargs).arguments
        for name in guarded:
            value = arguments.get(name)
            if isinstance(value, str) and value.strip():
                check_writable_path(config, value, description=name)

    # functools.wraps sets __wrapped__, so FastMCP still builds the tool schema
    # from the original signature and docstring.
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            check(args, kwargs)
            return await fn(*args, **kwargs)

        return async_wrapper

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        check(args, kwargs)
        return fn(*args, **kwargs)

    return wrapper


class GuardedMCP:
    """An MCP server proxy whose ``tool()`` decorator applies ``guard_tool``."""

    def __init__(self, mcp: Any, config: Any) -> None:
        self._mcp = mcp
        self._config = config

    def tool(self, *args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Any]:
        register = self._mcp.tool(*args, **kwargs)
        return lambda fn: register(guard_tool(fn, self._config))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._mcp, name)
