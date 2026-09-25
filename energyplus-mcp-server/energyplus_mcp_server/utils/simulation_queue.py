"""Queue EnergyPlus runs and execute up to a configured number at once.

A submitted run is staged first (its own run directory and ``in.idf``), then
queued. Worker threads launch each run as a separate EnergyPlus process (see
``energyplus_process``), so tool calls return control to the server while
simulations run, and several simulations can overlap.

Every status change is written to the run's ``run_record.json``:
``queued`` -> ``running`` -> ``completed`` | ``failed`` | ``cancelled``.
A record left ``queued`` or ``running`` by a server process that no longer
exists is marked ``interrupted`` when a later server starts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import subprocess
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import energyplus_process

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = frozenset({"queued", "running"})
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted"})


def default_max_concurrency() -> int:
    """Leave one CPU for the server and the agent's other tool calls."""
    return max(1, (os.cpu_count() or 2) - 1)


def write_record(path: Path, record: dict[str, Any]) -> None:
    """Replace ``path`` atomically so readers never see a partial record."""
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporary.write_text(json.dumps(record, indent=2))
    os.replace(temporary, path)


@dataclass(eq=False)
class SimulationJob:
    """One staged EnergyPlus run and its lifecycle.

    ``finalize`` builds the tool's result dictionary once the process has
    ended (or was never started); it reads ``exit_code`` and ``error`` and may
    add fields to ``record``.
    """

    run_id: str
    name: str
    command: list[str]
    output_directory: Path
    record_path: Path
    record: dict[str, Any]
    finalize: Callable[["SimulationJob"], dict[str, Any]]
    log_path: Optional[Path] = None
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    pid: Optional[int] = None
    exit_code: Optional[int] = None
    error: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    cancel_requested: bool = False
    done: threading.Event = field(default_factory=threading.Event)
    future: Optional[Future] = None
    process: Optional[subprocess.Popen] = None

    def __post_init__(self) -> None:
        if self.log_path is None:
            self.log_path = self.output_directory / "energyplus.log"

    def summary(self) -> dict[str, Any]:
        now = time.time()
        end = self.ended_at or now
        return {
            "run_id": self.run_id,
            "name": self.name,
            "status": self.status,
            "output_directory": str(self.output_directory),
            "run_record": str(self.record_path),
            "queued_seconds": round((self.started_at or end) - self.created_at, 1),
            "elapsed_seconds": round(end - self.started_at, 1) if self.started_at else None,
            "exit_code": self.exit_code,
            "error": self.error,
        }


