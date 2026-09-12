#!/usr/bin/env python3
"""Run a bounded two-server native-IDF semantic integration smoke.

The smoke applies one legacy parameter and one graph-aware schedule parameter,
simulates only the final copied IDF, and records its canonical SQL evidence
through Calibration-MCP.  It is deliberately not a calibration sweep.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import sys
import traceback
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import StdioServerParameters

from run_native_idf_calibration_pilot import (
    Audit,
    call,
    collect_domain_capabilities,
    connect,
    execute_provider_recipe,
    parse_tool_payload,
    sha256,
    tool_data,
)


async def expect_tool_rejection(session: Any, tool: str, **arguments: Any) -> str:
    """Return the provider error text and fail if a call unexpectedly succeeds."""
    try:
        parse_tool_payload(await session.call_tool(tool, arguments))
    except RuntimeError as error:
        return str(error)
    raise RuntimeError(f"{tool} unexpectedly accepted a partial-coverage recipe request")


def _lighting_declaration(capabilities: dict[str, Any]) -> dict[str, Any]:
    for group in capabilities["domain_capabilities"]:
        if group.get("tool") == "schedule_manager":
            return group["parameters"]["lighting_schedule"]
    raise RuntimeError("schedule_manager did not advertise lighting_schedule")


async def run(args: argparse.Namespace) -> dict[str, Any]:
    repo = args.repo.resolve()
    calibration_repo = args.calibration_repo.resolve()
    source = args.model.resolve()
    weather = args.weather.resolve()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    work = args.work_dir.resolve()
    runs = work / "runs"
    models = work / "models"
    calibration_home = work / "calibration-workspace"
    if work.exists() and any(work.iterdir()):
        raise RuntimeError(f"smoke work directory must be new or empty: {work}")
    for directory in (runs, models, calibration_home):
        directory.mkdir(parents=True, exist_ok=True)
    if not source.is_file() or not weather.is_file():
        raise RuntimeError("model and weather inputs must exist")
    source_hash = sha256(source)
    audit = Audit(work / "mcp-audit.jsonl")

    ep_env = {
        "MCP_CONFIG_PATH": str(repo / "energyplus-mcp-server/config.yaml"),
        "WORKSPACE_ROOT": str(repo / "energyplus-mcp-server"),
        "MPLCONFIGDIR": str(work / "mpl"),
        "XDG_CACHE_HOME": str(work / "cache"),
        "UV_PROJECT_ENVIRONMENT": "/tmp/energyplus-mcp-venv",
    }
    ep_params = StdioServerParameters(
        command="docker",
        args=[
            "run", "--rm", "-i", "-v", f"{repo}:{repo}",
            "-w", str(repo / "energyplus-mcp-server"),
            *sum((["-e", f"{key}={value}"] for key, value in ep_env.items()), []),
            args.image, "uv", "run", "python", "-m", "energyplus_mcp_server.server",
        ],
    )
    cal_params = StdioServerParameters(
        command=str(calibration_repo / ".venv/bin/python"),
        args=["-m", "calibration_mcp.server"],
        cwd=str(calibration_repo),
        env={
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(calibration_repo / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "CALIBRATION_MCP_HOME": str(calibration_home),
        },
    )

    async with AsyncExitStack() as stack:
        energyplus = await connect(stack, ep_params)
        calibration = await connect(stack, cal_params)

        resources = await calibration.list_resources()
        skill_uri = "skill://pattern-based-calibration/SKILL.md"
        if skill_uri not in {str(resource.uri) for resource in resources.resources}:
            raise RuntimeError("Calibration-MCP did not discover the authoritative skill")
        skill = await calibration.read_resource(skill_uri)
        if not skill.contents:
            raise RuntimeError("Calibration-MCP returned an empty skill resource")

        bills = manifest["utility_bills"]
        building = manifest["building"]
        created = await call(
            calibration, audit, "calibration", "create_project",
            building_id=f"{building['building_id']}-semantic-smoke",
            bldg_type=building["building_type"],
            hvac_sys_type=building["hvac_system_type"],
            runs_dir=str(runs), convergence_mode="strict", max_runs=2,
            backend="energyplus",
        )
        project_id = created["project_id"]
        await call(
            calibration, audit, "calibration", "ingest_bills",
            project_id=project_id,
            elec_measured=bills["electricity_january_to_december"],
            gas_measured=bills["gas_january_to_december"],
        )

        capabilities = await collect_domain_capabilities(energyplus, audit, source)
        partial = copy.deepcopy(capabilities)
        partial_lighting = _lighting_declaration(partial)
        partial_lighting.update({
            "supported": False,
            "coverage": "partial",
            "skipped": [{"reason": "smoke-injected unsupported schedule"}],
        })
        await call(
            calibration, audit, "calibration", "check_measure_reach",
            project_id=project_id, capabilities=partial, model_path=str(source),
        )
        partial_rejection = await expect_tool_rejection(
            calibration, "get_measure_recipe", project_id=project_id,
            parameter="light_sch", value=-3,
        )

        reach = await call(
            calibration, audit, "calibration", "check_measure_reach",
            project_id=project_id, capabilities=capabilities, model_path=str(source),
        )
        if "LPD" not in reach["supported_parameters"] or "light_sch" not in reach["supported_parameters"]:
            raise RuntimeError("smoke model lacks complete LPD and lighting-schedule coverage")

        lpd_recipe = await call(
            calibration, audit, "calibration", "get_measure_recipe",
            project_id=project_id, parameter="LPD", value=-3,
        )
        lpd_model = models / "legacy-lpd-minus-3.idf"
        lpd_edit = await execute_provider_recipe(
            energyplus, audit, lpd_recipe["recipes"][0],
            input_path=source, output_path=lpd_model, source_sha256=source_hash,
        )
        if sha256(source) != source_hash:
            raise RuntimeError("legacy edit changed the source model")

        lpd_hash = sha256(lpd_model)
        lpd_capabilities = await collect_domain_capabilities(energyplus, audit, lpd_model)
        await call(
            calibration, audit, "calibration", "check_measure_reach",
            project_id=project_id, capabilities=lpd_capabilities, model_path=str(lpd_model),
        )
        schedule_recipe = await call(
            calibration, audit, "calibration", "get_measure_recipe",
            project_id=project_id, parameter="light_sch", value=-3,
        )
        final_model = models / "legacy-lpd-and-lighting-schedule-minus-3.idf"
        schedule_edit = await execute_provider_recipe(
            energyplus, audit, schedule_recipe["recipes"][0],
            input_path=lpd_model, output_path=final_model, source_sha256=lpd_hash,
        )
        if sha256(lpd_model) != lpd_hash or sha256(source) != source_hash:
            raise RuntimeError("schedule edit changed an input model")

        run_id = "semantic-schedule-smoke"
        simulation = await call(
            energyplus, audit, "energyplus", "simulation_manager",
            action="run", idf_path=str(final_model), weather_file=str(weather),
            runs_dir=str(runs), run_id=run_id, readvars=False,
        )
        recorded = await call(
            calibration, audit, "calibration", "record_run",
            project_id=project_id, run_id=run_id, kind="baseline",
            model_path=str(final_model), assert_new=True, allow_ratio_outlier=True,
        )
        entry = tool_data(recorded)["run"]
        sql = runs / run_id / "run" / "eplusout.sql"
        run_record = runs / run_id / "run_record.json"
        if not sql.is_file() or not run_record.is_file() or not entry.get("metrics"):
            raise RuntimeError("live smoke did not produce and score canonical evidence")

    summary = {
        "ok": True,
        "project_id": project_id,
        "source": str(source),
        "source_sha256": source_hash,
        "legacy_operation": {
            "tool": lpd_recipe["recipes"][0]["tool_name"],
            "action": lpd_recipe["recipes"][0]["arguments"]["action"],
            "output": str(lpd_model),
            "changed": lpd_edit.get("changed"),
        },
        "new_operation": {
            "parameter": "light_sch",
            "tool": schedule_recipe["recipes"][0]["tool_name"],
            "action": schedule_recipe["recipes"][0]["arguments"]["action"],
            "output": str(final_model),
            "changed": schedule_edit.get("changed"),
            "coverage": schedule_edit.get("coverage"),
        },
        "partial_coverage_rejection": partial_rejection,
        "simulation": simulation,
        "evidence": {"sql": str(sql), "run_record": str(run_record)},
        "metrics": entry["metrics"],
        "skill_resource": skill_uri,
        "audit": str(work / "mcp-audit.jsonl"),
    }
    (work / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=True) + "\n")
    return summary


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    campaign = repo / "energyplus-mcp-server/outputs/sf-pilot-20260910/campaign-004"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=repo)
    parser.add_argument(
        "--calibration-repo", type=Path,
        default=Path("/Users/hanli/Documents/GitHub/BEM-AI/BEM-calibration-mcp"),
    )
    parser.add_argument("--manifest", type=Path, default=campaign / "input-manifest.json")
    parser.add_argument("--model", type=Path, default=campaign / "inputs/model-69-V26-1-0-calendar-2019.idf")
    parser.add_argument("--weather", type=Path, default=campaign / "inputs/CA_SAN-FRANCISCO-IAP_724940_19.epw")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--image", default="energyplus-mcp-dev:26.1.0-upgrade-20260910")
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args))
    except Exception as error:
        print(f"cross-server smoke failed: {error}", file=sys.stderr)
        traceback.print_exception(error)
        return 1
    print(json.dumps(result, indent=2, allow_nan=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
