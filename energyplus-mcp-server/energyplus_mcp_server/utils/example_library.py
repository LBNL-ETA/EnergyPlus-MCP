"""Searchable inventory of the installed EnergyPlus example and dataset IDFs.

EnergyPlus ships two reference libraries next to the engine:

* ``ExampleFiles/`` - complete, runnable models that show how objects are
  connected (about 760 files for 26.1).
* ``DataSets/`` - IDF fragments with reusable component data such as
  materials, window constructions, equipment curves, and schedules.

The inventory is rebuilt from the installed tree, never hand-maintained.  A
cheap fingerprint (installed IDD plus file names, sizes, and mtimes) decides
when a rebuild is needed, so a new EnergyPlus release is picked up
automatically.  The build is a plain-text scan (about 0.5 s for 26.1) that runs
lazily on first use and is kept in memory; ``EPLUS_EXAMPLE_INVENTORY_CACHE``
may name a directory in which to persist it across sessions.

Only :meth:`ExampleLibrary.get_objects` uses eppy, and only for the handful of
objects it returns, so field names match what ``idf_modification`` accepts.
"""

from __future__ import annotations

import difflib
import fnmatch
import hashlib
import io
import json
import logging
import os
import re
import tempfile
import threading
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
LIBRARIES = ("examples", "datasets")
CACHE_ENV = "EPLUS_EXAMPLE_INVENTORY_CACHE"
CATALOG_FILE = "ExampleFiles.html"

_HEADER_MAX_LINES = 80
_HEADER_MAX_CHARS = 4000
_SUMMARY_MAX_CHARS = 320
_MAX_SEARCH_LIMIT = 50
_MAX_GET_LIMIT = 20
_MAX_REFERENCED_OBJECTS = 40
_MAX_REFERENCE_DEPTH = 3
_PARSED_FILE_CACHE = 4

# Object families that are not native simulation input: ExpandObjects or a
# ground preprocessor rewrites them, so the file does not show the final
# objects an agent would add to a native IDF.
_PREPROCESSOR_PREFIXES = ("HVACTEMPLATE:", "GROUNDHEATTRANSFER:")
_EXTERNAL_FILE_TYPES = ("SCHEDULE:FILE", "SCHEDULE:FILE:SHADING")
_EXTERNAL_PREFIXES = ("PYTHONPLUGIN:", "EXTERNALINTERFACE:")


class ExampleLibraryError(ValueError):
    """A request named an unknown library, file, or object type."""


# ---------------------------------------------------------------------------
# Plain-text IDF scanning
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RawObject:
    """One IDF object as written, with comments removed."""

    class_name: str
    fields: tuple[str, ...]
    line: int

    @property
    def key(self) -> str:
        return self.class_name.upper()

    @property
    def name(self) -> str:
        return self.fields[0] if self.fields else ""

    def text(self) -> str:
        values = list(self.fields)
        while values and not values[-1]:
            values.pop()
        if not values:
            return f"{self.class_name};"
        return f"{self.class_name},\n  " + ",\n  ".join(values) + ";"


_MACRO_LINE = re.compile(r"^[ \t]*##.*$", re.MULTILINE)
_COMMENT = re.compile(r"!.*")


def _code_only(text: str) -> str:
    """Drop ``##`` macro lines and ``!`` comments, keeping line breaks."""
    if "##" in text:
        text = _MACRO_LINE.sub("", text)
    return _COMMENT.sub("", text)


def _object_chunks(code: str) -> List[str]:
    # Text after the final ';' is not a terminated object.
    return code.split(";")[:-1]


def scan_objects(text: str) -> List[RawObject]:
    """Split IDF text into objects without consulting the IDD.

    Handles ``!`` comments, objects spanning lines, several objects on one
    line, and ``##`` preprocessor macro lines (ignored).
    """
    objects: List[RawObject] = []
    line = 1
    for chunk in _object_chunks(_code_only(text)):
        stripped = chunk.strip()
        if stripped:
            leading = len(chunk) - len(chunk.lstrip())
            parts = [part.strip() for part in stripped.split(",")]
            if parts[0]:
                objects.append(RawObject(parts[0], tuple(parts[1:]), line + chunk.count("\n", 0, leading)))
        line += chunk.count("\n")
    return objects