class SimulationQueue:
    """FIFO queue with a cap on simultaneous EnergyPlus processes."""

    def __init__(self, max_concurrency: Optional[int] = None, timeout_seconds: float = 0) -> None:
        self.max_concurrency = max(1, int(max_concurrency or default_max_concurrency()))
        self.timeout_seconds = max(0.0, float(timeout_seconds or 0))
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_concurrency, thread_name_prefix="energyplus-run"
        )
        self._lock = threading.RLock()
        self._jobs: dict[str, SimulationJob] = {}

    # -- submission -----------------------------------------------------

    def ensure_available(self, run_id: str, output_directory: Path) -> None:
        """Raise if an active run already uses ``run_id`` or ``output_directory``."""
        with self._lock:
            existing = self._jobs.get(run_id)
            if existing is not None and existing.status in ACTIVE_STATUSES:
                raise ValueError(f"run_id is already queued or running: {run_id}")
            directory = Path(output_directory).resolve()
            for other in self._jobs.values():
                if other.status in ACTIVE_STATUSES and other.output_directory.resolve() == directory:
                    raise ValueError(
                        f"output_directory is in use by active run {other.run_id}: {directory}"
                    )

    def submit(self, job: SimulationJob) -> SimulationJob:
        """Register ``job`` and queue it; raises if its run_id or directory is busy."""
        with self._lock:
            self.ensure_available(job.run_id, job.output_directory)
            self._jobs[job.run_id] = job
            job.status = "queued"
            self._persist(job, queued_at=job.created_at)
            job.future = self._executor.submit(self._execute, job)
        return job

    def add_finished(self, job: SimulationJob) -> SimulationJob:
        """Track a run that failed during staging, so status and wait can report it."""
        with self._lock:
            self._jobs[job.run_id] = job
        job.done.set()
        return job

    # -- execution ------------------------------------------------------

    def _execute(self, job: SimulationJob) -> None:
        with self._lock:
            if job.cancel_requested:
                self._finish(job, "cancelled", "Simulation cancelled before it started")
                return
            job.status = "running"
            job.started_at = time.time()
        timed_out = False
        try:
            with open(job.log_path, "w", encoding="utf-8") as log:
                process = energyplus_process.start(job.command, job.output_directory, log)
                with self._lock:
                    job.process = process
                    job.pid = process.pid
                    self._persist(job, started_at=job.started_at, pid=process.pid)
                    cancelled = job.cancel_requested
                if cancelled:
                    energyplus_process.stop(process)
                try:
                    job.exit_code = process.wait(timeout=self.timeout_seconds or None)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    energyplus_process.stop(process)
                    job.exit_code = process.wait()
        except Exception as error:  # launch failure, e.g. missing executable
            logger.error("Simulation %s could not run: %s", job.run_id, error)
            self._finish(job, "failed", f"Could not start EnergyPlus: {error}")
            return

        if job.cancel_requested:
            self._finish(job, "cancelled", "Simulation cancelled while running")
        elif timed_out:
            self._finish(
                job,
                "failed",
                f"Simulation exceeded the {self.timeout_seconds:.0f} s limit "
                "(MCP_SIMULATION_TIMEOUT_SECONDS) and was stopped",
            )
        else:
            self._finish(job, None, None)

    def _finish(self, job: SimulationJob, status: Optional[str], error: Optional[str]) -> None:
        """Record the outcome; ``status=None`` lets ``finalize`` decide from the outputs."""
        job.ended_at = time.time()
        job.error = error
        try:
            job.result = job.finalize(job)
        except Exception as finalize_error:
            logger.error("Could not finalize simulation %s: %s", job.run_id, finalize_error)
            job.result = {"success": False, "error": f"Could not read simulation results: {finalize_error}"}
        if status is None:
            status = "completed" if job.result.get("success") else "failed"
            job.error = job.error or job.result.get("error")
        job.result.update({"run_id": job.run_id, "status": status, "run_record": str(job.record_path)})
        with self._lock:
            job.status = status
            job.process = None
            try:
                self._persist(
                    job,
                    finished_at=job.ended_at,
                    exit_code=job.exit_code,
                    **({"error": job.error} if job.error else {}),
                )
            except OSError as persist_error:
                # The run record is the budget and evidence source for
                # calibration, so a failed write must be visible.
                job.result["record_error"] = f"Could not write run_record.json: {persist_error}"
                logger.error("Could not write run record for %s: %s", job.run_id, persist_error)
        job.done.set()

    def _persist(self, job: SimulationJob, **fields: Any) -> None:
        job.record.update(fields)
        job.record["status"] = job.status
        write_record(job.record_path, job.record)

    # -- control and inspection ------------------------------------------

    def get(self, run_id: str) -> Optional[SimulationJob]:
        with self._lock:
            return self._jobs.get(run_id)

    def cancel(self, run_id: str) -> Optional[SimulationJob]:
        """Cancel a queued or running run; a finished run is returned unchanged."""
        with self._lock:
            job = self._jobs.get(run_id)
            if job is None or job.status not in ACTIVE_STATUSES:
                return job
            job.cancel_requested = True
            process = job.process
            if job.status == "queued" and job.future is not None and job.future.cancel():
                self._finish(job, "cancelled", "Simulation cancelled before it started")
                return job
        if process is not None:
            energyplus_process.stop(process)
        return job

    def overview(self, recent: int = 20) -> dict[str, Any]:
        with self._lock:
            jobs = list(self._jobs.values())
        running = [job.run_id for job in jobs if job.status == "running"]
        queued = [job.run_id for job in jobs if job.status == "queued"]
        finished = sorted(
            (job for job in jobs if job.status in TERMINAL_STATUSES),
            key=lambda job: job.ended_at or 0,
            reverse=True,
        )
        return {
            "max_concurrent_simulations": self.max_concurrency,
            "timeout_seconds": self.timeout_seconds or None,
            "running": running,
            "queued": queued,
            "recently_finished": [job.summary() for job in finished[:recent]],
        }

    async def wait(
        self, run_ids: Iterable[str], mode: str = "all", timeout_seconds: Optional[float] = None
    ) -> tuple[list[SimulationJob], list[SimulationJob]]:
        """Wait without blocking the event loop; returns (finished, pending) jobs."""
        jobs = []
        for run_id in run_ids:
            job = self.get(run_id)
            if job is None:
                raise KeyError(run_id)
            jobs.append(job)
        deadline = None if timeout_seconds is None else time.monotonic() + max(0.0, timeout_seconds)
        while True:
            finished = [job for job in jobs if job.done.is_set()]
            satisfied = len(finished) == len(jobs) or (mode == "any" and finished)
            if satisfied or (deadline is not None and time.monotonic() >= deadline):
                return finished, [job for job in jobs if not job.done.is_set()]
            await asyncio.sleep(0.2)

    def wait_sync(self, job: SimulationJob) -> SimulationJob:
        job.done.wait()
        return job


def _process_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def server_identity() -> dict[str, Any]:
    """Stamped on each record so a later server can tell whose runs were orphaned."""
    return {"server_pid": os.getpid(), "server_host": socket.gethostname()}


def mark_interrupted_runs(root: str | Path, depth: int = 2) -> list[str]:
    """Mark ``queued``/``running`` records whose server process is gone.

    Records owned by a live server (for example another stdio session sharing
    the same work area) and records from another host are left alone.
    """
    root = Path(root)
    if not root.is_dir():
        return []
    host = socket.gethostname()
    patterns = ["/".join(["*"] * level + ["run_record.json"]) for level in range(1, depth + 1)]
    marked = []
    for pattern in patterns:
        for path in root.glob(pattern):
            try:
                record = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if record.get("status") not in ACTIVE_STATUSES:
                continue
            if record.get("server_host") != host or _process_alive(record.get("server_pid")):
                continue
            record["status"] = "interrupted"
            record["error"] = "The server stopped before this run finished"
            record["finished_at"] = time.time()
            try:
                write_record(path, record)
                marked.append(str(path))
            except OSError:
                continue
    return marked
