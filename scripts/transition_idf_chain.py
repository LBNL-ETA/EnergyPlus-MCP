#!/usr/bin/env python3
"""Create an auditable, copy-only sequential EnergyPlus IDF transition.

The EnergyPlus transition executables require their adjacent IDD files in the
current working directory.  This utility keeps the supplied input read-only,
runs each transition against a disposable copy, and retains a versioned IDF,
official audit, stdout/stderr, SHA-256, and manifest for every stage.

It intentionally supports the SF 9.2 -> 25.1 host chain followed by the
25.1 -> 25.2 -> 26.1 chain packaged in the specified Docker image.  It does
not modify a source model, bulk-migrate models, or run simulations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


TRANSITION_RE = re.compile(
    r"^Transition-(V(?P<source>\d+-\d+-\d+))-to-(V(?P<target>\d+-\d+-\d+))$"
)
VERSION_RE = re.compile(r"(?im)^\s*version\s*,\s*([^,;!\r\n]+)")
CONTAINER_TRANSITIONS = (
    "Transition-V25-1-0-to-V25-2-0",
    "Transition-V25-2-0-to-V26-1-0",
)
CONTAINER_IDDS = ("V25-1-0-Energy+.idd", "V25-2-0-Energy+.idd", "V26-1-0-Energy+.idd")
CONTAINER_REPORT_VARIABLE_MAPPINGS = (
    "Report Variables 25-1-0 to 25-2-0.csv",
    "Report Variables 25-2-0 to 26-1-0.csv",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def idf_version(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = VERSION_RE.search(text)
    if not match:
        raise RuntimeError(f"No Version object found in {path}")
    numbers = match.group(1).strip().split(".")
    if not 2 <= len(numbers) <= 3 or any(not part.isdigit() for part in numbers):
        raise RuntimeError(f"Unrecognised Version value in {path}: {match.group(1)!r}")
    numbers += ["0"] * (3 - len(numbers))
    return "V" + "-".join(numbers)


def transition_parts(name: str) -> tuple[str, str]:
    match = TRANSITION_RE.match(name)
    if not match:
        raise RuntimeError(f"Unexpected transition executable name: {name}")
    return f"V{match.group('source')}", f"V{match.group('target')}"


def report_variable_mapping_name(from_version: str, to_version: str) -> str:
    return f"Report Variables {from_version[1:]} to {to_version[1:]}.csv"


def local_steps(transition_dir: Path, source_version: str) -> list[tuple[str, str, str, Path]]:
    available: dict[str, tuple[str, str, Path]] = {}
    for executable in transition_dir.glob("Transition-V*-to-V*"):
        if not executable.is_file():
            continue
        from_version, to_version = transition_parts(executable.name)
        available[from_version] = (from_version, to_version, executable)

    result: list[tuple[str, str, str, Path]] = []
    current = source_version
    while current != "V25-1-0":
        if current not in available:
            raise RuntimeError(
                f"{transition_dir} has no adjacent transition beginning at {current}; "
                "refusing a non-sequential upgrade"
            )
        from_version, to_version, executable = available[current]
        for idd_version in (from_version, to_version):
            idd = transition_dir / f"{idd_version}-Energy+.idd"
            if not idd.is_file():
                raise RuntimeError(f"Required adjacent IDD is missing: {idd}")
        mapping = transition_dir / report_variable_mapping_name(from_version, to_version)
        if not mapping.is_file():
            raise RuntimeError(f"Required report-variable mapping is missing: {mapping}")
        result.append((from_version, to_version, executable.name, executable))
        current = to_version
    return result


def copy_transition_sidecars(work_dir: Path, artifact_dir: Path, label: str) -> list[str]:
    copied: list[str] = []
    for candidate in sorted(work_dir.iterdir()):
        if candidate.name == "current.idf" or not candidate.is_file():
            continue
        destination = artifact_dir / f"{label}__{candidate.name}"
        shutil.copy2(candidate, destination)
        copied.append(str(destination.relative_to(artifact_dir.parent)))
    return copied


def copy_runtime_auxiliary_sidecars(runtime_dir: Path, artifact_dir: Path, label: str) -> list[str]:
    """Retain only transition-generated runtime files, never the staged binaries/IDDs."""
    copied: list[str] = []
    for name in ("Energy+.ini", "Transition.audit", "audit.out", "eplusout.err"):
        candidate = runtime_dir / name
        if candidate.is_file():
            destination = artifact_dir / f"{label}__runtime-{name}"
            shutil.copy2(candidate, destination)
            copied.append(str(destination.relative_to(artifact_dir.parent)))
    return copied


def stage_local_runtime(
    transition_dir: Path, steps: list[tuple[str, str, str, Path]], runtime_dir: Path
) -> None:
    """Copy the executable, adjacent IDDs, and report-variable mapping for every step."""
    runtime_dir.mkdir()
    needed: set[Path] = set()
    for from_version, to_version, _name, executable in steps:
        needed.add(executable)
        needed.add(transition_dir / f"{from_version}-Energy+.idd")
        needed.add(transition_dir / f"{to_version}-Energy+.idd")
        needed.add(transition_dir / report_variable_mapping_name(from_version, to_version))
    for source in sorted(needed):
        shutil.copy2(source, runtime_dir / source.name)


def container_transition_command(
    *,
    output_dir: Path,
    image: str,
    platform: str,
    transition_dir: str,
    executable_name: str,
) -> list[str]:
    """Run a candidate transition from a writable mounted runtime directory."""
    assets = (*CONTAINER_TRANSITIONS, *CONTAINER_IDDS, *CONTAINER_REPORT_VARIABLE_MAPPINGS)
    shell = (
        "set -eu; "
        "runtime=/artifacts/container-transition-runtime; "
        "mkdir -p \"$runtime\"; "
        "executable=$1; shift; "
        "for asset in \"$@\"; do cp -f \"$PWD/$asset\" \"$runtime/$asset\"; done; "
        "cd \"$runtime\"; "
        "exec \"$runtime/$executable\" /artifacts/work/current.idf"
    )
    return [
        "docker", "run", "--rm", "--platform", platform,
        "--user", f"{os.getuid()}:{os.getgid()}",
        "-v", f"{output_dir}:/artifacts",
        "-w", transition_dir,
        image,
        "/bin/sh", "-c", shell, "energyplus-transition", executable_name, *assets,
    ]


def run_step(
    *,
    current: Path,
    work_idf: Path,
    work_dir: Path,
    artifacts_dir: Path,
    stages_dir: Path,
    from_version: str,
    to_version: str,
    executable_name: str,
    command: list[str],
    cwd: Path | None,
    manifest: dict,
    manifest_path: Path,
    runtime_auxiliary_dir: Path | None = None,
) -> Path:
    shutil.copy2(current, work_idf)
    before_hash = sha256(work_idf)
    label = f"{from_version}-to-{to_version}"
    completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    (artifacts_dir / f"{label}.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (artifacts_dir / f"{label}.stderr.log").write_text(completed.stderr, encoding="utf-8")
    sidecars = copy_transition_sidecars(work_dir, artifacts_dir, label)
    if runtime_auxiliary_dir:
        sidecars += copy_runtime_auxiliary_sidecars(runtime_auxiliary_dir, artifacts_dir, label)
    record = {
        "from_version": from_version,
        "to_version": to_version,
        "transition_executable": executable_name,
        "command": command,
        "cwd": str(cwd) if cwd else None,
        "input_sha256": before_hash,
        "returncode": completed.returncode,
        "sidecars": sidecars,
    }
    if completed.returncode != 0:
        record["status"] = "failed"
        manifest["steps"].append(record)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError(f"{label} failed; see {artifacts_dir / f'{label}.stdout.log'}")
    actual_version = idf_version(work_idf)
    if actual_version != to_version:
        record.update({"status": "failed", "actual_version": actual_version})
        manifest["steps"].append(record)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError(f"{label} produced {actual_version}, expected {to_version}")
    stage = stages_dir / f"model-{to_version}.idf"
    shutil.copy2(work_idf, stage)
    record.update(
        {
            "status": "completed",
            "output_sha256": sha256(stage),
            "output_version": actual_version,
            "output_file": str(stage.relative_to(manifest_path.parent)),
        }
    )
    manifest["steps"].append(record)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return stage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Original IDF; never modified")
    parser.add_argument("--output-dir", type=Path, required=True, help="Must not already exist")
    parser.add_argument(
        "--local-transition-dir",
        type=Path,
        required=True,
        help="Official 25.1 IDFVersionUpdater directory containing 9.2 through 25.1 steps",
    )
    parser.add_argument("--container-image", required=True, help="Pinned 26.1 candidate image tag")
    parser.add_argument(
        "--container-transition-dir",
        default="/app/software/EnergyPlusV26-1-0/PreProcess/IDFVersionUpdater",
    )
    parser.add_argument("--platform", default="linux/arm64")
    args = parser.parse_args()

    source = args.source.resolve(strict=True)
    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        raise RuntimeError(f"Output directory already exists: {output_dir}")
    if source.is_relative_to(output_dir):
        raise RuntimeError("Source must not be inside the output directory")
    transition_dir = args.local_transition_dir.resolve(strict=True)

    source_version = idf_version(source)
    output_dir.mkdir(parents=True)
    stages_dir = output_dir / "stages"
    artifacts_dir = output_dir / "transition-artifacts"
    work_dir = output_dir / "work"
    runtime_dir = output_dir / "local-transition-runtime"
    container_runtime_dir = output_dir / "container-transition-runtime"
    for directory in (stages_dir, artifacts_dir, work_dir):
        directory.mkdir()
    source_stage = stages_dir / f"model-{source_version}.idf"
    shutil.copy2(source, source_stage)
    source_hash = sha256(source)
    manifest_path = output_dir / "migration-manifest.json"
    manifest = {
        "purpose": "copy-only representative IDF transition proof; not equivalence or calibration evidence",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "source_sha256_before": source_hash,
        "source_version": source_version,
        "source_copy": str(source_stage.relative_to(output_dir)),
        "local_transition_dir": str(transition_dir),
        "container_image": args.container_image,
        "container_transition_dir": args.container_transition_dir,
        "container_transition_runtime": str(container_runtime_dir.relative_to(output_dir)),
        "transition_support_assets": {
            "required": ["adjacent Energy+.idd", "per-step Report Variables mapping CSV"],
            "not_executed": "Rules and ObjectStatus files are documentation, per EnergyPlus auxiliary-program documentation.",
        },
        "platform": args.platform,
        "steps": [],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    current = source_stage
    work_idf = work_dir / "current.idf"
    try:
        local_chain = local_steps(transition_dir, source_version)
        stage_local_runtime(transition_dir, local_chain, runtime_dir)
        manifest["local_transition_runtime"] = str(runtime_dir.relative_to(output_dir))
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        for from_version, to_version, executable_name, _executable in local_chain:
            executable = runtime_dir / executable_name
            current = run_step(
                current=current,
                work_idf=work_idf,
                work_dir=work_dir,
                artifacts_dir=artifacts_dir,
                stages_dir=stages_dir,
                from_version=from_version,
                to_version=to_version,
                executable_name=executable_name,
                command=[str(executable), str(work_idf)],
                cwd=runtime_dir,
                manifest=manifest,
                manifest_path=manifest_path,
                runtime_auxiliary_dir=runtime_dir,
            )
        for executable_name in CONTAINER_TRANSITIONS:
            from_version, to_version = transition_parts(executable_name)
            if idf_version(current) != from_version:
                raise RuntimeError(f"Expected {from_version} before {executable_name}, found {idf_version(current)}")
            command = container_transition_command(
                output_dir=output_dir,
                image=args.container_image,
                platform=args.platform,
                transition_dir=args.container_transition_dir,
                executable_name=executable_name,
            )
            current = run_step(
                current=current,
                work_idf=work_idf,
                work_dir=work_dir,
                artifacts_dir=artifacts_dir,
                stages_dir=stages_dir,
                from_version=from_version,
                to_version=to_version,
                executable_name=executable_name,
                command=command,
                cwd=None,
                manifest=manifest,
                manifest_path=manifest_path,
                runtime_auxiliary_dir=container_runtime_dir,
            )
    except Exception as error:
        manifest["status"] = "failed"
        manifest["error"] = str(error)
        manifest["source_sha256_after"] = sha256(source)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        raise
    manifest.update(
        {
            "status": "completed",
            "final_file": str(current.relative_to(output_dir)),
            "final_version": idf_version(current),
            "final_sha256": sha256(current),
            "source_sha256_after": sha256(source),
        }
    )
    if manifest["source_sha256_after"] != source_hash:
        manifest["status"] = "failed"
        manifest["error"] = "Source hash changed unexpectedly"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError("Source hash changed unexpectedly")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(current)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"transition_idf_chain: {error}", file=sys.stderr)
        raise SystemExit(1)
