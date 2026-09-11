import json
from hashlib import sha256
from pathlib import Path
import re
from subprocess import TimeoutExpired
from types import SimpleNamespace

from energyplus_mcp_server.utils.model_upgrade import EnergyPlusVersion, ModelUpgrade


def _config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        paths=SimpleNamespace(workspace_root=str(tmp_path)),
        energyplus=SimpleNamespace(
            installation_path=str(tmp_path / "installation"),
            executable_path=str(tmp_path / "energyplus"),
        ),
    )


def _source(tmp_path: Path, version: str = "9.2") -> Path:
    path = tmp_path / "source.idf"
    path.write_text(f"! ordinary comment\nVersion, ! comment after the object header\n  {version}; ! version comment\n")
    return path


def _step(transition_dir: Path, source: str, target: str, *, mapping: bool = True) -> None:
    transition_dir.mkdir(exist_ok=True)
    from_version = EnergyPlusVersion.parse(source)
    to_version = EnergyPlusVersion.parse(target)
    (transition_dir / f"Transition-{from_version.label}-to-{to_version.label}").write_text("test")
    (transition_dir / f"{from_version.label}-Energy+.idd").write_text("test")
    (transition_dir / f"{to_version.label}-Energy+.idd").write_text("test")
    if mapping:
        (transition_dir / f"Report Variables {from_version.label[1:]} to {to_version.label[1:]}.csv").write_text("test")


def _upgrade(tmp_path: Path, monkeypatch) -> tuple[ModelUpgrade, Path]:
    transition_dir = tmp_path / "transitions"
    monkeypatch.setenv("EPLUS_TRANSITION_DIR", str(transition_dir))
    return ModelUpgrade(_config(tmp_path), timeout_seconds=1), transition_dir


def _successful_transition(command, **_kwargs):
    executable = Path(command[0]).name
    target = executable.split("-to-")[1].removeprefix("V").replace("-", ".")
    input_idf = Path(command[1])
    transitioned = re.sub(
        r"(?m)^(\s*)\d+(?:\.\d+){1,2};",
        rf"\g<1>{target};",
        input_idf.read_text(),
    )
    # Official transition tools may preserve the input and write .idfnew;
    # the runtime must accept that explicit per-hop output, not stale output
    # from a previous hop.
    input_idf.with_name("current.idfnew").write_text(transitioned)
    (Path(_kwargs["cwd"]) / "Transition.audit").write_text("** Warning ** fixture warning\n")
    return SimpleNamespace(returncode=0, stdout="completed\n** Warning ** fixture warning", stderr="")


def test_plan_lists_required_assets_without_writing(tmp_path, monkeypatch):
    upgrade, transition_dir = _upgrade(tmp_path, monkeypatch)
    source = _source(tmp_path)
    original = source.read_bytes()
    _step(transition_dir, "9.2", "9.3")

    result = upgrade.plan(str(source), "9.3")

    assert result["status"] == "ready"
    assert result["writes_files"] is False
    assert result["steps"][0]["from_version"] == "9.2"
    assert {asset["kind"] for asset in result["steps"][0]["assets"]} == {
        "transition_executable",
        "source_idd",
        "target_idd",
        "report_variable_mapping",
    }
    assert result["missing_assets"] == []
    assert source.read_bytes() == original
    assert not (tmp_path / "output").exists()


def test_run_stages_copy_and_preserves_source(tmp_path, monkeypatch):
    upgrade, transition_dir = _upgrade(tmp_path, monkeypatch)
    source = _source(tmp_path)
    source_hash = sha256(source.read_bytes()).hexdigest()
    _step(transition_dir, "9.2", "9.3")
    monkeypatch.setattr("energyplus_mcp_server.utils.model_upgrade.subprocess.run", _successful_transition)

    result = upgrade.run(str(source), "9.3", str(tmp_path / "upgrade"))

    output = tmp_path / "upgrade"
    manifest = json.loads((output / "migration-manifest.json").read_text())
    assert result["status"] == "completed"
    assert result["simulation_validated"] is False
    assert source.read_bytes() == _source_text("9.2")
    assert sha256(source.read_bytes()).hexdigest() == source_hash
    assert manifest["migration_status"] == "completed"
    assert manifest["simulation_validated"] is False
    assert manifest["source_sha256_before"] == manifest["source_sha256_after"] == source_hash
    assert manifest["final_version"] == "9.3"
    assert Path(result["final_path"]).is_file()
    assert result["transition_warnings"][0]["warnings"]["count"] >= 1
    assert not (output / "run_record.json").exists()


def _source_text(version: str) -> bytes:
    return f"! ordinary comment\nVersion, ! comment after the object header\n  {version}; ! version comment\n".encode()


def test_plan_reports_missing_mapping_and_missing_adjacent_chain(tmp_path, monkeypatch):
    upgrade, transition_dir = _upgrade(tmp_path, monkeypatch)
    source = _source(tmp_path)
    _step(transition_dir, "9.2", "9.3", mapping=False)

    missing_mapping = upgrade.plan(str(source), "9.3")
    missing_chain = upgrade.plan(str(source), "9.4")

    assert missing_mapping["status"] == "unavailable"
    assert missing_mapping["missing_assets"][0]["kind"] == "report_variable_mapping"
    assert missing_chain["status"] == "unavailable"
    assert "No official adjacent transition begins at 9.3" in missing_chain["issues"]
    assert not (tmp_path / "upgrade").exists()


def test_existing_output_and_downgrade_are_refused_without_writing(tmp_path, monkeypatch):
    upgrade, transition_dir = _upgrade(tmp_path, monkeypatch)
    source = _source(tmp_path)
    original = source.read_bytes()
    _step(transition_dir, "9.2", "9.3")
    existing_output = tmp_path / "existing-output"
    existing_output.mkdir()
    marker = existing_output / "keep"
    marker.write_text("do not overwrite")

    existing = upgrade.run(str(source), "9.3", str(existing_output))
    downgrade = upgrade.plan(str(source), "9.1")

    assert existing["status"] == "refused"
    assert "already exists" in existing["issues"][-1]
    assert marker.read_text() == "do not overwrite"
    assert downgrade["status"] == "refused"
    assert "Downgrade is not supported" in downgrade["issues"][0]
    assert source.read_bytes() == original


def test_timeout_records_failed_step_and_byte_output(tmp_path, monkeypatch):
    upgrade, transition_dir = _upgrade(tmp_path, monkeypatch)
    source = _source(tmp_path)
    _step(transition_dir, "9.2", "9.3")

    def _timeout(command, **_kwargs):
        raise TimeoutExpired(command, 1, output=b"** Warning ** slow transition", stderr=b"timed out")

    monkeypatch.setattr("energyplus_mcp_server.utils.model_upgrade.subprocess.run", _timeout)
    result = upgrade.run(str(source), "9.3", str(tmp_path / "timed-out"))

    manifest = json.loads((tmp_path / "timed-out" / "migration-manifest.json").read_text())
    record = manifest["steps"][0]
    assert result["status"] == "failed"
    assert record["status"] == "timed_out"
    assert record["timed_out"] is True
    assert record["warnings"]["count"] == 1
    assert "slow transition" in (tmp_path / "timed-out" / record["warnings"]["stdout_log"]).read_text()
    assert source.read_bytes() == _source_text("9.2")
