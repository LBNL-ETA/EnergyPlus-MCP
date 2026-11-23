"""Launch the EnergyPlus command line as an isolated child process.

eppy's ``IDF.run`` changes the server's working directory and swaps
``sys.stderr`` for the duration of a run. Both are process-wide, so two
overlapping runs (or a run plus any other tool) can interfere, and its verbose
mode prints to stdout, which is the JSON-RPC channel under the stdio
transport. Here each run gets its own working directory, log file, and process
group instead, so any number can run at once and a timeout or cancel can stop
EnergyPlus together with the helpers it spawns.
"""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from typing import IO, Optional, Sequence


def build_command(
    executable: str,
    idf_path: str | Path,
    output_directory: str | Path,
    *,
    weather: Optional[str] = None,
    idd: Optional[str] = None,
    annual: bool = False,
    design_day: bool = False,
    readvars: bool = False,
    expandobjects: bool = False,
    output_prefix: Optional[str] = None,
    output_suffix: Optional[str] = None,
) -> list[str]:
    """Return the ``energyplus`` argument list with absolute paths.

    Like eppy, ExpandObjects is enabled automatically when the model contains
    HVACTemplate objects, which EnergyPlus cannot simulate without it.
    """
    idf = Path(idf_path).resolve()
    if not expandobjects:
        expandobjects = "HVACTEMPLATE:" in idf.read_text(errors="replace").upper()
    command = [executable, "--output-directory", str(Path(output_directory).resolve())]
    if weather:
        command += ["--weather", str(Path(weather).resolve())]
    if idd and Path(idd).is_file():
        command += ["--idd", str(Path(idd).resolve())]
    if annual:
        command.append("--annual")
    if design_day:
        command.append("--design-day")
    if readvars:
        command.append("--readvars")
    if expandobjects:
        command.append("--expandobjects")
    if output_prefix:
        command += ["--output-prefix", output_prefix]
    if output_suffix:
        command += ["--output-suffix", output_suffix]
    command.append(str(idf))
    return command


def start(command: Sequence[str], cwd: str | Path, log: IO[str]) -> subprocess.Popen:
    """Start EnergyPlus in ``cwd`` with stdout and stderr sent to ``log``."""
    return subprocess.Popen(  # noqa: S603 - executable comes from server configuration
        list(command),
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        # Own process group: stopping the run also stops ExpandObjects,
        # ReadVarsESO, and other helpers, and never signals the server.
        start_new_session=(os.name == "posix"),
    )


def stop(process: subprocess.Popen, grace_seconds: float = 5.0) -> None:
    """Terminate a run's process group, escalating to kill after ``grace_seconds``."""
    if process.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    else:
        process.terminate()
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
        else:
            process.kill()
        process.wait()


def run(
    command: Sequence[str],
    cwd: str | Path,
    log_path: str | Path,
    timeout_seconds: Optional[float] = None,
) -> int:
    """Run EnergyPlus to completion and return its exit code.

    Raises ``subprocess.TimeoutExpired`` after stopping the process group when
    ``timeout_seconds`` elapses.
    """
    with open(log_path, "w", encoding="utf-8") as log:
        process = start(command, cwd, log)
        try:
            return process.wait(timeout=timeout_seconds or None)
        except subprocess.TimeoutExpired:
            stop(process)
            raise
