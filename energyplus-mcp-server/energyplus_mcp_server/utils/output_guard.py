"""Check every registered MCP tool's output arguments in one place.

Tools receive their destinations through a few argument names. Wrapping each
tool at registration checks those arguments, so a new tool with an
``output_path`` is covered without remembering to call the check itself:

- Over stdio, outputs may not point into the read-only input trees; the
  argument is passed through unchanged.
- Over streamable-http, the argument is replaced by an absolute path inside
  the caller's own workspace (relative paths are taken relative to it), so a
  tool never sees a destination outside that workspace.
"""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable

from .path_utils import resolve_output_location

OUTPUT_ARGUMENTS = ("output_path", "output_directory", "target_path", "runs_dir")


def guard_tool(fn: Callable[..., Any], config: Any) -> Callable[..., Any]:
    """Validate, and over HTTP confine, a tool's output arguments before it runs."""
    signature = inspect.signature(fn)
    guarded = [name for name in OUTPUT_ARGUMENTS if name in signature.parameters]
    if not guarded:
        return fn

    def check(args: tuple, kwargs: dict) -> tuple[tuple, dict]:
        bound = signature.bind_partial(*args, **kwargs)
        for name in guarded:
            value = bound.arguments.get(name)
            if isinstance(value, str) and value.strip():
                bound.arguments[name] = resolve_output_location(config, value, description=name)
        return bound.args, bound.kwargs

    # functools.wraps sets __wrapped__, so FastMCP still builds the tool schema
    # from the original signature and docstring.
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            args, kwargs = check(args, kwargs)
            return await fn(*args, **kwargs)

        return async_wrapper

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        args, kwargs = check(args, kwargs)
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
