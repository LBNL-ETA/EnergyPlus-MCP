"""Run MCP tool bodies in worker threads so they never block the event loop.

FastMCP awaits each tool on the server's single event loop. Most tools here
are ``async def`` but do synchronous eppy and file work, so awaiting them
directly would stall every other request, including other callers' tools and
``/health``. ``guard_tool`` (see ``output_guard``) therefore runs each tool in
a worker thread through :func:`run_tool_in_thread`, unless the tool is marked
:func:`native_async`.

Thread safety
-------------
eppy keeps the IDD at class level (``IDF.setiddname``, ``IDF.idd_info``,
``IDF.block``), and parsing a model fills in missing extensible-field keys in
that shared IDD data. Tools also share in-process caches. A worker thread
therefore holds :data:`EPPY_LOCK` for the whole tool call, so eppy-using tools
still run one at a time, exactly as they did on the event loop, but without
holding up anything else. ``EnergyPlusManager`` takes the same lock when it
stages a simulation from ``simulation_manager``'s own worker thread. The lock
is reentrant because a locked tool may stage a simulation itself.

Tools that never touch eppy or the shared caches are marked
:func:`eppy_free` and run without the lock.

Caller identity
---------------
``asyncio.to_thread`` runs the function in a copy of the caller's
``contextvars`` context, so ``scope.current_label()`` (the MCP request context
and ``auth``'s token label) sees the same caller inside the thread.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable, Coroutine

# Process-wide lock around eppy model parsing and editing.
EPPY_LOCK = threading.RLock()

_NATIVE_ASYNC = "__mcp_native_async__"
_EPPY_FREE = "__mcp_eppy_free__"


def native_async(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Mark a tool that awaits real asynchronous work; it stays on the event loop.

    Such a tool must move its own blocking work off the loop, for example with
    ``asyncio.to_thread``.
    """
    setattr(fn, _NATIVE_ASYNC, True)
    return fn


def eppy_free(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Mark a tool that never uses eppy or shared model caches; it runs without EPPY_LOCK."""
    setattr(fn, _EPPY_FREE, True)
    return fn


def is_native_async(fn: Callable[..., Any]) -> bool:
    return bool(getattr(fn, _NATIVE_ASYNC, False))


def is_eppy_free(fn: Callable[..., Any]) -> bool:
    return bool(getattr(fn, _EPPY_FREE, False))


def _drive(make_coroutine: Callable[[], Coroutine[Any, Any, Any]]) -> Any:
    """Run a coroutine that does no real awaiting to completion in this thread."""
    coroutine = make_coroutine()
    try:
        coroutine.send(None)
    except StopIteration as done:
        return done.value
    # The tool suspended on something only an event loop can resume.
    coroutine.close()
    raise RuntimeError(
        "a threaded MCP tool awaited asynchronous work; mark it @native_async "
        "and move its blocking work off the event loop itself"
    )


def _call(fn: Callable[..., Any], args: tuple, kwargs: dict, locked: bool) -> Any:
    def invoke() -> Any:
        if asyncio.iscoroutinefunction(fn):
            return _drive(lambda: fn(*args, **kwargs))
        return fn(*args, **kwargs)

    if not locked:
        return invoke()
    with EPPY_LOCK:
        return invoke()


async def run_tool_in_thread(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run ``fn`` (sync, or async without real awaits) in a worker thread."""
    return await asyncio.to_thread(_call, fn, args, kwargs, not is_eppy_free(fn))


async def run_eppy_in_thread(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """For ``native_async`` tools: run synchronous eppy work in a thread under EPPY_LOCK."""
    return await asyncio.to_thread(_call, fn, args, kwargs, True)
