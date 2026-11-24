"""Tools run off the event loop, keep eppy serialized, and keep the caller's scope."""

import ast
import asyncio
import inspect
import textwrap
import threading
import time

import httpx
import pytest

from energyplus_mcp_server.auth import _token_label
from energyplus_mcp_server.utils.output_guard import GuardedMCP, guard_tool
from energyplus_mcp_server.utils.tool_threads import (
    EPPY_LOCK,
    eppy_free,
    is_native_async,
    native_async,
)
from tests.test_scope import ALICE_TOKEN, BOB_TOKEN, _free_port, http_config  # noqa: F401
from tests.test_tool_surface import FakeMCP


def _on_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


# --- the wrapper -------------------------------------------------------------

async def test_tool_body_runs_in_a_worker_thread():
    async def tool() -> tuple:
        return threading.get_ident(), _on_event_loop()

    thread_id, on_loop = await guard_tool(tool, config=None)()
    assert thread_id != threading.get_ident()
    assert on_loop is False


async def test_native_async_tool_stays_on_the_loop():
    @native_async
    async def tool() -> tuple:
        await asyncio.sleep(0)
        return threading.get_ident(), _on_event_loop()

    assert await guard_tool(tool, config=None)() == (threading.get_ident(), True)


async def test_threaded_tool_that_awaits_fails_loudly():
    async def tool() -> None:
        await asyncio.sleep(0)

    with pytest.raises(RuntimeError, match="native_async"):
        await guard_tool(tool, config=None)()


async def test_slow_tool_does_not_block_a_concurrent_tool():
    async def slow() -> str:
        time.sleep(0.6)
        return "slow"

    @eppy_free
    async def fast() -> str:
        return "fast"

    slow_call = asyncio.create_task(guard_tool(slow, config=None)())
    await asyncio.sleep(0.05)
    started = time.monotonic()
    assert await guard_tool(fast, config=None)() == "fast"
    assert time.monotonic() - started < 0.3
    assert not slow_call.done()
    assert await slow_call == "slow"


async def test_eppy_tools_take_turns_but_eppy_free_tools_do_not_wait():
    intervals = {}

    def recorder(name, seconds):
        async def tool() -> None:
            start = time.monotonic()
            time.sleep(seconds)
            intervals[name] = (start, time.monotonic())
        tool.__name__ = name
        return tool

    first, second = recorder("first", 0.3), recorder("second", 0.3)
    free = eppy_free(recorder("free", 0.05))
    await asyncio.gather(
        guard_tool(first, None)(), guard_tool(second, None)(), guard_tool(free, None)(),
    )
    (a0, a1), (b0, b1) = sorted([intervals["first"], intervals["second"]])
    assert b0 >= a1, "two eppy tools overlapped"
    f0, _ = intervals["free"]
    assert f0 < a1, "an eppy-free tool waited for the eppy lock"


def test_simulation_staging_shares_the_tool_lock_and_it_is_reentrant():
    from energyplus_mcp_server.energyplus_tools import EnergyPlusManager

    assert EnergyPlusManager._EPPY_LOCK is EPPY_LOCK
    # A locked tool (calibration) may stage a simulation in the same thread.
    with EPPY_LOCK:
        with EnergyPlusManager._EPPY_LOCK:
            pass


async def test_scope_follows_each_caller_into_the_worker_thread(http_config):  # noqa: F811
    from energyplus_mcp_server.scope import current_label, current_scope

    async def whoami() -> tuple:
        time.sleep(0.1)  # keep both calls in flight together
        return current_label(), current_scope(http_config).user_root, _on_event_loop()

    async def call_as(label):
        token = _token_label.set(label)
        try:
            return await guard_tool(whoami, http_config)()
        finally:
            _token_label.reset(token)

    alice, bob = await asyncio.gather(call_as("alice"), call_as("bob"))
    assert alice[0] == "alice" and alice[1].endswith("users/alice") and alice[2] is False
    assert bob[0] == "bob" and bob[1].endswith("users/bob") and bob[2] is False


def test_registered_tools_that_await_are_marked_native_async():
    """A tool that awaits must stay on the loop; every other tool is threaded."""
    from energyplus_mcp_server.tool_surface import register_tool_surface

    mcp = FakeMCP()
    surface = {
        "mode": "hybrid",
        "domains": {name: True for name in (
            "envelope", "internal_loads", "schedules", "hvac",
            "service_water", "outputs", "geometry",
        )},
        "compatibility": {"workflow_managers": True},
    }
    register_tool_surface(mcp, object(), object(), surface)
    tools = mcp._tool_manager._tools
    assert tools
    for name, wrapper in tools.items():
        assert inspect.iscoroutinefunction(wrapper), name
        original = wrapper.__wrapped__
        tree = ast.parse(textwrap.dedent(inspect.getsource(original)))
        awaits = any(
            isinstance(node, (ast.Await, ast.AsyncFor, ast.AsyncWith))
            for node in ast.walk(tree)
        )
        assert awaits == is_native_async(original), (
            f"{name}: mark it @native_async exactly when it awaits"
        )


# --- end to end over streamable-http -----------------------------------------

async def test_slow_tool_keeps_health_and_other_users_responsive(http_config):  # noqa: F811
    """A blocking tool call must not stall /health or another user's tool."""
    import uvicorn
    from sse_starlette.sse import AppStatus
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings
    from energyplus_mcp_server.http_app import build_app
    from energyplus_mcp_server.scope import current_label, current_scope

    fastmcp = FastMCP(
        "thread-test",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    mcp = GuardedMCP(fastmcp, http_config)
    slow_started = threading.Event()

    @mcp.tool()
    async def slow_whoami() -> str:
        slow_started.set()
        time.sleep(2.0)  # stands in for a large IDF load or capability scan
        return f"{current_label()}|{current_scope(http_config).user_root}"

    @mcp.tool()
    @eppy_free
    async def whoami() -> str:
        return f"{current_label()}|{current_scope(http_config).user_root}"

    # sse_starlette keeps one process-wide exit event, bound to the event loop
    # of whichever test server first streamed; give this server its own.
    AppStatus.should_exit_event = None
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(build_app(fastmcp, http_config),
                                           host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started
    url = f"http://127.0.0.1:{port}"

    async def call_as(token, tool):
        async with streamablehttp_client(
            f"{url}/mcp", headers={"Authorization": f"Bearer {token}"},
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, {})
                return result.content[0].text, time.monotonic()

    try:
        slow = asyncio.create_task(call_as(ALICE_TOKEN, "slow_whoami"))
        assert await asyncio.to_thread(slow_started.wait, 10)

        started = time.monotonic()
        async with httpx.AsyncClient(timeout=10) as client:
            health = await client.get(f"{url}/health")
        health_seconds = time.monotonic() - started
        assert health.status_code == 200
        assert health_seconds < 1.0, f"/health took {health_seconds:.2f}s behind a slow tool"

        bob_text, bob_done = await call_as(BOB_TOKEN, "whoami")
        alice_text, alice_done = await slow
        assert bob_done < alice_done, "another user's tool waited for the slow tool"
        assert bob_text.startswith("bob|") and bob_text.endswith("users/bob")
        assert alice_text.startswith("alice|") and alice_text.endswith("users/alice")
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        AppStatus.should_exit_event = None
