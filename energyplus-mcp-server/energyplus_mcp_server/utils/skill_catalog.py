"""Discover and serve the agent skills bundled with this server.

Skills live in ``energyplus_mcp_server/skills/<name>/SKILL.md`` in the Agent
Skills layout: YAML front matter with ``name`` and ``description``, followed
by Markdown instructions.  Supporting ``.md``/``.json`` files may sit beside
it; scripts are deliberately not served.

``list_skills``/``get_skill`` tools are the portable delivery path because every
MCP host exposes tools to the model.  The same folder can later be published
through the MCP skills extension (SEP-2640) or copied into a host's filesystem
skill directory without changing its content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

import yaml

SKILLS_ROOT = Path(__file__).resolve().parent.parent / "skills"
SKILL_FILE = "SKILL.md"
ALLOWED_SUFFIXES = frozenset({".md", ".json"})
MAX_FILE_BYTES = 256 * 1024
_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)


class SkillError(ValueError):
    """A skill is malformed or a request named an unknown skill/file."""


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    directory: Path
    body: str
    metadata: Dict[str, Any]
    files: Tuple[str, ...]


def parse_front_matter(text: str) -> Tuple[Dict[str, Any], str]:
    match = _FRONT_MATTER.match(text)
    if not match:
        raise SkillError("SKILL.md must start with YAML front matter delimited by '---'")
    try:
        metadata = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SkillError(f"invalid YAML front matter: {exc}") from exc
    if not isinstance(metadata, dict):
        raise SkillError("front matter must be a mapping")
    return metadata, text[match.end():].lstrip("\n")


def load_skill(directory: Path) -> Skill:
    skill_file = directory / SKILL_FILE
    metadata, body = parse_front_matter(skill_file.read_text(encoding="utf-8"))
    name = metadata.get("name")
    description = metadata.get("description")
    if not isinstance(name, str) or not _NAME.match(name):
        raise SkillError(f"{skill_file}: 'name' must be lowercase words joined by hyphens")
    if name != directory.name:
        raise SkillError(f"{skill_file}: name {name!r} must match its directory {directory.name!r}")
    if not isinstance(description, str) or not description.strip():
        raise SkillError(f"{skill_file}: 'description' is required")
    files = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path == skill_file:
            continue
        relative = path.relative_to(directory).as_posix()
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            raise SkillError(f"{name}: only Markdown/JSON supporting files are served, found {relative}")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise SkillError(f"{name}: {relative} exceeds {MAX_FILE_BYTES} bytes")
        files.append(relative)
    return Skill(
        name=name,
        description=" ".join(description.split()),
        directory=directory,
        body=body,
        metadata=metadata,
        files=tuple(files),
    )


class SkillCatalog:
    """Reads skills from disk on each call so edits need no server restart."""

    def __init__(self, root: Path | str = SKILLS_ROOT) -> None:
        self.root = Path(root)

    def skills(self) -> List[Skill]:
        if not self.root.is_dir():
            return []
        return [
            load_skill(directory)
            for directory in sorted(self.root.iterdir())
            if directory.is_dir() and (directory / SKILL_FILE).is_file()
        ]

    def list(self) -> Dict[str, Any]:
        return {
            "skills": [
                {"name": skill.name, "description": skill.description, "files": list(skill.files)}
                for skill in self.skills()
            ],
            "usage": "Call get_skill(name) and follow its procedure; fetch supporting files with get_skill(name, file).",
        }

    def get(self, name: str, file: Optional[str] = None) -> Dict[str, Any]:
        skills = {skill.name: skill for skill in self.skills()}
        skill = skills.get((name or "").strip())
        if skill is None:
            raise SkillError(f"Unknown skill {name!r}. Available: {sorted(skills)}")
        if not file or file == SKILL_FILE:
            return {
                "name": skill.name,
                "description": skill.description,
                "content": skill.body,
                "files": list(skill.files),
            }
        relative = PurePosixPath(file.strip().replace("\\", "/")).as_posix()
        if relative not in skill.files:
            raise SkillError(f"{skill.name} has no supporting file {file!r}. Files: {list(skill.files)}")
        return {
            "name": skill.name,
            "file": relative,
            "content": (skill.directory / relative).read_text(encoding="utf-8"),
        }
