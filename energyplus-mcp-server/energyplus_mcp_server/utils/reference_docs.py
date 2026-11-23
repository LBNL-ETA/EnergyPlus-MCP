"""Section-level access to the EnergyPlus reference documentation.

The index is built from the LaTeX source of the EnergyPlus manuals for the
installed release by ``.devcontainer/build_reference_docs.py`` (a Docker build
stage).  It covers the Input Output Reference, Engineering Reference, Output
Details and Examples, and Plant Application Guide, split at every heading so a
caller can fetch one object, one field, or one topic.

``get_field`` pairs a field's documentation with its constraints from the
installed ``Energy+.idd`` (required, units, limits, choices, default, notes),
which is what an agent needs to fix an input-processing error.

Index location, first match wins:

1. ``EPLUS_REFERENCE_DOCS_DIR``
2. ``<EnergyPlus installation>/ReferenceDocs`` (where the image installs it)
3. ``<workspace>/work/reference_docs`` (a local build)
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DOCS_ENV = "EPLUS_REFERENCE_DOCS_DIR"
DOCUMENTS = (
    "input-output-reference",
    "engineering-reference",
    "output-details-and-examples",
    "plant-application-guide",
)
KINDS = ("object", "field", "output", "section")
DEFAULT_MAX_CHARS = 12000
MAX_CHARS = 40000
MAX_SEARCH_LIMIT = 30
_OUTLINE_LIMIT = 150
_SNIPPET_CHARS = 240
BUILD_HINT = (
    "Rebuild the Docker image (it installs the index under "
    "<EnergyPlus>/ReferenceDocs), or run: python .devcontainer/build_reference_docs.py "
    "--tag v<EnergyPlus version> --out energyplus-mcp-server/work/reference_docs "
    "(needs git and pandoc)."
)

_IDD_CLASS = re.compile(r"^([A-Za-z][A-Za-z0-9:_\-]*(?: [A-Za-z0-9:_\-]+)*)\s*[,;]\s*(?:!.*)?$")
_IDD_FIELD = re.compile(r"^([AN]\d+)\s*[,;](.*)$")
_IDD_ANNOTATION = re.compile(r"\\([A-Za-z][A-Za-z0-9\-:]*[<>]?)[ \t]*([^\\]*)")
_STOP_WORDS = frozenset(
    "a an and are as at be by for from in is it of on or that the this to was with".split()
)
_IDD_MULTI = {"key", "note", "memo", "object-list", "reference", "reference-class-name", "external-list"}


class ReferenceDocsError(ValueError):
    """A request named an unknown section/object/field or the index is missing."""


# ---------------------------------------------------------------------------
# IDD field definitions
# ---------------------------------------------------------------------------

def parse_idd(idd_path: str) -> Dict[str, Dict[str, Any]]:
    """Parse an IDD into {UPPER class: {"name", "properties", "fields"}}."""
    classes: Dict[str, Dict[str, Any]] = {}
    current: Optional[Dict[str, Any]] = None
    field: Optional[Dict[str, Any]] = None

    def annotate(target: Dict[str, Any], text: str) -> None:
        for key, value in _IDD_ANNOTATION.findall(text):
            value = value.strip()
            if key in ("group",):
                continue
            if key in _IDD_MULTI:
                target.setdefault(key, []).append(value)
            else:
                target[key] = value if value else True

    with open(idd_path, encoding="latin-1") as handle:
        for raw in handle:
            line = raw.split("!", 1)[0].strip() if not raw.lstrip().startswith("\\") else raw.strip()
            if not line:
                continue
            if line.startswith("\\"):
                if line.startswith("\\group"):
                    field = None
                    continue
                if current is not None:
                    annotate(field if field is not None else current["properties"], line)
                continue
            match = _IDD_FIELD.match(line)
            if match and current is not None:
                field = {"id": match.group(1)}
                annotate(field, match.group(2))
                current["fields"].append(field)
                continue
            match = _IDD_CLASS.match(line)
            if match:
                name = match.group(1).strip()
                current = {"name": name, "properties": {}, "fields": []}
                classes.setdefault(name.upper(), current)
                field = None
    return classes


def _normalize(name: str, generalize: int = 0) -> str:
    """Compare field names across IDD, eppy (underscores), and the manuals.

    generalize=1 maps repeated-field numbers to ``#`` ("Speed 2 Flow
    Fraction" ~ "Speed <#> Flow Fraction"); generalize=2 drops them.
    """
    text = name.lower().replace("_", " ")
    if generalize:
        text = re.sub(r"<\s*(#|x|n|\\#)\s*>|\b\d+\b", " # " if generalize == 1 else " ", text)
    # Spacing and punctuation vary ("X-coordinate", "Xcoordinate", "X Coordinate").
    return re.sub(r"[^a-z0-9#]+", "", text)


def _match_name(wanted: str, candidates: List[str]) -> Optional[int]:
    for level in (0, 1, 2):
        target = _normalize(wanted, level)
        for index, candidate in enumerate(candidates):
            if _normalize(candidate, level) == target:
                return index
    return None


def _idd_field_view(field: Dict[str, Any]) -> Dict[str, Any]:
    view: Dict[str, Any] = {"id": field["id"], "name": field.get("field")}
    for key, value in field.items():
        if key in ("id", "field"):
            continue
        if key == "required-field":
            view["required"] = True
        elif key == "key":
            view["choices"] = value
        elif key == "note":
            view["note"] = " ".join(value)
        else:
            view[key.replace("-", "_")] = value
    return view


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

class ReferenceDocs:
    """Lazy, read-only view of the reference documentation index."""

    def __init__(self, config: Any) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._loaded = False
        self._directory: Optional[Path] = None
        self._manifest: Dict[str, Any] = {}
        self._sections: List[Dict[str, Any]] = []
        self._end: List[int] = []
        self._by_label: Dict[str, int] = {}
        self._by_object: Dict[str, List[int]] = {}
        self._object_names: Dict[str, str] = {}
        self._lower: Optional[List[tuple]] = None
        self._idd: Optional[Dict[str, Dict[str, Any]]] = None
        self._idd_version: Optional[str] = None

    # -- location and loading -------------------------------------------------
    def candidate_directories(self) -> List[Path]:
        candidates: List[Path] = []
        env = os.getenv(DOCS_ENV)
        if env:
            candidates.append(Path(env))
        install = getattr(getattr(self.config, "energyplus", None), "installation_path", "")
        if install:
            candidates.append(Path(install) / "ReferenceDocs")
        work = getattr(getattr(self.config, "paths", None), "work_dir", "")
        if work:
            candidates.append(Path(work) / "reference_docs")
        return candidates

    def _load(self) -> None:
        with self._lock:
            if self._loaded:
                return
            for directory in self.candidate_directories():
                if (directory / "manifest.json").is_file() and (directory / "sections.json").is_file():
                    break
            else:
                raise ReferenceDocsError(
                    "EnergyPlus reference documentation index not found in "
                    + ", ".join(str(p) for p in self.candidate_directories())
                    + ". " + BUILD_HINT
                )
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            if manifest.get("schema_version") != SCHEMA_VERSION:
                raise ReferenceDocsError(
                    f"{directory} has index schema {manifest.get('schema_version')}, "
                    f"expected {SCHEMA_VERSION}. " + BUILD_HINT
                )
            sections = json.loads((directory / "sections.json").read_text(encoding="utf-8"))

            end = [len(sections)] * len(sections)
            stack: List[int] = []
            for index, section in enumerate(sections):
                while stack and (
                    sections[stack[-1]]["doc"] != section["doc"]
                    or sections[stack[-1]]["level"] >= section["level"]
                ):
                    end[stack.pop()] = index
                stack.append(index)
                self._by_label.setdefault(section["label"].lower(), index)
                for name in section["object_types"]:
                    self._by_object.setdefault(name.upper(), []).append(index)
                    self._object_names.setdefault(name.upper(), name)
            for name, ids in self._by_object.items():
                # Prefer the Input Output Reference object section.
                ids.sort(key=lambda i: (sections[i]["doc"] != DOCUMENTS[0], sections[i]["kind"] != "object", i))

            self._directory = directory
            self._manifest = manifest
            self._sections = sections
            self._end = end
            self._loaded = True
            logger.info("Loaded %d reference documentation sections from %s", len(sections), directory)

    def _installed_idd_version(self) -> Optional[str]:
        if self._idd_version is None:
            path = getattr(getattr(self.config, "energyplus", None), "idd_path", "")
            version = ""
            if path and os.path.isfile(path):
                with open(path, encoding="latin-1") as handle:
                    for _ in range(5):
                        line = handle.readline()
                        if line.startswith("!IDD_Version"):
                            version = line.split(None, 1)[1].strip() if len(line.split()) > 1 else ""
                            break
            self._idd_version = version
        return self._idd_version or None

    def _idd_classes(self) -> Dict[str, Dict[str, Any]]:
        if self._idd is None:
            path = getattr(getattr(self.config, "energyplus", None), "idd_path", "")
            if not path or not os.path.isfile(path):
                raise ReferenceDocsError(f"Installed EnergyPlus IDD not found: {path or '(unset)'}")
            self._idd = parse_idd(path)
        return self._idd

    def _version_note(self) -> Optional[str]:
        installed = self._installed_idd_version()
        documented = self._manifest.get("energyplus_version")
        if installed and documented and installed != documented:
            return (
                f"Documentation is for EnergyPlus {documented} but the installed engine is "
                f"{installed}; field names and behavior may differ."
            )
        return None

    # -- helpers --------------------------------------------------------------
    def _path(self, index: int) -> List[str]:
        titles = []
        parent = self._sections[index]["parent"]
        while parent is not None:
            titles.append(self._sections[parent]["title"])
            parent = self._sections[parent]["parent"]
        return list(reversed(titles))

    def _summary(self, index: int) -> Dict[str, Any]:
        s = self._sections[index]
        item = {
            "section_id": index,
            "doc": s["doc"],
            "title": s["title"],
            "kind": s["kind"],
            "path": " > ".join(self._path(index)[-3:]),
            "chars": sum(len(self._sections[i]["text"]) for i in range(index, self._end[index])),
        }
        if s["object_types"]:
            item["object_types"] = s["object_types"]
        if s.get("field"):
            item["field"] = s["field"]
        if s.get("owner") is not None:
            item["object"] = self._sections[s["owner"]]["title"]
        return item

    def _with_note(self, result: Dict[str, Any]) -> Dict[str, Any]:
        note = self._version_note()
        if note:
            result["version_warning"] = note
        return result

    def _object_section(self, object_type: str) -> int:
        ids = self._by_object.get(object_type.strip().upper())
        if not ids:
            close = difflib.get_close_matches(
                object_type.upper(), list(self._object_names), n=5, cutoff=0.6
            )
            raise ReferenceDocsError(
                f"No documentation section for object type {object_type!r}"
                + (f"; did you mean {[self._object_names[c] for c in close]}?" if close else "")
            )
        return ids[0]

    # -- actions --------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        try:
            self._load()
        except ReferenceDocsError as exc:
            return {
                "available": False,
                "error": str(exc),
                "searched": [str(p) for p in self.candidate_directories()],
            }
        manifest = self._manifest
        return self._with_note({
            "available": True,
            "directory": str(self._directory),
            "energyplus_version": manifest.get("energyplus_version"),
            "installed_idd_version": self._installed_idd_version(),
            "source": manifest.get("source"),
            "built_at": manifest.get("built_at"),
            "documents": manifest.get("documents"),
            "documented_object_types": manifest.get("documented_object_types"),
            "idd_object_types": manifest.get("idd_object_types"),
            "license": str(self._directory / manifest.get("license", "LICENSE.txt")),
        })

    def search(
        self,
        query: str,
        doc: Optional[str] = None,
        kind: Optional[str] = None,
        limit: int = 10,
    ) -> Dict[str, Any]:
        self._load()
        query = (query or "").strip()
        if not query:
            raise ReferenceDocsError("query is required for search")
        if doc and doc not in DOCUMENTS:
            raise ReferenceDocsError(f"doc must be one of {list(DOCUMENTS)}")
        if kind and kind not in KINDS:
            raise ReferenceDocsError(f"kind must be one of {list(KINDS)}")
        limit = max(1, min(limit, MAX_SEARCH_LIMIT))
        if self._lower is None:
            self._lower = [(s["title"].lower(), s["text"].lower()) for s in self._sections]

        phrase = query.lower()
        terms = [t for t in re.findall(r"[\w:.\-]+", phrase) if t not in _STOP_WORDS] or [phrase]
        required = max(1, -(-len(terms) * 2 // 3))
        scored = []
        for index, (title, text) in enumerate(self._lower):
            section = self._sections[index]
            if doc and section["doc"] != doc:
                continue
            if kind and section["kind"] != kind:
                continue
            score = 0
            hits = 0
            for term in terms:
                if term in title:
                    hits += 1
                    score += 10
                else:
                    count = text.count(term)
                    if count:
                        hits += 1
                        score += min(count, 5)
            # Natural-language queries rarely match every word; require most.
            if hits < required:
                continue
            if title == phrase:
                score += 100
            elif phrase in title:
                score += 40
            elif phrase in text:
                score += 8
            if section["kind"] == "object":
                score += 5
            scored.append((-hits, -score, index))
        scored.sort()
        results = []
        for negative_hits, negative, index in scored[:limit]:
            item = self._summary(index)
            item["score"] = -negative
            item["matched_terms"] = f"{-negative_hits}/{len(terms)}"
            text = self._sections[index]["text"]
            position = self._lower[index][1].find(terms[0]) if terms else -1
            start = max(0, position - _SNIPPET_CHARS // 3) if position >= 0 else 0
            item["snippet"] = " ".join(text[start:start + _SNIPPET_CHARS].split())
            results.append(item)
        return self._with_note({"query": query, "total_matches": len(scored), "results": results})

    def get_section(
        self,
        section_id: Optional[int] = None,
        label: Optional[str] = None,
        object_type: Optional[str] = None,
        include_subsections: bool = True,
        max_chars: Optional[int] = None,
        offset: int = 0,
    ) -> Dict[str, Any]:
        self._load()
        if sum(x is not None and x != "" for x in (section_id, label, object_type)) != 1:
            raise ReferenceDocsError("give exactly one of section_id, label, or object_type")
        if section_id is not None:
            if not 0 <= section_id < len(self._sections):
                raise ReferenceDocsError(f"section_id must be 0..{len(self._sections) - 1}")
            index = section_id
        elif label:
            key = label.strip().lstrip("#").lower()
            if key not in self._by_label:
                raise ReferenceDocsError(f"No section with label {label!r}")
            index = self._by_label[key]
        else:
            index = self._object_section(object_type or "")

        base = self._sections[index]["level"]
        stop = self._end[index] if include_subsections else index + 1
        parts = []
        for i in range(index, stop):
            s = self._sections[i]
            heading = "#" * min(6, s["level"] - base + 1) + " " + s["title"]
            parts.append(heading + ("\n\n" + s["text"] if s["text"] else ""))
        content = "\n\n".join(parts)

        limit = max(500, min(max_chars or DEFAULT_MAX_CHARS, MAX_CHARS))
        offset = max(0, offset)
        chunk = content[offset:offset + limit]
        result = self._summary(index)
        result.update({
            "label": self._sections[index]["label"],
            "source": self._sections[index]["source"],
            "full_path": " > ".join(self._path(index) + [self._sections[index]["title"]]),
            "offset": offset,
            "content": chunk,
            "total_chars": len(content),
            "truncated": offset + len(chunk) < len(content),
        })
        if result["truncated"]:
            result["next_offset"] = offset + len(chunk)
        outline = [
            {"section_id": i, "title": self._sections[i]["title"], "kind": self._sections[i]["kind"],
             "level": self._sections[i]["level"] - base}
            for i in range(index + 1, self._end[index])
            if self._sections[i]["level"] - base <= 2
        ]
        if outline and (result["truncated"] or not include_subsections):
            result["outline"] = outline[:_OUTLINE_LIMIT]
        result["links"] = (
            "Links like [Name](#label) refer to other sections; fetch them with get_section(label=...)."
        )
        return self._with_note(result)

    def get_field(self, object_type: str, field: str) -> Dict[str, Any]:
        self._load()
        if not object_type or not field:
            raise ReferenceDocsError("object_type and field are required for get_field")

        result: Dict[str, Any] = {"object_type": object_type, "field": field}
        idd_error = None
        idd_field = None
        try:
            idd_class = self._idd_classes().get(object_type.strip().upper())
        except ReferenceDocsError as exc:
            idd_class, idd_error = None, str(exc)
        idd_names: List[str] = []
        if idd_class is not None:
            result["object_type"] = idd_class["name"]
            idd_names = [f.get("field") or f["id"] for f in idd_class["fields"]]
            position = _match_name(field, idd_names)
            if position is not None:
                idd_field = idd_class["fields"][position]
                result["field"] = idd_names[position]
                result["idd"] = _idd_field_view(idd_field)
                props = idd_class["properties"]
                extensible = [k for k in props if k.startswith("extensible")]
                if extensible:
                    result["idd"]["object_extensible"] = extensible[0]
        elif idd_error is None:
            idd_error = f"{object_type!r} is not an object type in the installed IDD"

        doc_field = None
        doc_names: List[str] = []
        object_index = None
        try:
            object_index = self._object_section(result["object_type"])
        except ReferenceDocsError as exc:
            result["documentation_error"] = str(exc)
        if object_index is not None:
            fields = [
                i for i in range(object_index + 1, self._end[object_index])
                if self._sections[i]["kind"] == "field" and self._sections[i]["owner"] == object_index
            ]
            doc_names = [self._sections[i]["field"] for i in fields]
            position = _match_name(result["field"], doc_names)
            if position is None and result["field"] != field:
                position = _match_name(field, doc_names)
            result["object_section_id"] = object_index
            if position is not None:
                index = fields[position]
                doc_field = self._sections[index]
                result["documentation"] = {
                    "section_id": index,
                    "title": doc_field["title"],
                    "label": doc_field["label"],
                    "text": doc_field["text"],
                }

        if idd_class is None and object_index is None:
            raise ReferenceDocsError(result["documentation_error"])
        if idd_field is None and doc_field is None:
            names = idd_names or doc_names
            close = difflib.get_close_matches(field, names, n=5, cutoff=0.4)
            raise ReferenceDocsError(
                f"No field {field!r} on {result['object_type']!r}"
                + (f"; did you mean {close}?" if close else "")
                + (f" Fields: {names[:60]}" if names and not close else "")
                + (f" ({idd_error})" if idd_error else "")
            )
        if idd_error:
            result["idd_error"] = idd_error
        if idd_field is None:
            result["idd_note"] = "Field documented but not matched in the installed IDD."
        if doc_field is None and object_index is not None:
            result["documentation_note"] = (
                "No dedicated paragraph for this field; read the object section with "
                f"get_section(section_id={object_index})."
            )
        return self._with_note(result)


_INSTANCES: Dict[int, ReferenceDocs] = {}
_INSTANCES_LOCK = threading.Lock()


def get_reference_docs(config: Any) -> ReferenceDocs:
    """Return the process-wide index for ``config`` (one per server)."""
    with _INSTANCES_LOCK:
        docs = _INSTANCES.get(id(config))
        if docs is None:
            docs = ReferenceDocs(config)
            _INSTANCES[id(config)] = docs
        return docs