def count_object_types(text: str) -> tuple[Dict[str, int], Optional[str]]:
    """Fast inventory scan: ``({UPPER class: count}, Version value)``."""
    counts: Dict[str, int] = defaultdict(int)
    version = None
    for chunk in _object_chunks(_code_only(text)):
        head, _, rest = chunk.partition(",")
        key = head.strip().upper()
        if key:
            counts[key] += 1
            if key == "VERSION" and version is None:
                version = rest.split(",", 1)[0].strip() or None
    return dict(counts), version


def extract_header(text: str) -> str:
    """Return the leading ``!`` comment block, skipping ``!-`` editor lines."""
    lines: List[str] = []
    for line in text[:20000].splitlines():
        stripped = line.strip()
        if not stripped:
            if lines:
                lines.append("")
            continue
        if not stripped.startswith("!"):
            break
        if stripped.startswith("!-"):
            continue
        lines.append(stripped[1:].rstrip()[1:] if stripped[1:2] == " " else stripped[1:].rstrip())
        if len(lines) >= _HEADER_MAX_LINES:
            break
    header = "\n".join(lines).strip()
    return header[:_HEADER_MAX_CHARS]


_SECTION = re.compile(r"^([A-Z][A-Za-z /()]+?):\s*(.*)$")


def summarize_header(header: str) -> str:
    """Condense the header's description/highlights into one short sentence."""
    sections: Dict[str, List[str]] = {}
    current: Optional[str] = None
    for line in header.splitlines():
        match = _SECTION.match(line)
        if match and not line.startswith(" "):
            current = match.group(1).strip().lower()
            sections[current] = [match.group(2).strip()]
        elif current and line.strip():
            sections[current].append(line.strip())
        elif not line.strip():
            current = None
    parts = [
        " ".join(sections[key]).strip()
        for key in ("basic file description", "highlights")
        if key in sections
    ]
    summary = " ".join(part for part in parts if part)
    if not summary:
        summary = " ".join(line.strip() for line in header.splitlines()[1:4] if line.strip())
    return _truncate(re.sub(r"\s+", " ", summary))


def _truncate(value: str, limit: int = _SUMMARY_MAX_CHARS) -> str:
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# IDD and ExampleFiles.html metadata
# ---------------------------------------------------------------------------

_IDD_CLASS = re.compile(r"^([A-Za-z][^,;!\\]*?)\s*[,;]\s*(?:!.*)?$")
_IDD_FIELD = re.compile(r"^[AN]\d+\s*[,;]")


def read_idd_classes(idd_path: str) -> tuple[str, Dict[str, str]]:
    """Return (EnergyPlus version, {UPPER class name: canonical name})."""
    version = ""
    classes: Dict[str, str] = {}
    with open(idd_path, encoding="latin-1") as handle:
        for line in handle:
            if not version and line.startswith("!IDD_Version"):
                version = line.split(None, 1)[1].strip() if len(line.split()) > 1 else ""
            # Class names normally start in column 0, but a few 26.1 entries
            # are indented by one space; field lines are ``A1,``/``N1,``.
            stripped = line.strip()
            if not stripped or stripped[0] in "!\\" or _IDD_FIELD.match(stripped):
                continue
            match = _IDD_CLASS.match(stripped)
            if match:
                name = match.group(1).strip()
                classes.setdefault(name.upper(), name)
    return version, classes


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.header: List[str] = []
        self.rows: List[List[str]] = []
        self._row: Optional[List[str]] = None
        self._cell: Optional[List[str]] = None
        self._is_header = False

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag == "tr":
            self._flush_row()
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._flush_cell()
            self._cell = []
            self._is_header = tag == "th"

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th"):
            self._flush_cell()
        elif tag in ("tr", "table"):
            self._flush_row()

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def _flush_cell(self) -> None:
        if self._cell is None or self._row is None:
            return
        value = re.sub(r"\s+", " ", "".join(self._cell)).strip()
        (self.header if self._is_header else self._row).append(value)
        self._cell = None

    def _flush_row(self) -> None:
        self._flush_cell()
        if self._row:
            self.rows.append(self._row)
        self._row = None

    def close(self) -> None:
        super().close()
        self._flush_row()


