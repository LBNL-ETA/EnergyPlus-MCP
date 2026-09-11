#!/usr/bin/env python3
"""Run a measured-bill native-IDF calibration pilot through both MCP servers.

The driver intentionally executes one complete parameter ladder.  It is a
checkpoint-producing integration pilot, not a hidden one-call optimizer:
EnergyPlus-MCP owns IDF inspection, mutation, and simulation, while
pattern-based-BEM-calibration-mcp owns bills, metrics, patterns, selection,
the run ledger, and the sweep commit.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import sys
import traceback
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


REQUIRED_PARAMETERS = {
    "LPD", "EPD", "OCD", "INF", "WIN-U", "WIN-SHGC", "COP", "HE", "FAN"
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    model = Path(data.get("model", {}).get("pilot_idf", "")).expanduser()
    weather = Path(data.get("weather", {}).get("path", "")).expanduser()
    bills = data.get("utility_bills", {})
    elec = bills.get("electricity_january_to_december")
    gas = bills.get("gas_january_to_december")
    if data.get("building", {}).get("building_type") not in {"office", "retail"}:
        errors.append("building_type must be office or retail")
    if data.get("building", {}).get("hvac_system_type") not in {
        "Packaged system", "Centralized system", "Heat pump"
    }:
        errors.append("hvac_system_type is not a calibration priority-database label")
    for label, values in (("electricity", elec), ("gas", gas)):
        if not isinstance(values, list) or len(values) != 12:
            errors.append(f"{label} bills must contain 12 January-to-December values")
        elif any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
            for value in values
        ):
            errors.append(f"{label} bills must be finite non-negative numbers")
    if bills.get("electricity_unit") != "kWh" or bills.get("gas_unit") != "therm":
        errors.append("bill units must be explicitly kWh and therm")
    if bills.get("calendar_year") != data.get("weather", {}).get("calendar_year"):
        errors.append("bill and weather calendar years do not match")
    for label, candidate, expected_suffix, expected_hash in (
        ("pilot model", model, ".idf", data.get("model", {}).get("pilot_sha256")),
        ("weather", weather, ".epw", data.get("weather", {}).get("sha256")),
    ):
        if not candidate.is_file() or candidate.suffix.lower() != expected_suffix:
            errors.append(f"{label} file is missing or has the wrong suffix: {candidate}")
        elif expected_hash != sha256(candidate):
            errors.append(f"{label} SHA-256 does not match the manifest")
    expected = set(data.get("calibration", {}).get("native_parameters_expected", []))
    if expected != REQUIRED_PARAMETERS:
        errors.append("native_parameters_expected must name exactly the nine released operations")
    if errors:
        raise ValueError("Invalid pilot manifest:\n- " + "\n- ".join(errors))
    data["_manifest_path"] = str(path.resolve())
    return data


def parse_tool_payload(result: Any) -> dict[str, Any]:
    texts = [block.text for block in result.content if getattr(block, "type", None) == "text"]
    if getattr(result, "isError", False):
        raise RuntimeError("MCP tool error: " + "\n".join(texts))
    decoder = json.JSONDecoder()
    for text in texts:
        for index, character in enumerate(text):
            if character not in "{[":
                continue
            try:
                payload, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                if payload.get("success") is False or payload.get("ok") is False:
                    raise RuntimeError(json.dumps(payload, indent=2))
                return payload
    raise RuntimeError("MCP tool returned no JSON object: " + "\n".join(texts)[-4000:])


def tool_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def convergence_branch(metrics: dict[str, Any], mode: str) -> str:
    def below(name: str, limit: float) -> bool:
        value = metrics.get(name)
        return isinstance(value, (int, float)) and not isinstance(value, bool) and (
            math.isnan(value) or abs(value) < limit
        )

    if all(
        below(name, limit)
        for name, limit in (
            ("nmbe_elec", 5), ("nmbe_gas", 5),
            ("cvrmse_elec", 15), ("cvrmse_gas", 15),
        )
    ):
        return "strict"
    if mode == "relaxed" and all(
        below(name, limit)
        for name, limit in (
            ("nmbe_source", 5), ("cvrmse_source", 15),
            ("nmbe_elec", 10), ("nmbe_gas", 10),
        )
    ):
        return "relaxed"
    return "not_converged"


def select_pattern(elec: dict[str, Any], gas: dict[str, Any]) -> tuple[str, int, dict[str, Any]] | None:
    fuels = (("Electricity", elec), ("Gas", gas))
    universal = [(fuel, pattern) for fuel, pattern in fuels if pattern.get("ub") in (-1, 1)]
    if universal:
        fuel, pattern = max(universal, key=lambda item: float(item[1].get("ub_index") or 0))
        return f"{fuel} universal bias", int(pattern["ub"]), pattern
    seasonal = [(fuel, pattern) for fuel, pattern in fuels if pattern.get("sb") in (-1, 1)]
    if seasonal:
        fuel, pattern = max(seasonal, key=lambda item: float(item[1].get("sb_index") or 0))
        return f"{fuel} seasonal bias", int(pattern["sb"]), pattern
    return None


def validate_run_period_calendar(
    preflight: dict[str, Any], year: int,
) -> list[dict[str, Any]]:
    def matches(actual: Any, expected: Any) -> bool:
        if isinstance(expected, int) and not isinstance(expected, bool):
            try:
                return float(actual) == float(expected)
            except (TypeError, ValueError):
                return False
        return str(actual).strip().lower() == str(expected).lower()

    settings = preflight.get("simulation_settings") or {}
    periods = ((settings.get("RunPeriod") or {}).get("current_values") or [])
    if not periods:
        raise ValueError("model preflight found no RunPeriod")
    problems = []
    for period in periods:
        expected = {
            "Begin_Month": 1,
            "Begin_Day_of_Month": 1,
            "Begin_Year": year,
            "End_Month": 12,
            "End_Day_of_Month": 31,
            "End_Year": year,
        }
        mismatches = {
            key: {"expected": value, "actual": period.get(key)}
            for key, value in expected.items()
            if not matches(period.get(key), value)
        }
        if mismatches:
            problems.append({"index": period.get("index"), "mismatches": mismatches})
    if problems:
        raise ValueError(
            "IDF RunPeriod is not aligned to the measured/weather calendar; "
            + json.dumps(problems, sort_keys=True)
        )
    return periods


class Audit:
    def __init__(self, path: Path):
        self.path = path
        self.sequence = sum(
            1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
        ) if path.exists() else 0

    def record(self, server: str, tool: str, arguments: dict[str, Any], result: dict[str, Any]) -> None:
        self.sequence += 1
        entry = {
            "sequence": self.sequence,
            "at": datetime.now(timezone.utc).isoformat(),
            "server": server,
            "tool": tool,
            "arguments": arguments,
            "result": result,
        }
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, sort_keys=True) + "\n")


async def call(
    session: ClientSession,
    audit: Audit,
    server: str,
    tool: str,
    **arguments: Any,
) -> dict[str, Any]:
    payload = parse_tool_payload(await session.call_tool(tool, arguments))
    audit.record(server, tool, arguments, payload)
    return payload


async def connect(stack: AsyncExitStack, params: StdioServerParameters) -> ClientSession:
    read, write = await stack.enter_async_context(stdio_client(params))
    session = await stack.enter_async_context(ClientSession(read, write))
    await session.initialize()
    return session


async def run(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = args.manifest.resolve()
    manifest = load_manifest(manifest_path)
    repo = args.repo.resolve()
    campaign = manifest_path.parent
    runs = campaign / "runs"
    models = campaign / "models"
    calibration_home = campaign / "calibration-workspace"
    for directory in (runs, models, calibration_home):
        directory.mkdir(parents=True, exist_ok=True)
    if any(runs.glob("*/run_record.json")):
        raise RuntimeError(f"{runs} already contains physical runs; use a new campaign directory")
    audit = Audit(campaign / "mcp-audit.jsonl")

    image = args.image
    ep_env = {
        "MCP_CONFIG_PATH": str(repo / "energyplus-mcp-server/config.yaml"),
        "WORKSPACE_ROOT": str(repo / "energyplus-mcp-server"),
        "MPLCONFIGDIR": str(campaign / "mpl"),
        "XDG_CACHE_HOME": str(campaign / "cache"),
        # Never let uv replace the host macOS .venv through the bind mount.
        "UV_PROJECT_ENVIRONMENT": "/tmp/energyplus-mcp-venv",
    }
    ep_params = StdioServerParameters(
        command="docker",
        args=[
            "run", "--rm", "-i",
            "-v", f"{repo}:{repo}",
            "-w", str(repo / "energyplus-mcp-server"),
            *sum((["-e", f"{key}={value}"] for key, value in ep_env.items()), []),
            image, "uv", "run", "python", "-m", "energyplus_mcp_server.server",
        ],
    )
    calibration_repo = args.calibration_repo.resolve()
    cal_params = StdioServerParameters(
        command=str(calibration_repo / ".venv/bin/python"),
        args=["-m", "calibration_mcp.server"],
        cwd=str(calibration_repo),
        env={
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(calibration_repo / "src"),
            "CALIBRATION_MCP_HOME": str(calibration_home),
        },
    )

    async with AsyncExitStack() as stack:
        ep = await connect(stack, ep_params)
        cal = await connect(stack, cal_params)
        ep_tools = {item.name for item in (await ep.list_tools()).tools}
        cal_tools = {item.name for item in (await cal.list_tools()).tools}
        for needed, available, label in (
            (
                {"calibration_manager", "simulation_manager", "model_preflight"},
                ep_tools,
                "EnergyPlus-MCP",
            ),
            ({
                "create_project", "ingest_bills", "classify_climate", "check_model_meters",
                "check_measure_reach", "record_run", "detect_patterns",
                "init_calibration_state", "pick_parameter", "get_measure_recipe",
                "get_bound_repair_recipe", "sweep_progress", "calibration_progress",
                "commit_sweep", "get_project",
            }, cal_tools, "calibration-MCP"),
        ):
            missing = needed - available
            if missing:
                raise RuntimeError(f"{label} is missing required tools: {sorted(missing)}")

        building = manifest["building"]
        calibration = manifest["calibration"]
        bills = manifest["utility_bills"]
        current_model = Path(manifest["model"]["pilot_idf"])
        weather = Path(manifest["weather"]["path"])
        preflight = await call(
            ep, audit, "energyplus", "model_preflight",
            action="info", idf_path=str(current_model),
        )
        run_periods = validate_run_period_calendar(
            preflight, manifest["weather"]["calendar_year"],
        )
        caps = await call(
            ep, audit, "energyplus", "calibration_manager",
            action="capabilities", idf_path=str(current_model),
        )
        supported = {
            name for name, declaration in caps["parameters"].items()
            if declaration.get("supported") and declaration.get("coverage") == "complete"
        }
        if supported != REQUIRED_PARAMETERS:
            raise RuntimeError(f"unexpected model-specific calibration coverage: {sorted(supported)}")

        created = await call(
            cal, audit, "calibration", "create_project",
            building_id=building["building_id"],
            bldg_type=building["building_type"],
            hvac_sys_type=building["hvac_system_type"],
            runs_dir=str(runs),
            convergence_mode=calibration["convergence_mode"],
            max_runs=calibration["physical_run_budget"],
            backend="energyplus",
        )
        project_id = created["project_id"]
        await call(
            cal, audit, "calibration", "ingest_bills", project_id=project_id,
            elec_measured=bills["electricity_january_to_december"],
            gas_measured=bills["gas_january_to_december"],
        )
        climate = await call(
            cal, audit, "calibration", "classify_climate",
            project_id=project_id, epw_path=str(weather),
        )
        await call(
            cal, audit, "calibration", "check_model_meters",
            project_id=project_id, capabilities=caps,
        )
        await call(
            cal, audit, "calibration", "check_measure_reach",
            project_id=project_id, capabilities=caps, model_path=str(current_model),
        )

        repairs: list[dict[str, Any]] = []
        for index, parameter in enumerate(sorted(REQUIRED_PARAMETERS), start=1):
            inspection = await call(
                ep, audit, "energyplus", "calibration_manager",
                action="inspect", idf_path=str(current_model), parameter=parameter,
            )
            repair = await call(
                cal, audit, "calibration", "get_bound_repair_recipe",
                project_id=project_id, parameter=parameter, inspection=inspection,
            )
            recipe_list = repair.get("recipes", [])
            if recipe_list:
                candidate = models / f"baseline-repair-{index:02d}-{parameter}.idf"
                recipe = recipe_list[0]
                mutation_args = dict(recipe["arguments"])
                mutation_args.update(idf_path=str(current_model), output_path=str(candidate))
                changed = await call(
                    ep, audit, "energyplus", recipe["tool_name"], **mutation_args,
                )
                repairs.append({
                    "parameter": parameter,
                    "input": str(current_model),
                    "output": str(candidate),
                    "changes": changed.get("changes", []),
                })
                current_model = candidate
                caps = await call(
                    ep, audit, "energyplus", "calibration_manager",
                    action="capabilities", idf_path=str(current_model),
                )
                await call(
                    cal, audit, "calibration", "check_measure_reach",
                    project_id=project_id, capabilities=caps, model_path=str(current_model),
                )

        baseline_run_id = "baseline"
        baseline_sim = await call(
            ep, audit, "energyplus", "simulation_manager",
            action="run", idf_path=str(current_model), weather_file=str(weather),
            runs_dir=str(runs), run_id=baseline_run_id, readvars=False,
        )
        baseline_record = await call(
            cal, audit, "calibration", "record_run",
            project_id=project_id, run_id=baseline_run_id, kind="baseline",
            model_path=str(current_model), assert_new=True,
            allow_ratio_outlier=bool(
                calibration.get("allow_source_qualified_ratio_outlier", False)
            ),
        )
        baseline_entry = tool_data(baseline_record)["run"]
        baseline_metrics = baseline_entry["metrics"]
        baseline_branch = convergence_branch(
            baseline_metrics, calibration["convergence_mode"]
        )
        elec_pattern = tool_data(await call(
            cal, audit, "calibration", "detect_patterns",
            project_id=project_id, run_id=baseline_run_id, fuel="elec",
        ))
        gas_pattern = tool_data(await call(
            cal, audit, "calibration", "detect_patterns",
            project_id=project_id, run_id=baseline_run_id, fuel="gas",
        ))
        await call(
            cal, audit, "calibration", "init_calibration_state", project_id=project_id,
        )

        summary: dict[str, Any] = {
            "status": "baseline_checkpoint",
            "project_id": project_id,
            "manifest": str(manifest_path),
            "climate": tool_data(climate).get("climate_type"),
            "bounds_extreme_diagnostics": "unavailable_nonfatal",
            "bound_repairs": repairs,
            "run_periods": run_periods,
            "baseline": {
                "run_id": baseline_run_id,
                "model_path": str(current_model),
                "model_sha256": sha256(current_model),
                "simulation": baseline_sim,
                "metrics": baseline_metrics,
                "convergence_branch": baseline_branch,
                "patterns": {"electricity": elec_pattern, "gas": gas_pattern},
            },
        }
        if baseline_branch != "not_converged":
            summary["status"] = "baseline_converged"
        else:
            selected_pattern = select_pattern(elec_pattern, gas_pattern)
            if selected_pattern is None:
                summary["status"] = "no_pattern_checkpoint"
            else:
                bias_pattern, bias_sign, pattern_evidence = selected_pattern
                selection = tool_data(await call(
                    cal, audit, "calibration", "pick_parameter",
                    project_id=project_id, bias_pattern=bias_pattern, bias_sign=bias_sign,
                ))
                parameter = selection.get("chosen_param")
                direction = selection.get("direction")
                if not parameter or direction not in {"increase", "decrease"}:
                    summary["status"] = "no_available_parameter_checkpoint"
                    summary["selection"] = selection
                else:
                    initial_progress = tool_data(await call(
                        cal, audit, "calibration", "sweep_progress",
                        project_id=project_id, parameter=parameter, direction=direction,
                    ))
                    expected_values = initial_progress["missing_values"]
                    budget = tool_data(await call(
                        cal, audit, "calibration", "calibration_progress",
                        project_id=project_id, needed=len(expected_values),
                    ))
                    if not budget.get("can_start_batch"):
                        raise RuntimeError("the physical-run budget cannot fit the complete ladder")
                    candidates: list[dict[str, Any]] = []
                    inspection = await call(
                        ep, audit, "energyplus", "calibration_manager",
                        action="inspect", idf_path=str(current_model), parameter=parameter,
                    )
                    for rung, value in enumerate(expected_values, start=1):
                        progress = tool_data(await call(
                            cal, audit, "calibration", "sweep_progress",
                            project_id=project_id, parameter=parameter, direction=direction,
                        ))
                        if progress.get("next_value") != value:
                            raise RuntimeError(
                                f"authoritative next rung changed: expected {value}, got {progress.get('next_value')}"
                            )
                        bounded = await call(
                            cal, audit, "calibration", "get_bound_repair_recipe",
                            project_id=project_id, parameter=parameter,
                            inspection=inspection, percentage_change=value,
                        )
                        recipe_list = bounded.get("recipes") or []
                        if not recipe_list:
                            raise RuntimeError(
                                f"bounded {parameter} rung {value} is a no-op"
                            )
                        recipe = recipe_list[0]
                        candidate_model = models / f"sweep-01-{parameter}-{rung:02d}-{value}.idf"
                        mutation_args = dict(recipe["arguments"])
                        mutation_args.update(
                            idf_path=str(current_model), output_path=str(candidate_model)
                        )
                        mutation = await call(
                            ep, audit, "energyplus", recipe["tool_name"], **mutation_args,
                        )
                        if not mutation.get("changes"):
                            raise RuntimeError(f"{parameter} rung {value} made no model change")
                        run_id = f"sweep-01-{parameter.lower()}-{rung:02d}"
                        simulation = await call(
                            ep, audit, "energyplus", "simulation_manager",
                            action="run", idf_path=str(candidate_model), weather_file=str(weather),
                            runs_dir=str(runs), run_id=run_id, readvars=False,
                        )
                        record = await call(
                            cal, audit, "calibration", "record_run",
                            project_id=project_id, run_id=run_id, kind="candidate",
                            parameter=parameter, value=str(value), decision="rejected",
                            model_path=str(candidate_model), seed_model_path=str(current_model),
                            use_selection=True, assert_new=True,
                            allow_ratio_outlier=bool(
                                calibration.get("allow_source_qualified_ratio_outlier", False)
                            ),
                        )
                        candidates.append({
                            "run_id": run_id, "value": value, "model_path": str(candidate_model),
                            "model_sha256": sha256(candidate_model), "simulation": simulation,
                            "metrics": tool_data(record)["run"]["metrics"],
                        })
                    final_progress = tool_data(await call(
                        cal, audit, "calibration", "sweep_progress",
                        project_id=project_id, parameter=parameter, direction=direction,
                    ))
                    if not final_progress.get("can_close"):
                        raise RuntimeError("complete ladder was simulated but sweep_progress cannot close it")
                    commit = tool_data(await call(
                        cal, audit, "calibration", "commit_sweep",
                        project_id=project_id, parameter=parameter,
                        incoming_run_id=baseline_run_id,
                        allow_ratio_outlier=bool(
                            calibration.get("allow_source_qualified_ratio_outlier", False)
                        ),
                    ))
                    project = await call(
                        cal, audit, "calibration", "get_project", project_id=project_id,
                    )
                    summary.update({
                        "status": "first_sweep_committed",
                        "selection": {
                            "bias_pattern": bias_pattern,
                            "bias_sign": bias_sign,
                            "pattern_evidence": pattern_evidence,
                            **selection,
                        },
                        "sweep": {
                            "parameter": parameter,
                            "direction": direction,
                            "expected_values": expected_values,
                            "candidates": candidates,
                            "commit": commit,
                        },
                        "project_checkpoint": project,
                    })

    summary["completed_at"] = datetime.now(timezone.utc).isoformat()
    summary["audit_log"] = str(audit.path)
    (campaign / "pilot-summary.json").write_text(
        json.dumps(summary, indent=2, allow_nan=True) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--repo", type=Path,
        default=Path(__file__).resolve().parents[1],
        help="EnergyPlus-MCP repository root",
    )
    parser.add_argument(
        "--calibration-repo", type=Path,
        default=Path("/Users/hanli/Documents/projects/Openstudio-AI/pattern-based-BEM-calibration-mcp"),
    )
    parser.add_argument(
        "--image", default="energyplus-mcp-dev:26.1.0-upgrade-20260910",
    )
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args))
    except Exception as error:
        print(f"pilot failed: {error}", file=sys.stderr)
        traceback.print_exception(error)
        return 1
    print(json.dumps(result, indent=2, allow_nan=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
