#!/usr/bin/env python3
"""Resume a qualified native-IDF calibration project through both MCPs.

Every sweep is generated non-cumulatively from the current committed IDF.
Calibration-MCP owns pattern selection, ladder completion, scoring, and state;
EnergyPlus-MCP owns bounded IDF mutations and physical simulations.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import traceback
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp import StdioServerParameters

from run_native_idf_calibration_pilot import (
    Audit,
    REQUIRED_PARAMETERS,
    call,
    connect,
    convergence_branch,
    load_manifest,
    select_pattern,
    sha256,
    tool_data,
    validate_run_period_calendar,
)


def safe_token(value: Any) -> str:
    return str(value).replace("-", "m").replace(".", "p").replace(" ", "_")


def server_parameters(
    repo: Path,
    calibration_repo: Path,
    campaign: Path,
    image: str,
) -> tuple[StdioServerParameters, StdioServerParameters]:
    ep_env = {
        "MCP_CONFIG_PATH": str(repo / "energyplus-mcp-server/config.yaml"),
        "WORKSPACE_ROOT": str(repo / "energyplus-mcp-server"),
        "MPLCONFIGDIR": str(campaign / "mpl"),
        "XDG_CACHE_HOME": str(campaign / "cache"),
        # Never let uv replace the host macOS .venv through the bind mount.
        "UV_PROJECT_ENVIRONMENT": "/tmp/energyplus-mcp-venv",
    }
    ep = StdioServerParameters(
        command="docker",
        args=[
            "run", "--rm", "-i", "-v", f"{repo}:{repo}",
            "-w", str(repo / "energyplus-mcp-server"),
            *sum((["-e", f"{key}={value}"] for key, value in ep_env.items()), []),
            image, "uv", "run", "python", "-m", "energyplus_mcp_server.server",
        ],
    )
    calibration = StdioServerParameters(
        command=str(calibration_repo / ".venv/bin/python"),
        args=["-m", "calibration_mcp.server"],
        cwd=str(calibration_repo),
        env={
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(calibration_repo / "src"),
            "CALIBRATION_MCP_HOME": str(campaign / "calibration-workspace"),
        },
    )
    return ep, calibration


def current_checkpoint(project: dict[str, Any]) -> tuple[str, Path, dict[str, Any]]:
    best = project.get("current_best") or {}
    run_id = best.get("run_id")
    model = Path(best.get("model_path") or "")
    metrics = best.get("metrics")
    if not run_id or not model.is_file() or not isinstance(metrics, dict):
        raise RuntimeError("calibration-MCP did not return a resumable current-best checkpoint")
    if best.get("model_sha256") != sha256(model):
        raise RuntimeError("current-best IDF hash no longer matches the calibration ledger")
    return run_id, model, metrics


async def run(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = args.manifest.resolve()
    manifest = load_manifest(manifest_path)
    repo = args.repo.resolve()
    calibration_repo = args.calibration_repo.resolve()
    campaign = manifest_path.parent
    runs = campaign / "runs"
    models = campaign / "models"
    if not runs.is_dir():
        raise RuntimeError(f"campaign runs directory is missing: {runs}")
    models.mkdir(parents=True, exist_ok=True)
    audit = Audit(campaign / "continuation-audit.jsonl")
    ep_params, cal_params = server_parameters(
        repo, calibration_repo, campaign, args.image,
    )
    calibration = manifest["calibration"]
    weather = Path(manifest["weather"]["path"])
    sweeps: list[dict[str, Any]] = []
    status = "sweep_limit_checkpoint"

    async with AsyncExitStack() as stack:
        ep = await connect(stack, ep_params)
        cal = await connect(stack, cal_params)
        project = await call(
            cal, audit, "calibration", "get_project", project_id=args.project_id,
        )
        if Path(project["meta"]["runs_dir"]).resolve() != runs.resolve():
            raise RuntimeError("project runs_dir does not match this campaign")
        if project["meta"].get("backend") != "energyplus":
            raise RuntimeError("resume requires an EnergyPlus-backed calibration project")

        for _ in range(args.max_sweeps):
            incoming_run_id, current_model, incoming_metrics = current_checkpoint(project)
            branch = convergence_branch(
                incoming_metrics, calibration["convergence_mode"],
            )
            if branch != "not_converged":
                status = f"{branch}_converged"
                break

            caps = await call(
                ep, audit, "energyplus", "calibration_manager",
                action="capabilities", idf_path=str(current_model),
            )
            preflight = await call(
                ep, audit, "energyplus", "model_preflight",
                action="info", idf_path=str(current_model),
            )
            validate_run_period_calendar(
                preflight, manifest["weather"]["calendar_year"],
            )
            supported = {
                name for name, declaration in caps["parameters"].items()
                if declaration.get("supported") and declaration.get("coverage") == "complete"
            }
            if supported != REQUIRED_PARAMETERS:
                raise RuntimeError(
                    f"current-best model lost native calibration coverage: {sorted(supported)}"
                )
            elec_pattern = tool_data(await call(
                cal, audit, "calibration", "detect_patterns",
                project_id=args.project_id, run_id=incoming_run_id, fuel="elec",
            ))
            gas_pattern = tool_data(await call(
                cal, audit, "calibration", "detect_patterns",
                project_id=args.project_id, run_id=incoming_run_id, fuel="gas",
            ))
            selected_pattern = select_pattern(elec_pattern, gas_pattern)
            if selected_pattern is None:
                status = "no_detectable_pattern_checkpoint"
                break
            bias_pattern, bias_sign, pattern_evidence = selected_pattern
            selection = tool_data(await call(
                cal, audit, "calibration", "pick_parameter",
                project_id=args.project_id,
                bias_pattern=bias_pattern,
                bias_sign=bias_sign,
            ))
            parameter = selection.get("chosen_param")
            direction = selection.get("direction")
            if not parameter or direction not in {"increase", "decrease"}:
                status = "no_available_parameter_checkpoint"
                await call(
                    cal, audit, "calibration", "evaluate_termination",
                    project_id=args.project_id,
                )
                report = await call(
                    cal, audit, "calibration", "finalize_report",
                    project_id=args.project_id,
                    allow_ratio_outlier=bool(
                        calibration.get("allow_source_qualified_ratio_outlier", False)
                    ),
                )
                status = "parameters_exhausted"
                project = await call(
                    cal, audit, "calibration", "get_project",
                    project_id=args.project_id,
                )
                project["final_report"] = report
                break

            progress = tool_data(await call(
                cal, audit, "calibration", "sweep_progress",
                project_id=args.project_id,
                parameter=parameter,
                direction=direction,
            ))
            expected_values = progress["missing_values"]
            budget = tool_data(await call(
                cal, audit, "calibration", "calibration_progress",
                project_id=args.project_id,
                needed=len(expected_values),
            ))
            if not budget.get("can_start_batch"):
                status = "insufficient_budget_checkpoint"
                break

            project_summary = project.get("ledger_summary") or {}
            sweep_number = int(project_summary.get("committed_sweep_count") or 0) + 1
            inspection = await call(
                ep, audit, "energyplus", "calibration_manager",
                action="inspect", idf_path=str(current_model), parameter=parameter,
            )
            candidates = []
            for rung, value in enumerate(expected_values, start=1):
                progress = tool_data(await call(
                    cal, audit, "calibration", "sweep_progress",
                    project_id=args.project_id,
                    parameter=parameter,
                    direction=direction,
                ))
                if progress.get("next_value") != value:
                    raise RuntimeError(
                        f"authoritative next rung changed: expected {value}, "
                        f"got {progress.get('next_value')}"
                    )
                bounded = await call(
                    cal, audit, "calibration", "get_bound_repair_recipe",
                    project_id=args.project_id,
                    parameter=parameter,
                    inspection=inspection,
                    percentage_change=value,
                )
                recipes = bounded.get("recipes") or []
                if not recipes:
                    raise RuntimeError(
                        f"bounded {parameter} rung {value} is a no-op; repair the "
                        "boundary before spending a simulation"
                    )
                recipe = recipes[0]
                token = safe_token(value)
                candidate_model = models / (
                    f"sweep-{sweep_number:02d}-{parameter}-{rung:02d}-{token}.idf"
                )
                mutation_args = dict(recipe["arguments"])
                mutation_args.update(
                    idf_path=str(current_model), output_path=str(candidate_model),
                )
                mutation = await call(
                    ep, audit, "energyplus", recipe["tool_name"], **mutation_args,
                )
                if not mutation.get("changes"):
                    raise RuntimeError(f"{parameter} rung {value} made no IDF change")
                run_id = f"sweep-{sweep_number:02d}-{parameter.lower()}-{rung:02d}"
                simulation = await call(
                    ep, audit, "energyplus", "simulation_manager",
                    action="run", idf_path=str(candidate_model),
                    weather_file=str(weather), runs_dir=str(runs),
                    run_id=run_id, readvars=False,
                )
                record = tool_data(await call(
                    cal, audit, "calibration", "record_run",
                    project_id=args.project_id,
                    run_id=run_id,
                    kind="candidate",
                    parameter=parameter,
                    value=str(value),
                    decision="rejected",
                    model_path=str(candidate_model),
                    seed_model_path=str(current_model),
                    use_selection=True,
                    assert_new=True,
                    allow_ratio_outlier=bool(
                        calibration.get("allow_source_qualified_ratio_outlier", False)
                    ),
                ))
                candidates.append({
                    "run_id": run_id,
                    "value": value,
                    "model_path": str(candidate_model),
                    "model_sha256": sha256(candidate_model),
                    "metrics": record["run"]["metrics"],
                    "bounded_operation": recipe["arguments"],
                    "simulation_success": simulation.get("success"),
                })

            final_progress = tool_data(await call(
                cal, audit, "calibration", "sweep_progress",
                project_id=args.project_id,
                parameter=parameter,
                direction=direction,
            ))
            if not final_progress.get("can_close"):
                raise RuntimeError("complete physical ladder cannot be closed")
            commit = tool_data(await call(
                cal, audit, "calibration", "commit_sweep",
                project_id=args.project_id,
                parameter=parameter,
                incoming_run_id=incoming_run_id,
                allow_ratio_outlier=bool(
                    calibration.get("allow_source_qualified_ratio_outlier", False)
                ),
            ))
            sweeps.append({
                "sweep_number": sweep_number,
                "incoming_run_id": incoming_run_id,
                "incoming_metrics": incoming_metrics,
                "pattern": {
                    "bias_pattern": bias_pattern,
                    "bias_sign": bias_sign,
                    "evidence": pattern_evidence,
                },
                "selection": selection,
                "parameter": parameter,
                "direction": direction,
                "expected_values": expected_values,
                "candidates": candidates,
                "commit": commit,
            })
            project = await call(
                cal, audit, "calibration", "get_project", project_id=args.project_id,
            )
        else:
            incoming_run_id, _, metrics = current_checkpoint(project)
            branch = convergence_branch(metrics, calibration["convergence_mode"])
            if branch != "not_converged":
                status = f"{branch}_converged"

    final_project = project
    summary = {
        "status": status,
        "project_id": args.project_id,
        "manifest": str(manifest_path),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "sweeps_completed_this_invocation": len(sweeps),
        "sweeps": sweeps,
        "final_project": final_project,
        "audit_log": str(audit.path),
    }
    (campaign / "continuation-summary.json").write_text(
        json.dumps(summary, indent=2, allow_nan=True) + "\n", encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--max-sweeps", type=int, default=1)
    parser.add_argument(
        "--repo", type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--calibration-repo", type=Path,
        default=Path(
            "/Users/hanli/Documents/projects/Openstudio-AI/"
            "pattern-based-BEM-calibration-mcp"
        ),
    )
    parser.add_argument(
        "--image", default="energyplus-mcp-dev:26.1.0-upgrade-20260910",
    )
    args = parser.parse_args()
    if args.max_sweeps < 1:
        parser.error("--max-sweeps must be at least 1")
    try:
        result = asyncio.run(run(args))
    except Exception as error:
        print(f"continuation failed: {error}", file=sys.stderr)
        traceback.print_exception(error)
        return 1
    print(json.dumps(result, indent=2, allow_nan=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