def read_example_catalog(path: str) -> Dict[str, Dict[str, Any]]:
    """Parse EnergyPlus' generated ``ExampleFiles.html`` summary table.

    Returns ``{filename: {description, location, floor_area_m2, stories,
    zones, features}}``.  Missing or malformed catalogs yield ``{}``; the
    inventory never depends on this optional enrichment.
    """
    try:
        parser = _TableParser()
        with open(path, encoding="latin-1") as handle:
            parser.feed(handle.read())
        parser.close()
    except OSError:
        return {}
    header = parser.header
    if not header or header[0].lower() != "filename":
        return {}
    column = {name.rstrip("?").lower(): index for index, name in enumerate(header)}
    catalog: Dict[str, Dict[str, Any]] = {}
    for row in parser.rows:
        if len(row) != len(header):
            continue

        def cell(name: str) -> str:
            index = column.get(name)
            return row[index] if index is not None else ""

        catalog[row[0]] = {
            "description": cell("description"),
            "location": cell("location"),
            "floor_area_m2": _number(cell("floorarea-m2")),
            "stories": _number(cell("numstories")),
            "zones": _number(cell("numzones")),
            "features": [
                header[index].rstrip("?")
                for index, value in enumerate(row)
                if header[index].endswith("?") and value.strip().lower() == "true"
            ],
        }
    return catalog


def _number(value: str) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------


def _idf_files(root: str) -> List[str]:
    found: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for filename in sorted(filenames):
            if filename.lower().endswith(".idf"):
                found.append(os.path.relpath(os.path.join(dirpath, filename), root).replace(os.sep, "/"))
    return found


def _stat_token(path: str) -> str:
    try:
        stat = os.stat(path)
    except OSError:
        return f"{path}:missing"
    return f"{path}:{stat.st_size}:{stat.st_mtime_ns}"


def _flags(object_counts: Dict[str, int]) -> List[str]:
    keys = [key.upper() for key in object_counts]
    flags: List[str] = []
    if any(key.startswith(_PREPROCESSOR_PREFIXES) for key in keys):
        flags.append("needs_preprocessor")
    if any(key in _EXTERNAL_FILE_TYPES or key.startswith(_EXTERNAL_PREFIXES) for key in keys):
        flags.append("external_dependencies")
    return flags


def _describe_file(path: str, classes: Dict[str, str]) -> Dict[str, Any]:
    with open(path, encoding="latin-1") as handle:
        text = handle.read()
    raw_counts, version = count_object_types(text)
    counts: Dict[str, int] = defaultdict(int)
    for key, count in raw_counts.items():
        counts[classes.get(key, key)] += count
    header = extract_header(text)
    return {
        "size": os.path.getsize(path),
        "version": version,
        "objects": dict(sorted(counts.items())),
        "object_count": sum(counts.values()),
        "zones": counts.get(classes.get("ZONE", "Zone"), 0),
        "flags": _flags(counts),
        "header": header,
        "summary": summarize_header(header),
    }


