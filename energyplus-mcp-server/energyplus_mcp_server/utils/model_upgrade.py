"""Copy-only, local EnergyPlus IDF transition planning and execution.

This module intentionally does not simulate models, call Docker, use the
network, or accept an executable path from a caller.  It discovers official
transition programs only from the configured transition directory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Optional


TRANSITION_RE = re.compile(
    r"^Transition-(V(?P<source>\d+-\d+-\d+))-to-(V(?P<target>\d+-\d+-\d+))(?:\.exe)?$"
)
IDF_VERSION_RE = re.compile(r"(?im)^\s*version\s*,\s*([^,;\r\n]+)")
VERSION_RE = re.compile(r"^V?(\d+)[.-](\d+)(?:[.-](\d+))?$")
RUNTIME_VERSION_RE = re.compile(r"\d+\.\d+(?:\.\d+)?")
RUNTIME_AUXILIARY_FILES = ("Energy+.ini", "Transition.audit", "audit.out", "eplusout.err")
WARNING_LINE_RE = re.compile(r"(?im)^.*(?:\*\*\s*warning\s*\*\*|\bwarning\s*:).*$")


@dataclass(frozen=True, order=True)
class EnergyPlusVersion:
    """A comparable EnergyPlus version with stable transition-file labels."""

    parts: tuple[int, int, int]
    raw: str = field(compare=False)

    @classmethod
    def parse(cls, value: str) -> "EnergyPlusVersion":
        normalized = value.strip()
        match = VERSION_RE.fullmatch(normalized)
        if not match:
            raise ValueError(f"Unsupported EnergyPlus version: {value!r}")
        return cls(tuple(int(part or 0) for part in match.groups()), normalized)

    @property
    def label(self) -> str:
        return "V" + "-".join(str(part) for part in self.parts)

    @property
    def canonical(self) -> str:
        return ".".join(str(part) for part in self.parts)

    @property
    def display(self) -> str:
        return f"{self.parts[0]}.{self.parts[1]}" if self.parts[2] == 0 else self.canonical


@dataclass(frozen=True)
class TransitionStep:
    source: EnergyPlusVersion
    target: EnergyPlusVersion
    executable: Path

    @property
    def mapping_name(self) -> str:
        return f"Report Variables {self.source.label[1:]} to {self.target.label[1:]}.csv"

    def assets(self, transition_dir: Path) -> list[dict[str, Any]]:
        expected = (
            ("transition_executable", self.executable),
            ("source_idd", transition_dir / f"{self.source.label}-Energy+.idd"),
            ("target_idd", transition_dir / f"{self.target.label}-Energy+.idd"),
            ("report_variable_mapping", transition_dir / self.mapping_name),
        )
        return [
            {"kind": kind, "name": path.name, "path": str(path), "exists": path.is_file()}
            for kind, path in expected
        ]


class ModelUpgrade:
    """Discover and execute a bounded, auditable chain of local transitions."""

    def __init__(self, config: Any, *, timeout_seconds: int = 300):
        self.config = config
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _file_hash(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _idf_version(path: Path) -> EnergyPlusVersion:
        contents = path.read_text(encoding="utf-8", errors="replace")
        # IDF comments can follow the object field or sit between ``Version,``
        # and the version value.  Parse only the object text, never via the
        # current runtime's IDD (which cannot safely read older models).
        uncommented = re.sub(r"!.*$", "", contents, flags=re.MULTILINE)
        match = IDF_VERSION_RE.search(uncommented)
        if not match:
            raise ValueError(f"IDF has no Version object: {path}")
        return EnergyPlusVersion.parse(match.group(1).strip())

    def _resolve_idf_path(self, idf_path: str) -> Path:
        candidate = Path(idf_path).expanduser()
        if not candidate.is_absolute():
            workspace_root = Path(self.config.paths.workspace_root)
            candidate = workspace_root / candidate
        candidate = candidate.resolve()
        if not candidate.is_file():
            raise FileNotFoundError(f"IDF not found: {candidate}")
        if candidate.suffix.lower() != ".idf":
            raise ValueError(f"Expected an .idf file: {candidate}")
        return candidate

    def _resolve_output_directory(self, output_directory: str) -> Path:
        candidate = Path(output_directory).expanduser()
        if not candidate.is_absolute():
            candidate = Path(self.config.paths.workspace_root) / candidate
        return candidate.resolve()

    def _transition_directory(self) -> tuple[Path, str]:
        configured = os.getenv("EPLUS_TRANSITION_DIR")
        if configured:
            return Path(configured).expanduser().resolve(), "EPLUS_TRANSITION_DIR"
        installation = Path(self.config.energyplus.installation_path)
        return (installation / "PreProcess" / "IDFVersionUpdater").resolve(), "EnergyPlus installation fallback"

    def _runtime_version(self) -> EnergyPlusVersion:
        executable = Path(self.config.energyplus.executable_path)
        if not executable.is_file():
            raise FileNotFoundError(f"Configured EnergyPlus executable not found: {executable}")
        completed = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"EnergyPlus version probe failed with exit code {completed.returncode}")
        match = RUNTIME_VERSION_RE.search(f"{completed.stdout}\n{completed.stderr}")
        if not match:
            raise RuntimeError(f"Could not determine EnergyPlus version from {executable}")
        return EnergyPlusVersion.parse(match.group(0))

    @staticmethod
    def _discover_transitions(transition_dir: Path) -> tuple[dict[EnergyPlusVersion, list[TransitionStep]], list[str]]:
        transitions: dict[EnergyPlusVersion, list[TransitionStep]] = {}
        issues: list[str] = []
        if not transition_dir.is_dir():
            return transitions, [f"Transition directory not found: {transition_dir}"]
        for candidate in transition_dir.iterdir():
            match = TRANSITION_RE.fullmatch(candidate.name)
            if not match or not candidate.is_file():
                continue
            source = EnergyPlusVersion.parse(match.group("source"))
            target = EnergyPlusVersion.parse(match.group("target"))
            transitions.setdefault(source, []).append(TransitionStep(source, target, candidate))
        return transitions, issues

    def _build_chain(
        self,
        source: EnergyPlusVersion,
        target: EnergyPlusVersion,
        transition_dir: Path,
    ) -> tuple[list[TransitionStep], list[str]]:
        transitions, issues = self._discover_transitions(transition_dir)
        if issues or source >= target:
            return [], issues
        chain: list[TransitionStep] = []
        visited: set[EnergyPlusVersion] = set()
        current = source
        while current != target:
            if current in visited:
                issues.append(f"Transition chain loops at {current.display}")
                break
            visited.add(current)
            candidates = transitions.get(current, [])
            if not candidates:
                issues.append(f"No official adjacent transition begins at {current.display}")
                break
            if len(candidates) != 1:
                names = ", ".join(step.executable.name for step in candidates)
                issues.append(f"Ambiguous transitions from {current.display}: {names}")
                break
            step = candidates[0]
            if step.target <= current:
                issues.append(f"Invalid non-forward transition: {step.executable.name}")
                break
            if step.target > target:
                issues.append(
                    f"Transition {step.executable.name} overshoots requested target {target.display}"
                )
                break
            chain.append(step)
            current = step.target
        return chain, issues

    def plan(self, idf_path: str, target_version: Optional[str] = None) -> dict[str, Any]:
        """Read source and local transition metadata only; never create files."""
        result: dict[str, Any] = {
            "tool": "model_upgrade",
            "action": "plan",
            "simulation_validated": False,
            "writes_files": False,
            "steps": [],
            "missing_assets": [],
            "issues": [],
        }
        try:
            source_path = self._resolve_idf_path(idf_path)
            source = self._idf_version(source_path)
            result.update(
                {
                    "idf_path": str(source_path),
                    "source_version": source.display,
                    "source_version_canonical": source.canonical,
                    "source_sha256": self._file_hash(source_path),
                }
            )
            if target_version is None:
                target = self._runtime_version()
                result["target_source"] = "configured EnergyPlus runtime"
            else:
                target = EnergyPlusVersion.parse(target_version)
                result["target_source"] = "explicit request"
            result.update(
                {
                    "target_version": target.display,
                    "target_version_canonical": target.canonical,
                }
            )
            if source == target:
                result.update(
                    {
                        "status": "no_upgrade_needed",
                        "ready_to_run": False,
                        "message": "Model already declares the requested EnergyPlus version; no files will be written.",
                    }
                )
                return result
            if source > target:
                result.update(
                    {
                        "status": "refused",
                        "ready_to_run": False,
                        "issues": [f"Downgrade is not supported: {source.display} to {target.display}"],
                    }
                )
                return result

            transition_dir, directory_source = self._transition_directory()
            result["transition_directory"] = str(transition_dir)
            result["transition_directory_source"] = directory_source
            chain, issues = self._build_chain(source, target, transition_dir)
            result["issues"].extend(issues)
            for step in chain:
                assets = step.assets(transition_dir)
                result["steps"].append(
                    {
                        "from_version": step.source.display,
                        "to_version": step.target.display,
                        "executable": step.executable.name,
                        "assets": assets,
                    }
                )
                result["missing_assets"].extend(
                    {
                        "from_version": step.source.display,
                        "to_version": step.target.display,
                        **asset,
                    }
                    for asset in assets
                    if not asset["exists"]
                )
            if result["issues"] or result["missing_assets"] or not chain:
                result.update({"status": "unavailable", "ready_to_run": False})
            else:
                result.update({"status": "ready", "ready_to_run": True})
        except Exception as error:
            result.update({"status": "unavailable", "ready_to_run": False, "issues": [str(error)]})
        return result

    @staticmethod
    def _copy_runtime_outputs(runtime_dir: Path, artifact_dir: Path, label: str) -> list[str]:
        copied: list[str] = []
        for name in RUNTIME_AUXILIARY_FILES:
            source = runtime_dir / name
            if source.is_file():
                target = artifact_dir / f"{label}__runtime-{name}"
                shutil.copy2(source, target)
                copied.append(str(target.relative_to(artifact_dir.parent)))
        return copied

    @staticmethod
    def _copy_work_sidecars(work_dir: Path, artifact_dir: Path, label: str) -> list[str]:
        copied: list[str] = []
        for source in sorted(work_dir.iterdir()):
            if source.name == "current.idf" or not source.is_file():
                continue
            target = artifact_dir / f"{label}__{source.name}"
            shutil.copy2(source, target)
            copied.append(str(target.relative_to(artifact_dir.parent)))
        return copied

    @staticmethod
    def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def _as_text(value: str | bytes | None) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value or ""

    @staticmethod
    def _warning_summary(
        stdout: str,
        stderr: str,
        stdout_log: Path,
        stderr_log: Path,
        output_dir: Path,
        auxiliary_files: list[Path],
        copied_sidecars: list[str],
    ) -> dict[str, Any]:
        text_by_source = [("stdout", stdout), ("stderr", stderr)]
        for auxiliary in auxiliary_files:
            if auxiliary.is_file():
                text_by_source.append((auxiliary.name, auxiliary.read_text(encoding="utf-8", errors="replace")))
        warnings = [
            {"source": source, "line": line.strip()}
            for source, text in text_by_source
            for line in WARNING_LINE_RE.findall(text)
        ]
        return {
            "count": len(warnings),
            "examples": warnings[:10],
            "stdout_log": str(stdout_log.relative_to(output_dir)),
            "stderr_log": str(stderr_log.relative_to(output_dir)),
            "auxiliary_files": [
                path for path in copied_sidecars if "__runtime-" in Path(path).name
            ],
        }

    @staticmethod
    def _transition_warning_summaries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "from_version": step["from_version"],
                "to_version": step["to_version"],
                "warnings": step["warnings"],
            }
            for step in manifest["steps"]
            if "warnings" in step
        ]

    def run(
        self,
        idf_path: str,
        target_version: Optional[str],
        output_directory: Optional[str],
    ) -> dict[str, Any]:
        """Execute a preplanned transition on copies in a new output directory."""
        plan = self.plan(idf_path, target_version)
        result = {**plan, "action": "run", "writes_files": False, "ready_to_run": False}
        if plan["status"] == "no_upgrade_needed":
            result["migration_status"] = "no_upgrade_needed"
            return result
        if plan["status"] != "ready":
            result["migration_status"] = "refused"
            return result
        if not output_directory:
            result.update(
                {
                    "status": "refused",
                    "migration_status": "refused",
                    "issues": [*plan["issues"], "output_directory is required for action='run'"],
                }
            )
            return result

        output_dir = self._resolve_output_directory(output_directory)
        if output_dir.exists():
            result.update(
                {
                    "status": "refused",
                    "migration_status": "refused",
                    "output_directory": str(output_dir),
                    "issues": [*plan["issues"], f"Output directory already exists: {output_dir}"],
                }
            )
            return result

        source = Path(plan["idf_path"])
        source_hash = plan["source_sha256"]
        transition_dir = Path(plan["transition_directory"])
        output_dir.mkdir(parents=True)
        stages_dir = output_dir / "stages"
        runtime_dir = output_dir / "transition-runtime"
        work_dir = output_dir / "work"
        artifact_dir = output_dir / "transition-artifacts"
        for directory in (stages_dir, runtime_dir, work_dir, artifact_dir):
            directory.mkdir()
        manifest_path = output_dir / "migration-manifest.json"
        manifest: dict[str, Any] = {
            "tool": "model_upgrade",
            "migration_status": "running",
            "simulation_validated": False,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": str(source),
            "source_version": plan["source_version"],
            "target_version": plan["target_version"],
            "source_sha256_before": source_hash,
            "transition_directory": str(transition_dir),
            "steps": [],
        }
        self._write_manifest(manifest_path, manifest)
        result.update(
            {
                "status": "running",
                "migration_status": "running",
                "writes_files": True,
                "output_directory": str(output_dir),
                "migration_manifest": str(manifest_path),
            }
        )

        try:
            current = stages_dir / f"{source.stem}-{EnergyPlusVersion.parse(plan['source_version']).label}{source.suffix}"
            shutil.copy2(source, current)
            manifest["source_copy"] = str(current.relative_to(output_dir))
            for step_data in plan["steps"]:
                for asset in step_data["assets"]:
                    source_asset = Path(asset["path"])
                    shutil.copy2(source_asset, runtime_dir / source_asset.name)
            self._write_manifest(manifest_path, manifest)

            for step_data in plan["steps"]:
                label = f"V{step_data['from_version'].replace('.', '-')}-to-V{step_data['to_version'].replace('.', '-')}"
                executable = runtime_dir / step_data["executable"]
                # A transition may leave ``current.idfnew`` and other auxiliary
                # files.  Isolate every hop so a prior step's output cannot be
                # misread as the next step's result.
                step_work_dir = work_dir / label
                step_work_dir.mkdir()
                work_idf = step_work_dir / "current.idf"
                shutil.copy2(current, work_idf)
                input_hash = self._file_hash(work_idf)
                for name in RUNTIME_AUXILIARY_FILES:
                    generated = runtime_dir / name
                    if generated.is_file():
                        generated.unlink()
                timed_out = False
                try:
                    completed = subprocess.run(
                        [str(executable), str(work_idf)],
                        cwd=runtime_dir,
                        capture_output=True,
                        text=True,
                        timeout=self.timeout_seconds,
                        check=False,
                    )
                    stdout = self._as_text(completed.stdout)
                    stderr = self._as_text(completed.stderr)
                    returncode = completed.returncode
                except subprocess.TimeoutExpired as error:
                    stdout = self._as_text(error.stdout)
                    stderr = self._as_text(error.stderr)
                    returncode = None
                    timed_out = True
                stdout_log = artifact_dir / f"{label}.stdout.log"
                stderr_log = artifact_dir / f"{label}.stderr.log"
                stdout_log.write_text(stdout, encoding="utf-8")
                stderr_log.write_text(stderr, encoding="utf-8")
                sidecars = self._copy_work_sidecars(step_work_dir, artifact_dir, label)
                sidecars += self._copy_runtime_outputs(runtime_dir, artifact_dir, label)
                warning_auxiliaries = [
                    runtime_dir / name for name in RUNTIME_AUXILIARY_FILES if (runtime_dir / name).is_file()
                ]
                record: dict[str, Any] = {
                    "from_version": step_data["from_version"],
                    "to_version": step_data["to_version"],
                    "transition_executable": step_data["executable"],
                    "input_sha256": input_hash,
                    "returncode": returncode,
                    "timed_out": timed_out,
                    "sidecars": sidecars,
                    "warnings": self._warning_summary(
                        stdout,
                        stderr,
                        stdout_log,
                        stderr_log,
                        output_dir,
                        warning_auxiliaries,
                        sidecars,
                    ),
                }
                if timed_out or returncode != 0:
                    record["status"] = "timed_out" if timed_out else "failed"
                    manifest["steps"].append(record)
                    if timed_out:
                        raise RuntimeError(
                            f"Transition {label} timed out after {self.timeout_seconds} seconds"
                        )
                    raise RuntimeError(f"Transition {label} failed with exit code {returncode}")
                expected_version = EnergyPlusVersion.parse(step_data["to_version"])
                produced = work_idf
                actual_version = self._idf_version(produced)
                alternate = step_work_dir / "current.idfnew"
                if actual_version != expected_version and alternate.is_file():
                    alternate_version = self._idf_version(alternate)
                    if alternate_version == expected_version:
                        produced, actual_version = alternate, alternate_version
                if actual_version != expected_version:
                    record.update({"status": "failed", "actual_version": actual_version.display})
                    manifest["steps"].append(record)
                    raise RuntimeError(
                        f"Transition {label} produced {actual_version.display}, expected {expected_version.display}"
                    )
                stage = stages_dir / f"{source.stem}-{actual_version.label}{source.suffix}"
                shutil.copy2(produced, stage)
                record.update(
                    {
                        "status": "completed",
                        "output_version": actual_version.display,
                        "output_sha256": self._file_hash(stage),
                        "output_file": str(stage.relative_to(output_dir)),
                    }
                )
                manifest["steps"].append(record)
                current = stage
                self._write_manifest(manifest_path, manifest)
            source_hash_after = self._file_hash(source)
            if source_hash_after != source_hash:
                raise RuntimeError("Source hash changed unexpectedly")
            manifest.update(
                {
                    "migration_status": "completed",
                    "final_file": str(current.relative_to(output_dir)),
                    "final_version": self._idf_version(current).display,
                    "final_sha256": self._file_hash(current),
                    "source_sha256_after": source_hash_after,
                }
            )
            result.update(
                {
                    "status": "completed",
                    "migration_status": "completed",
                    "final_path": str(current),
                    "final_sha256": manifest["final_sha256"],
                    "source_sha256_after": manifest["source_sha256_after"],
                    "transition_warnings": self._transition_warning_summaries(manifest),
                }
            )
        except Exception as error:
            manifest.update(
                {
                    "migration_status": "failed",
                    "error": str(error),
                    "source_sha256_after": self._file_hash(source),
                }
            )
            result.update(
                {
                    "status": "failed",
                    "migration_status": "failed",
                    "error": str(error),
                    "transition_warnings": self._transition_warning_summaries(manifest),
                }
            )
        self._write_manifest(manifest_path, manifest)
        return result
