"""Check every registered MCP tool's output arguments in one place.

Tools receive their destinations through a few argument names. Wrapping each
tool at registration checks those arguments, so a new tool with an
``output_path`` is covered without remembering to call the check itself:

- Over stdio, outputs may not point into the read-only input trees; the
  argument is passed through unchanged.
- Over streamable-http, the argument is replaced by an absolute path inside
  the caller's own workspace (relative paths are taken relative to it), so a
  tool never sees a destination outside that workspace.

The same wrapper also moves each tool's synchronous work off the event loop
(see ``tool_threads``): tools run in a worker thread unless marked
``native_async``.

Finally it sends JSON replies without indentation (``compact_reply``). Tools
build their replies with ``json.dumps(..., indent=2)``; the indentation was 25
to 57 percent of each reply, and every reply is read by an agent. Set
``MCP_COMPACT_JSON=0`` to keep the tools' own formatting.
"""

from __future__ import annotations

import functools
import inspect
import json
import os
from typing import Any, Callable

from .path_utils import resolve_output_location
from .tool_threads import is_native_async, run_tool_in_thread

OUTPUT_ARGUMENTS = ("output_path", "output_directory", "target_path", "runs_dir")


def compact_reply(result: Any) -> Any:
    """Re-encode a JSON object/array reply without whitespace; leave anything else alone."""
    if not isinstance(result, str) or os.environ.get("MCP_COMPACT_JSON") == "0":
        return result
    text = result.lstrip()
    if not text.startswith(("{", "[")):
        return result
    try:
        parsed = json.loads(text)
    except ValueError:
        return result
    return json.dumps(parsed, separators=(",", ":"), ensure_ascii=False)


def guard_tool(fn: Callable[..., Any], config: Any) -> Callable[..., Any]:
    """Check a tool's output arguments, then run it without blocking the event loop.

    Output arguments are validated, and over HTTP confined, before the tool
    runs. The returned wrapper is always ``async``: tools marked
    ``native_async`` are awaited on the loop; every other tool runs in a
    worker thread (see ``tool_threads.run_tool_in_thread``).
    """
    signature = inspect.signature(fn)
    guarded = [name for name in OUTPUT_ARGUMENTS if name in signature.parameters]
    native = is_native_async(fn)
    if native and not inspect.iscoroutinefunction(fn):
        raise TypeError(f"{fn.__name__} is marked native_async but is not a coroutine function")

    def check(args: tuple, kwargs: dict) -> tuple[tuple, dict]:
        if not guarded:
            return args, kwargs
        bound = signature.bind_partial(*args, **kwargs)
        for name in guarded:
            value = bound.arguments.get(name)
            if isinstance(value, str) and value.strip():
                bound.arguments[name] = resolve_output_location(config, value, description=name)
        return bound.args, bound.kwargs

    # functools.wraps sets __wrapped__, so FastMCP still builds the tool schema
    # from the original signature and docstring.
    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        args, kwargs = check(args, kwargs)
        if native:
            return compact_reply(await fn(*args, **kwargs))
        return compact_reply(await run_tool_in_thread(fn, *args, **kwargs))

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