class ExampleLibrary:
    """Lazily built, fingerprint-checked index of the installed libraries."""

    def __init__(self, config: Any, cache_dir: Optional[str] = None) -> None:
        self.config = config
        self.cache_dir = cache_dir if cache_dir is not None else os.getenv(CACHE_ENV) or None
        self._lock = threading.Lock()
        self._inventory: Optional[Dict[str, Any]] = None
        self._fingerprint: Optional[str] = None
        self._index: Dict[str, Dict[str, List[str]]] = {}
        self._parsed: "OrderedDict[str, tuple[str, List[RawObject]]]" = OrderedDict()

    # -- locations -----------------------------------------------------------------

    def roots(self) -> Dict[str, str]:
        energyplus = self.config.energyplus
        install = getattr(energyplus, "installation_path", "") or ""
        return {
            "examples": getattr(energyplus, "example_files_path", "") or os.path.join(install, "ExampleFiles"),
            "datasets": os.path.join(install, "DataSets") if install else "",
        }

    def fingerprint(self) -> str:
        digest = hashlib.sha256(f"schema={SCHEMA_VERSION}".encode())
        digest.update(_stat_token(self.config.energyplus.idd_path).encode())
        for library, root in sorted(self.roots().items()):
            digest.update(f"\n[{library}]{root}".encode())
            if not root or not os.path.isdir(root):
                continue
            digest.update(_stat_token(os.path.join(root, CATALOG_FILE)).encode())
            for relative in _idf_files(root):
                digest.update(_stat_token(os.path.join(root, relative)).encode())
        return digest.hexdigest()

    # -- inventory lifecycle --------------------------------------------------------

    def inventory(self) -> Dict[str, Any]:
        fingerprint = self.fingerprint()
        with self._lock:
            if self._inventory is None or fingerprint != self._fingerprint:
                inventory = self._load_cached(fingerprint) or self._build(fingerprint)
                self._inventory = inventory
                self._fingerprint = fingerprint
                self._index = self._build_index(inventory)
                self._parsed.clear()
            return self._inventory

    def _cache_path(self, fingerprint: str) -> Optional[Path]:
        if not self.cache_dir:
            return None
        return Path(self.cache_dir) / f"example-inventory-{fingerprint[:24]}.json"

    def _load_cached(self, fingerprint: str) -> Optional[Dict[str, Any]]:
        path = self._cache_path(fingerprint)
        if path is None or not path.is_file():
            return None
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            logger.warning("Ignoring unreadable example inventory cache %s: %s", path, exc)
            return None
        if data.get("fingerprint") != fingerprint or data.get("schema") != SCHEMA_VERSION:
            return None
        return data

    def _build(self, fingerprint: str) -> Dict[str, Any]:
        idd_path = self.config.energyplus.idd_path
        version, classes = read_idd_classes(idd_path) if idd_path and os.path.isfile(idd_path) else ("", {})
        libraries: Dict[str, Any] = {}
        for library, root in self.roots().items():
            files: Dict[str, Any] = {}
            available = bool(root) and os.path.isdir(root)
            if available:
                catalog = read_example_catalog(os.path.join(root, CATALOG_FILE)) if library == "examples" else {}
                for relative in _idf_files(root):
                    try:
                        entry = _describe_file(os.path.join(root, relative), classes)
                    except OSError as exc:
                        logger.warning("Skipping unreadable library file %s: %s", relative, exc)
                        continue
                    entry["catalog"] = catalog.get(os.path.basename(relative))
                    if entry["catalog"] and entry["catalog"].get("description"):
                        entry["summary"] = _truncate(entry["catalog"]["description"])
                    files[relative] = entry
            libraries[library] = {"root": root, "available": available, "files": files}
        inventory = {
            "schema": SCHEMA_VERSION,
            "fingerprint": fingerprint,
            "energyplus_version": version,
            "idd_path": idd_path,
            "classes": sorted(classes.values()),
            "libraries": libraries,
        }
        logger.info(
            "Built EnergyPlus example inventory: %s",
            {name: len(lib["files"]) for name, lib in libraries.items()},
        )
        self._write_cache(inventory)
        return inventory

    def _write_cache(self, inventory: Dict[str, Any]) -> None:
        path = self._cache_path(inventory["fingerprint"])
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, suffix=".tmp") as handle:
                json.dump(inventory, handle)
            os.replace(handle.name, path)
        except OSError as exc:
            logger.warning("Could not persist example inventory to %s: %s", path, exc)

    @staticmethod
    def _build_index(inventory: Dict[str, Any]) -> Dict[str, Dict[str, List[str]]]:
        index: Dict[str, Dict[str, List[str]]] = {}
        for library, data in inventory["libraries"].items():
            by_type: Dict[str, List[str]] = defaultdict(list)
            for relative, entry in data["files"].items():
                for object_type in entry["objects"]:
                    by_type[object_type.upper()].append(relative)
            index[library] = dict(by_type)
        return index

    # -- helpers ----------------------------------------------------------------------

    @staticmethod
    def _libraries(library: Optional[str]) -> List[str]:
        if library in (None, "", "all"):
            return list(LIBRARIES)
        if library not in LIBRARIES:
            raise ExampleLibraryError(f"library must be one of {list(LIBRARIES)} or 'all', got {library!r}")
        return [library]

    def _canonical_types(self, requested: Sequence[str]) -> List[str]:
        """Resolve requested class names (case-insensitive, ``*`` wildcards)."""
        classes = self.inventory()["classes"]
        by_upper = {name.upper(): name for name in classes}
        resolved: List[str] = []
        for raw in requested:
            value = (raw or "").strip()
            if not value:
                continue
            if any(char in value for char in "*?["):
                matches = [name for name in classes if fnmatch.fnmatchcase(name.upper(), value.upper())]
                if not matches:
                    raise ExampleLibraryError(f"No EnergyPlus object type matches pattern {value!r}")
                resolved.extend(matches)
                continue
            canonical = by_upper.get(value.upper())
            if canonical is None and not classes:
                canonical = value
            if canonical is None:
                raise ExampleLibraryError(
                    f"Unknown EnergyPlus object type {value!r}. "
                    f"Close matches: {self._suggest_types(value)}. "
                    "Use action='object_types' to browse valid names."
                )
            resolved.append(canonical)
        return list(dict.fromkeys(resolved))

    def _suggest_types(self, value: str, limit: int = 8) -> List[str]:
        classes = self.inventory()["classes"]
        upper = value.upper()
        contains = [name for name in classes if upper in name.upper()]
        close = difflib.get_close_matches(value, classes, n=limit, cutoff=0.6)
        return list(dict.fromkeys(close + contains))[:limit]

    def _locate(self, file: str, library: Optional[str]) -> tuple[str, str, Dict[str, Any]]:
        inventory = self.inventory()
        wanted = (file or "").strip().replace("\\", "/")
        if not wanted:
            raise ExampleLibraryError("file is required")
        for name in self._libraries(library):
            files = inventory["libraries"][name]["files"]
            if wanted in files:
                return name, wanted, files[wanted]
            base = os.path.basename(wanted)
            matches = [relative for relative in files if os.path.basename(relative) == base]
            if len(matches) == 1:
                return name, matches[0], files[matches[0]]
            if len(matches) > 1:
                raise ExampleLibraryError(f"{file!r} is ambiguous in {name}: {matches}")
        candidates = [
            relative
            for name in self._libraries(library)
            for relative in inventory["libraries"][name]["files"]
        ]
        suggestions = difflib.get_close_matches(os.path.basename(wanted), candidates, n=5, cutoff=0.5)
        raise ExampleLibraryError(f"{file!r} is not in the EnergyPlus library. Close matches: {suggestions}")

    def _file_objects(self, path: str) -> List[RawObject]:
        token = _stat_token(path)
        cached = self._parsed.get(path)
        if cached and cached[0] == token:
            self._parsed.move_to_end(path)
            return cached[1]
        with open(path, encoding="latin-1") as handle:
            objects = scan_objects(handle.read())
        self._parsed[path] = (token, objects)
        while len(self._parsed) > _PARSED_FILE_CACHE:
            self._parsed.popitem(last=False)
        return objects

    @staticmethod
    def _file_result(library: str, relative: str, entry: Dict[str, Any], matched: Iterable[str] = ()) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "file": relative,
            "library": library,
            "summary": entry.get("summary") or "",
            "zones": entry.get("zones", 0),
            "object_count": entry.get("object_count", 0),
            "size_kb": round(entry.get("size", 0) / 1024),
        }
        counts = {name: entry["objects"][name] for name in matched if name in entry["objects"]}
        if counts:
            result["matched_objects"] = counts
        if entry.get("flags"):
            result["flags"] = entry["flags"]
        return result

    # -- public operations -----------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        inventory = self.inventory()
        return {
            "energyplus_version": inventory["energyplus_version"],
            "libraries": {
                name: {
                    "root": data["root"],
                    "available": data["available"],
                    "idf_files": len(data["files"]),
                    "object_types_covered": len(self._index.get(name, {})),
                }
                for name, data in inventory["libraries"].items()
            },
            "object_types_in_idd": len(inventory["classes"]),
            "fingerprint": inventory["fingerprint"][:16],
            "persistent_cache": bool(self.cache_dir),
        }

    def search(
        self,
        object_types: Optional[Sequence[str]] = None,
        keywords: Optional[Sequence[str]] = None,
        features: Optional[Sequence[str]] = None,
        library: Optional[str] = None,
        max_zones: Optional[int] = None,
        limit: int = 8,
    ) -> Dict[str, Any]:
        """Find library files containing *all* requested object types.

        Keywords and features narrow the results further.  Results are ranked
        by keyword hits, then files that need a preprocessor last, then the
        smallest files first because they are easiest to read and adapt.
        """
        types = self._canonical_types(object_types or [])
        terms = [term.lower() for term in (keywords or []) if term and term.strip()]
        wanted_features = {feature.rstrip("?").lower() for feature in (features or []) if feature}
        if not (types or terms or wanted_features):
            raise ExampleLibraryError("Provide at least one of object_types, keywords, or features")
        limit = max(1, min(int(limit or 8), _MAX_SEARCH_LIMIT))
        inventory = self.inventory()
        output: Dict[str, Any] = {"object_types": types, "keywords": terms, "results": {}}
        for name in self._libraries(library):
            files = inventory["libraries"][name]["files"]
            if types:
                candidate_sets = [set(self._index.get(name, {}).get(t.upper(), [])) for t in types]
                candidates = set.intersection(*candidate_sets) if candidate_sets else set()
            else:
                candidates = set(files)
            ranked = []
            for relative in candidates:
                entry = files[relative]
                if max_zones is not None and entry.get("zones", 0) > max_zones:
                    continue
                catalog = entry.get("catalog") or {}
                if wanted_features:
                    have = {feature.lower() for feature in catalog.get("features", [])}
                    if not wanted_features <= have:
                        continue
                hits = 0
                if terms:
                    haystack = " ".join(
                        [relative, entry.get("summary", ""), entry.get("header", ""), catalog.get("description", "")]
                    ).lower()
                    hits = sum(term in haystack for term in terms)
                    if not hits:
                        continue
                penalty = 1 if "needs_preprocessor" in entry.get("flags", []) else 0
                ranked.append((-hits, penalty, entry.get("object_count", 0), relative))
            ranked.sort()
            output["results"][name] = {
                "total_matches": len(ranked),
                "files": [self._file_result(name, rel, files[rel], types) for *_, rel in ranked[:limit]],
            }
        output["next_step"] = (
            "Call action='describe' on a candidate, then action='get_objects' with its file and "
            "object_type to fetch the objects and the schedules/curves/constructions they reference."
        )
        return output

    def object_types(self, pattern: str = "", library: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        """List IDD object types matching ``pattern`` with how many files use each."""
        inventory = self.inventory()
        limit = max(1, min(int(limit or 50), 200))
        query = (pattern or "").strip().upper()
        names = inventory["classes"]
        if query:
            if any(char in query for char in "*?["):
                names = [name for name in names if fnmatch.fnmatchcase(name.upper(), query)]
            else:
                names = [name for name in names if query in name.upper()]
        libraries = self._libraries(library)
        rows = [
            {
                "object_type": name,
                **{
                    f"{lib}_files": len(self._index.get(lib, {}).get(name.upper(), []))
                    for lib in libraries
                },
            }
            for name in names
        ]
        return {"pattern": pattern, "total_matches": len(rows), "object_types": rows[:limit]}

    def describe(self, file: str, library: Optional[str] = None) -> Dict[str, Any]:
        name, relative, entry = self._locate(file, library)
        objects = sorted(entry["objects"].items(), key=lambda item: (-item[1], item[0]))
        result = {
            "file": relative,
            "library": name,
            "path": os.path.join(self.inventory()["libraries"][name]["root"], relative),
            "version": entry.get("version"),
            "zones": entry.get("zones", 0),
            "object_count": entry.get("object_count", 0),
            "size_kb": round(entry.get("size", 0) / 1024),
            "flags": entry.get("flags", []),
            "catalog": entry.get("catalog"),
            "header": entry.get("header", ""),
            "objects": dict(objects),
        }
        if "needs_preprocessor" in result["flags"]:
            result["warning"] = (
                "This file relies on HVACTemplate or GroundHeatTransfer objects that ExpandObjects "
                "or a ground preprocessor rewrites; prefer a native example for object structure."
            )
        return result

    def get_objects(
        self,
        file: str,
        object_type: str,
        library: Optional[str] = None,
        names: Optional[Sequence[str]] = None,
        name_contains: Optional[str] = None,
        limit: int = 3,
        include_references: bool = True,
        reference_depth: int = 1,
        output_format: str = "fields",
    ) -> Dict[str, Any]:
        """Return objects of one type plus, optionally, the objects they reference."""
        if output_format not in ("fields", "idf", "both"):
            raise ExampleLibraryError("format must be 'fields', 'idf', or 'both'")
        resolved = self._canonical_types([object_type])
        if len(resolved) != 1:
            raise ExampleLibraryError(
                f"object_type must name exactly one EnergyPlus type; {object_type!r} matched {resolved[:10]}"
            )
        canonical = resolved[0]
        library_name, relative, entry = self._locate(file, library)
        path = os.path.join(self.inventory()["libraries"][library_name]["root"], relative)
        raw_objects = self._file_objects(path)
        limit = max(1, min(int(limit or 3), _MAX_GET_LIMIT))
        depth = max(0, min(int(reference_depth or 0), _MAX_REFERENCE_DEPTH)) if include_references else 0

        matches = [obj for obj in raw_objects if obj.key == canonical.upper()]
        total = len(matches)
        if names:
            wanted = {value.strip().upper() for value in names if value}
            matches = [obj for obj in matches if obj.name.upper() in wanted]
        if name_contains:
            needle = name_contains.strip().upper()
            matches = [obj for obj in matches if needle in obj.name.upper()]
        selected = matches[:limit]

        result: Dict[str, Any] = {
            "file": relative,
            "library": library_name,
            "energyplus_version": self.inventory()["energyplus_version"],
            "object_type": canonical,
            "total_in_file": total,
            "matched": len(matches),
            "returned": len(selected),
            "objects": [],
            "referenced_objects": [],
        }
        if not selected:
            if total == 0:
                result["hint"] = (
                    f"{relative} has no {canonical} objects; use action='search' with "
                    f"object_types=['{canonical}'] to find files that do."
                )
            return result

        by_name: Dict[str, List[RawObject]] = defaultdict(list)
        for obj in raw_objects:
            if obj.name:
                by_name[obj.name.upper()].append(obj)

        included = {id(obj) for obj in selected}
        primary = self._to_eppy(selected)
        result["objects"] = [self._render(obj, output_format) for obj in primary]
        frontier = list(zip(primary, result["objects"]))
        truncated_refs = False
        for _ in range(depth):
            discovered: List[RawObject] = []
            for eppy_obj, rendered in frontier:
                references = []
                for field, value in self._referencing_fields(eppy_obj):
                    info = eppy_obj.getfieldidd(field) or {}
                    valid = {name.upper() for name in info.get("validobjects", ())}
                    targets = [cand for cand in by_name.get(str(value).upper(), []) if cand.key in valid]
                    references.append(
                        {
                            "field": field,
                            "name": value,
                            "types": sorted({cand.class_name for cand in targets}),
                            "found": bool(targets),
                        }
                    )
                    for target in targets:
                        if id(target) in included:
                            continue
                        if len(included) - len(selected) + len(discovered) >= _MAX_REFERENCED_OBJECTS:
                            truncated_refs = True
                            continue
                        included.add(id(target))
                        discovered.append(target)
                if references:
                    rendered["references"] = references
            if not discovered:
                break
            parsed = self._to_eppy(discovered)
            rendered_refs = [self._render(obj, output_format) for obj in parsed]
            result["referenced_objects"].extend(rendered_refs)
            frontier = list(zip(parsed, rendered_refs))
        if truncated_refs:
            result["truncated_references"] = f"Stopped after {_MAX_REFERENCED_OBJECTS} referenced objects"
        if matches[limit:]:
            result["more_available"] = len(matches) - limit
        if "needs_preprocessor" in entry.get("flags", []):
            result["warning"] = "Source file uses HVACTemplate/GroundHeatTransfer preprocessor objects."
        result["notes"] = [
            "Values are illustrative inputs from an example, not recommended defaults.",
            "Field names are eppy names for the installed IDD; check the target model's version "
            "before copying because field names and order change between releases.",
            "Rename objects and remap zone, node, and schedule references before adding them to a model.",
        ]
        return result

    # -- eppy bridge ----------------------------------------------------------------

    def _ensure_idd(self) -> Any:
        from eppy.modeleditor import IDF

        if IDF.getiddname() is None:
            IDF.setiddname(self.config.energyplus.idd_path)
        return IDF

    def _to_eppy(self, objects: Sequence[RawObject]) -> List[Any]:
        """Parse only the chosen objects with eppy, preserving their order."""
        IDF = self._ensure_idd()
        text = "\n".join(obj.text() for obj in objects)
        idf = IDF(io.StringIO(text))
        parsed_by_key: Dict[str, List[Any]] = defaultdict(list)
        for key, bucket in idf.idfobjects.items():
            parsed_by_key[key.upper()].extend(bucket)
        positions: Dict[str, int] = defaultdict(int)
        ordered = []
        for obj in objects:
            bucket = parsed_by_key.get(obj.key, [])
            index = positions[obj.key]
            if index < len(bucket):
                ordered.append(bucket[index])
                positions[obj.key] += 1
        return ordered

    @staticmethod
    def _referencing_fields(eppy_obj: Any) -> List[tuple[str, Any]]:
        fields = []
        for field, value in zip(eppy_obj.fieldnames[1:], eppy_obj.fieldvalues[1:]):
            if value in ("", None) or isinstance(value, (int, float)):
                continue
            try:
                info = eppy_obj.getfieldidd(field) or {}
            except Exception:  # pragma: no cover - eppy extensible-field edge cases
                continue
            if info.get("validobjects"):
                fields.append((field, value))
        return fields

    @staticmethod
    def _render(eppy_obj: Any, output_format: str) -> Dict[str, Any]:
        fields = {
            field: value
            for field, value in zip(eppy_obj.fieldnames[1:], eppy_obj.fieldvalues[1:])
            if value not in ("", None)
        }
        name = fields.get("Name", "")
        rendered: Dict[str, Any] = {"type": eppy_obj.key, "name": name}
        if output_format in ("fields", "both"):
            rendered["fields"] = fields
        if output_format in ("idf", "both"):
            rendered["idf_text"] = str(eppy_obj).strip()
        return rendered


_LIBRARIES: Dict[int, ExampleLibrary] = {}
_LIBRARIES_LOCK = threading.Lock()


def get_example_library(config: Any) -> ExampleLibrary:
    """Return the process-wide library for ``config`` (one per server)."""
    with _LIBRARIES_LOCK:
        library = _LIBRARIES.get(id(config))
        if library is None:
            library = ExampleLibrary(config)
            _LIBRARIES[id(config)] = library
        return library
