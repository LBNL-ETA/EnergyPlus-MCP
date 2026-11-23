"""Refuse models that could escape a caller's workspace when run over HTTP.

Per-token scoping (energyplus_mcp_server.scope) confines what the server's
tools read and write. A model is different: EnergyPlus itself acts on what the
model says. Over the streamable-HTTP transport, before EnergyPlus runs a
caller's model, this check rejects:

- ``PythonPlugin:*`` objects, which make EnergyPlus import and run Python code;
- ``ExternalInterface:*`` objects (BCVTB co-simulation and FMUs), which load
  and run external programs;
- file references (``Schedule:File``, ``Table:Lookup`` external files, ...)
  that point outside the caller's readable folders, or that use ``..``.

Stdio callers are unaffected: a local server runs whatever the user's own
model asks for.

EnergyPlus Model Context Protocol Server (EnergyPlus-MCP)
Copyright (c) 2025, The Regents of the University of California,
through Lawrence Berkeley National Laboratory (subject to receipt of
any required approvals from the U.S. Dept. of Energy). All rights reserved.

See License.txt in the parent directory for license details.
"""

from __future__ import annotations

import os
import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Iterator

# Object classes (lower case) that run code outside EnergyPlus.
BLOCKED_PREFIXES = ("pythonplugin:", "externalinterface")

# Object class (lower case) -> 1-based field index holding a file path, from the
# EnergyPlus 26.1 IDD.
FILE_FIELDS = {
    "schedule:file": 3,
    "schedule:file:shading": 1,
    "construction:windowdatafile": 2,
    "coil:dx:ashrae205:performance": 2,
    "chiller:electric:ashrae205": 2,
    "table:independentvariable": 8,
    "table:lookup": 8,
}


class UnsafeModelError(PermissionError):
    """The model asks EnergyPlus to do something a remote caller may not."""


def iter_objects(text: str) -> Iterator[tuple[str, list[str]]]:
    """Yield (class name, [field values]) for each object in IDF text."""
    without_comments = "\n".join(line.split("!", 1)[0] for line in text.splitlines())
    for statement in without_comments.split(";"):
        parts = [part.strip() for part in statement.split(",")]
        if parts and parts[0]:
            yield parts[0], parts[1:]


def _is_absolute(value: str) -> bool:
    return PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute() \
        or bool(re.match(r"^[A-Za-z]:", value))


def _has_parent_reference(value: str) -> bool:
    return ".." in re.split(r"[\\/]+", value)


def find_problems(text: str, can_read=None) -> list[str]:
    """Return a description of each unsafe object in IDF ``text``.

    ``can_read`` decides whether an absolute file reference is allowed; with
    None, absolute references are always rejected.
    """
    problems: list[str] = []
    for class_name, fields in iter_objects(text):
        lowered = class_name.lower()
        name = fields[0] if fields else ""
        if lowered.startswith(BLOCKED_PREFIXES):
            problems.append(f"{class_name} '{name}': runs external code, which is not "
                            "allowed on a remote server")
            continue
        index = FILE_FIELDS.get(lowered)
        if not index or len(fields) < index:
            continue
        value = fields[index - 1].strip().strip('"')
        if not value:
            continue
        if _has_parent_reference(value):
            problems.append(f"{class_name} '{name}': file reference '{value}' uses '..'")
        elif _is_absolute(value) and not (can_read and can_read(os.path.realpath(value))):
            problems.append(f"{class_name} '{name}': file '{value}' is outside the folders "
                            "this token may read")
    return problems


def check_model_for_caller(config, idf_path: str) -> None:
    """Raise UnsafeModelError if a remote (HTTP) caller's model is unsafe to run.

    Relative file references are allowed: EnergyPlus resolves them against the
    run directory and the model's own folder, which are inside the caller's
    workspace, and against its own installation.
    """
    from ..scope import current_scope

    scope = current_scope(config)
    if scope is None:
        return
    with open(idf_path, encoding="utf-8", errors="replace") as handle:
        problems = find_problems(handle.read(), scope.can_read)
    if problems:
        raise UnsafeModelError(
            "This model cannot run on a remote server:\n- " + "\n- ".join(problems)
            + "\nRemove these objects. For data files, upload them with file_transfer "
            "and reference them by the server_path it returns."
        )
