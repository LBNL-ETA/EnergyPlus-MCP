"""Queued, concurrent EnergyPlus runs, exercised with a stand-in executable.

The fake ``energyplus`` sleeps, writes EnergyPlus-style outputs, and logs its
start/end time and working directory, so the tests can check overlap, the
concurrency cap, cancellation, timeouts, and the calibration layout without an
EnergyPlus installation. A model line ``! FAKE sleep=1 exit=1`` sets its
behavior.
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from energyplus_mcp_server.energyplus_tools import EnergyPlusManager
from energyplus_mcp_server.tools import simulation as simulation_tool
from energyplus_mcp_server.utils import energyplus_process
from energyplus_mcp_server.utils.error_parser import ErrorParser
from energyplus_mcp_server.utils.simulation_queue import (
    SimulationQueue,
    mark_interrupted_runs,
    server_identity,
)

FAKE_ENERGYPLUS = """#!{python}
import json, os, pathlib, sys, time
args = sys.argv[1:]
def option(name):
    return args[args.index(name) + 1] if name in args else None
out = pathlib.Path(option("--output-directory"))
prefix, suffix = option("--output-prefix"), option("--output-suffix") or "L"
idf = pathlib.Path(args[-1])
directives = {{}}
for line in idf.read_text().splitlines():
    if line.startswith("! FAKE"):
        directives.update(part.split("=") for part in line.split()[2:])
start = time.time()
time.sleep(float(directives.get("sleep", 0)))
base = (prefix or "eplus") + ("out" if suffix == "L" else "")
code = int(directives.get("exit", 0))
if code:
    (out / f"{{base}}.err").write_text("   ** Severe  ** fake severe\\n   **  Fatal  ** fake fatal\\n")
else:
    (out / f"{{base}}.err").write_text("   ************* EnergyPlus Completed Successfully.\\n")
    (out / f"{{base}}.sql").write_text("sql")
    (out / f"{{base}}.end").write_text("EnergyPlus Completed Successfully")
with open(os.environ["FAKE_EP_LOG"], "a") as log:
    log.write(json.dumps({{"idf": str(idf), "cwd": os.getcwd(), "args": args,
                           "start": start, "end": time.time()}}) + "\\n")
