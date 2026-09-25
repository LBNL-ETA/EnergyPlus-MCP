from typing import Any, Dict, List, Optional, Literal
import asyncio
import json

from energyplus_mcp_server.utils.path_utils import check_writable_path

# Per-run settings a run_batch entry may override; the rest come from the call.
RUN_FIELDS = (
    "idf_path", "weather_file", "output_directory", "annual", "design_day", "readvars",
    "expandobjects", "include_sqlite_output", "runs_dir", "run_id",
)


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    @mcp.tool()
    async def simulation_manager(
        action: Literal[
            "run", "submit", "run_batch", "status", "wait", "cancel",
            "update_settings", "update_run_period", "capabilities",
        ],
        idf_path: Optional[str] = None,
        weather_file: Optional[str] = None,
        output_directory: Optional[str] = None,
        annual: bool = True,
        design_day: bool = False,
        readvars: bool = True,
        expandobjects: bool = True,
        settings: Optional[Dict[str, Any]] = None,
        run_period: Optional[Dict[str, Any]] = None,
        run_period_index: int = 0,
        run_id: Optional[str] = None,
        runs_dir: Optional[str] = None,
        detail: Literal["summary", "detailed"] = "summary",
        include_sqlite_output: bool = True,
        runs: Optional[List[Dict[str, Any]]] = None,
        run_ids: Optional[List[str]] = None,
        wait_for: Literal["all", "any"] = "all",
        timeout_seconds: Optional[float] = None,
    ) -> str:
        """Run EnergyPlus simulations, one at a time or several in parallel.

        Simulations go through a shared queue that runs up to
        max_concurrent_simulations EnergyPlus processes at once (see
        action="status"); the server stays responsive while they run.

        Actions:
            run: Run one simulation and return its result when it finishes.
                Several run calls made in parallel execute concurrently.
            submit: Queue one simulation and return its run_id immediately;
                follow with wait or status.
            run_batch: Queue every entry in ``runs`` (each a dict with idf_path
                and optional weather_file, output_directory, runs_dir, run_id,
                annual, design_day, ...; missing keys come from this call's
                arguments), then wait up to timeout_seconds (default: until all
                finish; 0 returns the run_ids at once). Use this for
                calibration candidates or parametric variants.
            status: With run_id or run_ids, report each run's state
                (queued, running, completed, failed, cancelled, interrupted)
                and, once finished, its result. runs_dir finds a calibration
                run that this server process is not tracking. Without ids,
                report the queue.
            wait: Wait for run_ids (wait_for="all" or "any") up to
                timeout_seconds (default 600), then report finished and
                pending runs.
            cancel: Cancel run_id or run_ids, queued or running.
            update_settings / update_run_period: Edit SimulationControl or
                RunPeriod in a copy of the model.

        runs_dir with run_id writes the calibration evidence layout
        <runs_dir>/<run_id>/run_record.json and run/eplusout.sql. Every run
        writes run_record.json, updated at each status change.
        """
        queue = ep_manager.simulation_queue

        def run_kwargs(entry: Dict[str, Any]) -> Dict[str, Any]:
            defaults = {
                "idf_path": idf_path, "weather_file": weather_file,
                "output_directory": output_directory, "annual": annual,
                "design_day": design_day, "readvars": readvars,
                "expandobjects": expandobjects,
                "include_sqlite_output": include_sqlite_output,
                "runs_dir": runs_dir, "run_id": run_id,
            }
            unknown = set(entry) - set(RUN_FIELDS)
            if unknown:
                raise ValueError(f"Unsupported run fields: {sorted(unknown)}; allowed: {list(RUN_FIELDS)}")
            merged = {**defaults, **entry}
            # Batch entries bypass the tool-argument guard, so check them here.
            for name in ("output_directory", "runs_dir"):
                if merged.get(name):
                    check_writable_path(config, merged[name], description=name)
            return merged

        def report(jobs: List[Any]) -> List[Dict[str, Any]]:
            return [ep_manager.simulation_status(job) for job in jobs]

        def requested_ids() -> List[str]:
            return list(run_ids or ([run_id] if run_id else []))

        if action == "capabilities":
            return json.dumps({
                "tool": "simulation_manager",
                "actions": [
                    {"name": "run", "required": ["idf_path"], "optional": ["weather_file", "output_directory", "annual", "design_day", "readvars", "expandobjects", "include_sqlite_output", "runs_dir", "run_id"]},
                    {"name": "submit", "required": ["idf_path"], "optional": ["weather_file", "output_directory", "annual", "design_day", "readvars", "expandobjects", "include_sqlite_output", "runs_dir", "run_id"]},
                    {"name": "run_batch", "required": ["runs"], "optional": ["timeout_seconds", "weather_file", "runs_dir", "annual", "design_day", "readvars", "expandobjects", "include_sqlite_output"]},
                    {"name": "status", "optional": ["run_id", "run_ids", "runs_dir"]},
                    {"name": "wait", "required": ["run_id or run_ids"], "optional": ["wait_for", "timeout_seconds"]},
                    {"name": "cancel", "required": ["run_id or run_ids"]},
                    {"name": "update_settings", "required": ["idf_path", "settings"]},
                    {"name": "update_run_period", "required": ["idf_path", "run_period"], "optional": ["run_period_index"]},
                ],
                "max_concurrent_simulations": queue.max_concurrency,
                "timeout_seconds": queue.timeout_seconds or None,
                "detail": detail,
            }, indent=2)

        if action in ("run", "submit"):
            if not idf_path:
                return "Missing required parameter: idf_path"
            job = await asyncio.to_thread(ep_manager.submit_simulation, **run_kwargs({}))
            if action == "submit":
                return json.dumps(ep_manager.simulation_status(job), indent=2)
            await queue.wait([job.run_id])
            return f"Simulation run complete:\n{json.dumps(job.result, indent=2)}"

        if action == "run_batch":
            if not runs:
                return json.dumps({"error": "run_batch requires runs: a list of run dicts with idf_path"})
            jobs, errors = [], []
            for index, entry in enumerate(runs):
                try:
                    kwargs = run_kwargs(dict(entry))
                    if not kwargs.get("idf_path"):
                        raise ValueError("idf_path is required")
                    jobs.append(await asyncio.to_thread(ep_manager.submit_simulation, **kwargs))
                except Exception as error:
                    errors.append({"index": index, "error": str(error)})
            finished, pending = await queue.wait([job.run_id for job in jobs], "all", timeout_seconds)
            return json.dumps({
                "submitted": len(jobs),
                "completed": sum(job.status == "completed" for job in finished),
                "failed": sum(job.status != "completed" for job in finished),
                "pending": [job.run_id for job in pending],
                "runs": report(jobs),
                "submission_errors": errors,
            }, indent=2)

        if action == "status":
            ids = requested_ids()
            if not ids:
                return json.dumps(queue.overview(), indent=2)
            statuses = []
            for requested in ids:
                job = queue.get(requested)
                if job is not None:
                    statuses.append(ep_manager.simulation_status(job))
                    continue
                record = ep_manager.find_run_record(requested, runs_dir)
                statuses.append(
                    {"run_id": requested, "tracked_by_this_server": False, **record}
                    if record else {"run_id": requested, "status": "unknown", "error": "No such run"}
                )
            return json.dumps({"runs": statuses}, indent=2)

        if action == "wait":
            ids = requested_ids()
            if not ids:
                return json.dumps({"error": "wait requires run_id or run_ids"})
            try:
                finished, pending = await queue.wait(ids, wait_for, 600 if timeout_seconds is None else timeout_seconds)
            except KeyError as missing:
                return json.dumps({"error": f"Run is not tracked by this server: {missing.args[0]}"})
            return json.dumps({
                "finished": report(finished),
                "pending": [job.summary() for job in pending],
            }, indent=2)

        if action == "cancel":
            ids = requested_ids()
            if not ids:
                return json.dumps({"error": "cancel requires run_id or run_ids"})
            results = []
            for requested in ids:
                job = queue.cancel(requested)
                results.append(job.summary() if job else {"run_id": requested, "error": "Run is not tracked by this server"})
            return json.dumps({"runs": results}, indent=2)

        if action == "update_settings":
            if not idf_path or not isinstance(settings, dict) or not settings:
                return "Missing required parameters: idf_path, settings"
            result = ep_manager.modify_simulation_settings(idf_path=idf_path, object_type="SimulationControl", field_updates=settings, output_path=None)
            return f"SimulationControl updated:\n{result}"
        if action == "update_run_period":
            if not idf_path or not isinstance(run_period, dict) or not run_period:
                return "Missing required parameters: idf_path, run_period"
            result = ep_manager.modify_simulation_settings(idf_path=idf_path, object_type="RunPeriod", field_updates=run_period, run_period_index=int(run_period_index or 0), output_path=None)
            return f"RunPeriod updated:\n{result}"
        return f"Unsupported action: {action}"
