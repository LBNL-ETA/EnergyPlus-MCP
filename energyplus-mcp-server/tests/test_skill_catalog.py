import asyncio
import json
import re
from pathlib import Path

import pytest

from energyplus_mcp_server.tool_surface import (
    DOMAIN_TOOLS,
    MASTER_TOOLS,
    WORKFLOW_COMPAT_MODULES,
    expected_tool_names,
)
from energyplus_mcp_server.utils.skill_catalog import SKILLS_ROOT, SkillCatalog, SkillError


def write_skill(root: Path, name: str, text: str, extra: dict[str, str] | None = None) -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(text)
    for relative, content in (extra or {}).items():
        (directory / relative).write_text(content)
    return directory


def test_bundled_skills_load_and_include_learn_from_examples():
    listing = SkillCatalog().list()
    by_name = {skill["name"]: skill for skill in listing["skills"]}

    assert "learn-from-examples" in by_name
    assert by_name["learn-from-examples"]["files"] == ["datasets-guide.md"]
    skill = SkillCatalog().get("learn-from-examples")
    assert skill["content"].startswith("# Learn from EnergyPlus examples")
    assert "---" not in skill["content"].splitlines()[0]
    guide = SkillCatalog().get("learn-from-examples", "datasets-guide.md")
    assert "WindowConstructs.idf" in guide["content"]


def test_bundled_skills_only_reference_registered_tools():
    all_tools = expected_tool_names(
        {
            "mode": "hybrid",
            "domains": {name: True for name in DOMAIN_TOOLS},
            "compatibility": {"workflow_managers": False},
        }
    )
    deprecated = {tool for _, tool in WORKFLOW_COMPAT_MODULES}
    for skill_file in SKILLS_ROOT.glob("*/*.md"):
        text = skill_file.read_text()
        called = set(re.findall(r"`([a-z_]+)\(", text))
        assert called, skill_file
        assert called <= all_tools | set(MASTER_TOOLS), (skill_file, called - all_tools)
        assert not called & deprecated, skill_file


def test_supporting_files_are_whitelisted(tmp_path):
    write_skill(
        tmp_path,
        "demo",
        "---\nname: demo\ndescription: Demo skill.\n---\n# Demo\n",
        {"notes.md": "notes"},
    )
    (tmp_path / "secret.md").write_text("outside the skill")
    catalog = SkillCatalog(tmp_path)

    assert catalog.get("demo", "notes.md")["content"] == "notes"
    for bad in ("../secret.md", "/etc/passwd", "missing.md"):
        with pytest.raises(SkillError, match="no supporting file"):
            catalog.get("demo", bad)
    with pytest.raises(SkillError, match="Unknown skill"):
        catalog.get("nope")


@pytest.mark.parametrize(
    ("text", "extra", "message"),
    [
        ("# no front matter\n", None, "front matter"),
        ("---\nname: other\ndescription: x\n---\n", None, "must match its directory"),
        ("---\nname: demo\n---\n", None, "description"),
        ("---\nname: Demo Skill\ndescription: x\n---\n", None, "lowercase"),
        ("---\nname: demo\ndescription: x\n---\n", {"run.py": "print()"}, "only Markdown/JSON"),
    ],
)
def test_malformed_skills_are_rejected(tmp_path, text, extra, message):
    write_skill(tmp_path, "demo", text, extra)

    with pytest.raises(SkillError, match=message):
        SkillCatalog(tmp_path).list()


def test_skill_tools_return_json(monkeypatch):
    from energyplus_mcp_server.tools import skills as tool_module

    tools = {}

    class FakeMCP:
        def tool(self, *args, **kwargs):
            def decorate(fn):
                tools[fn.__name__] = fn
                return fn

            return decorate

    tool_module.register(FakeMCP(), object(), object())

    listed = json.loads(asyncio.run(tools["list_skills"]()))
    assert "learn-from-examples" in {skill["name"] for skill in listed["skills"]}
    loaded = json.loads(asyncio.run(tools["get_skill"]("learn-from-examples")))
    assert "example_library" in loaded["content"]
    missing = json.loads(asyncio.run(tools["get_skill"]("unknown")))
    assert missing["error"].startswith("Unknown skill")