sys.exit(code)
"""


class FakeIDF:
    def __init__(self, path, epw=None):
        self.path = path

    def save(self, target):
        shutil.copy(self.path, target)


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self, *args, **kwargs):
        def decorate(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorate


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    executable = tmp_path / "energyplus"
    executable.write_text(FAKE_ENERGYPLUS.format(python=sys.executable))
    executable.chmod(0o755)
    log = tmp_path / "fake_energyplus.jsonl"
    monkeypatch.setenv("FAKE_EP_LOG", str(log))
    monkeypatch.setattr("energyplus_mcp_server.energyplus_tools.IDF", FakeIDF)
    root = tmp_path / "server"
    (root / "sample_files" / "basic").mkdir(parents=True)

    def make_manager(max_concurrency=4, timeout=0):
        config = SimpleNamespace(
            paths=SimpleNamespace(
                workspace_root=str(root),
                sample_files_path=str(root / "sample_files"),
                output_dir=str(root / "work" / "runs"),
                uploads_dir=str(root / "work" / "models" / "uploads"),
                derived_models_dir=str(root / "work" / "models" / "derived"),
                reports_dir=str(root / "work" / "reports"),
            ),
            energyplus=SimpleNamespace(
                executable_path=str(executable), idd_path="", installation_path="",
                example_files_path="", weather_data_path="",
            ),
            server=SimpleNamespace(simulation_timeout=timeout, max_concurrent_simulations=max_concurrency),
        )
        manager = EnergyPlusManager.__new__(EnergyPlusManager)
        manager.config = config
        manager.error_parser = ErrorParser()
        manager.simulation_queue = SimulationQueue(max_concurrency, timeout)
        manager._resolve_idf_path = lambda path: str(Path(path).resolve())
        manager._ensure_output_sqlite = lambda idf: None
        manager._ensure_calibration_outputs = lambda idf: None
        manager._assert_simulation_version_matches = lambda path: {"model_version": "26.1"}
        return manager

    def model(name, directives=""):
        path = root / "sample_files" / "basic" / f"{name}.idf"
        path.write_text(f"! FAKE {directives}\nVersion,26.1;\n")
        return path

    def launches():
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text().splitlines()]

    return SimpleNamespace(root=root, make_manager=make_manager, model=model, launches=launches)


def _max_overlap(launches):
    events = sorted([(item["start"], 1) for item in launches] + [(item["end"], -1) for item in launches])
    running = peak = 0
    for _, change in events:
        running += change
        peak = max(peak, running)
    return peak


def test_runs_overlap_in_isolated_directories(workspace):
    manager = workspace.make_manager(max_concurrency=3)
    models = [workspace.model(f"Box{i}", "sleep=1") for i in range(3)]

    started = time.monotonic()
    jobs = [manager.submit_simulation(str(path), annual=False, design_day=True) for path in models]
    for job in jobs:
        manager.simulation_queue.wait_sync(job)
    elapsed = time.monotonic() - started

    assert elapsed < 2.5
    assert _max_overlap(workspace.launches()) == 3
    assert len({job.output_directory for job in jobs}) == 3
    for job, launch in zip(jobs, sorted(workspace.launches(), key=lambda item: item["idf"])):
        assert job.status == "completed" and job.result["success"]
        assert Path(launch["cwd"]).resolve() == job.output_directory.resolve()
        assert json.loads(job.record_path.read_text())["status"] == "completed"
    # Nothing was written beside the read-only source models.
    assert sorted(p.name for p in models[0].parent.iterdir()) == ["Box0.idf", "Box1.idf", "Box2.idf"]


def test_concurrency_cap_is_respected(workspace):
    manager = workspace.make_manager(max_concurrency=1)
    jobs = [manager.submit_simulation(str(workspace.model(f"Cap{i}", "sleep=0.4"))) for i in range(3)]
    for job in jobs:
        manager.simulation_queue.wait_sync(job)

    assert _max_overlap(workspace.launches()) == 1
    assert all(job.status == "completed" for job in jobs)


def test_run_calls_do_not_block_the_server(workspace):
    manager = workspace.make_manager(max_concurrency=3)
    mcp = FakeMCP()
    simulation_tool.register(mcp, manager, manager.config)
    tool = mcp.tools["simulation_manager"]
    models = [workspace.model(f"Tool{i}", "sleep=1") for i in range(3)]

    async def exercise():
        ticks = 0
        stop = asyncio.Event()

        async def ticker():
            nonlocal ticks
            while not stop.is_set():
                await asyncio.sleep(0.1)
                ticks += 1

        ticking = asyncio.create_task(ticker())
        started = time.monotonic()
        results = await asyncio.gather(*(tool(action="run", idf_path=str(path)) for path in models))
        elapsed = time.monotonic() - started
        stop.set()
        await ticking
        return results, elapsed, ticks

    results, elapsed, ticks = asyncio.run(exercise())
    assert elapsed < 2.5
    assert ticks >= 8  # the event loop kept running during the simulations
    for text in results:
        assert text.startswith("Simulation run complete:")
        assert json.loads(text.split("\n", 1)[1])["success"]


def test_run_batch_submit_wait_and_status(workspace):
    manager = workspace.make_manager(max_concurrency=2)
    mcp = FakeMCP()
    simulation_tool.register(mcp, manager, manager.config)
    tool = mcp.tools["simulation_manager"]
    fast, slow = workspace.model("Fast", "sleep=0.2"), workspace.model("Slow", "sleep=1.5")

    async def exercise():
        batch = json.loads(await tool(action="run_batch", runs=[
            {"idf_path": str(fast)},
            {"idf_path": str(fast), "design_day": True},
            {"idf_path": str(fast), "output_directory": "sample_files/basic/out"},
        ]))
        submitted = json.loads(await tool(action="submit", idf_path=str(slow)))
        early = json.loads(await tool(action="wait", run_id=submitted["run_id"], timeout_seconds=0.2))
        done = json.loads(await tool(action="wait", run_id=submitted["run_id"]))
        status = json.loads(await tool(action="status", run_ids=[submitted["run_id"]]))
        overview = json.loads(await tool(action="status"))
        return batch, submitted, early, done, status, overview

    batch, submitted, early, done, status, overview = asyncio.run(exercise())
    assert batch["submitted"] == 2 and batch["completed"] == 2 and batch["pending"] == []
    assert batch["submission_errors"][0]["index"] == 2
    assert "read-only" in batch["submission_errors"][0]["error"]
    assert submitted["status"] in ("queued", "running")
    assert early["finished"] == [] and early["pending"][0]["run_id"] == submitted["run_id"]
    assert done["finished"][0]["status"] == "completed"
    assert status["runs"][0]["result"]["success"]
    assert overview["max_concurrent_simulations"] == 2 and overview["running"] == []


def test_cancel_queued_and_running_runs(workspace):
    manager = workspace.make_manager(max_concurrency=1)
    queue = manager.simulation_queue
    running = manager.submit_simulation(str(workspace.model("Long", "sleep=30")))
    queued = manager.submit_simulation(str(workspace.model("Waiting", "sleep=30")))
    deadline = time.monotonic() + 5
    while running.status != "running" and time.monotonic() < deadline:
        time.sleep(0.05)

    assert queue.cancel(queued.run_id).status == "cancelled"
    started = time.monotonic()
    queue.cancel(running.run_id)
    queue.wait_sync(running)

    assert time.monotonic() - started < 8
    assert running.status == "cancelled" and not running.result["success"]
    assert json.loads(queued.record_path.read_text())["status"] == "cancelled"
    assert workspace.launches() == []  # stopped before the fake logged, and the queued run never launched


def test_timeout_stops_the_run(workspace):
    manager = workspace.make_manager(max_concurrency=1, timeout=1)
    job = manager.submit_simulation(str(workspace.model("Slowpoke", "sleep=30")))
    started = time.monotonic()
    manager.simulation_queue.wait_sync(job)

    assert time.monotonic() - started < 8
    assert job.status == "failed"
    assert "limit" in job.result["error"]


def test_failed_run_reports_the_fatal_error(workspace):
    manager = workspace.make_manager()
    job = manager.submit_simulation(str(workspace.model("Broken", "exit=1")))
    manager.simulation_queue.wait_sync(job)
    status = manager.simulation_status(job)

    assert job.status == "failed"
    assert "exited with code 1" in job.result["error"] and "Fatal" in job.result["error"]
    assert status["error_summary"]["counts"]["fatal"] == 1


def test_calibration_layout_records_each_status(workspace, tmp_path):
    manager = workspace.make_manager()
    runs_dir = workspace.root / "work" / "runs" / "campaign"
    source = workspace.model("Candidate", "sleep=0.2")

    job = manager.submit_simulation(str(source), runs_dir=str(runs_dir), run_id="cand-001")
    queued_record = json.loads((runs_dir / "cand-001" / "run_record.json").read_text())
    manager.simulation_queue.wait_sync(job)
    record = json.loads((runs_dir / "cand-001" / "run_record.json").read_text())
    launch = workspace.launches()[0]

    assert queued_record["status"] in ("queued", "running")
    assert record["status"] == "completed" and record["run_id"] == "cand-001"
    assert record["eplusout_sql"] == str(runs_dir / "cand-001" / "run" / "eplusout.sql")
    assert isinstance(record["started_at"], float) and record["finished_at"] >= record["started_at"]
    assert launch["args"][-1] == str((runs_dir / "cand-001" / "in.idf").resolve())
    assert Path(launch["cwd"]).resolve() == (runs_dir / "cand-001" / "run").resolve()
    assert job.result["eplusout_sql"].endswith("run/eplusout.sql")


def test_busy_output_directory_is_refused(workspace):
    manager = workspace.make_manager(max_concurrency=1)
    first = manager.submit_simulation(str(workspace.model("Shared", "sleep=1")), output_directory="work/runs/shared")

    with pytest.raises(RuntimeError, match="in use"):
        manager.submit_simulation(str(workspace.model("Other")), output_directory="work/runs/shared")
    manager.simulation_queue.wait_sync(first)
    assert first.status == "completed"


def test_orphaned_records_are_marked_interrupted(tmp_path):
    finished = subprocess.Popen([sys.executable, "-c", "pass"])
    finished.wait()
    orphan = tmp_path / "orphan" / "run_record.json"
    live = tmp_path / "campaign" / "live" / "run_record.json"
    for path, pid in ((orphan, finished.pid), (live, os.getpid())):
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"run_id": path.parent.name, "status": "running",
                                    **server_identity(), "server_pid": pid}))

    marked = mark_interrupted_runs(tmp_path)

    assert marked == [str(orphan)]
    assert json.loads(orphan.read_text())["status"] == "interrupted"
    assert json.loads(live.read_text())["status"] == "running"


def test_command_enables_expandobjects_for_hvac_templates(tmp_path):
    model = tmp_path / "templated.idf"
    model.write_text("Version,26.1;\nHVACTemplate:Thermostat,T,,20,,24;\n")

    command = energyplus_process.build_command("energyplus", model, tmp_path / "out", weather=None)

    assert "--expandobjects" in command
    assert command[-1] == str(model.resolve())
