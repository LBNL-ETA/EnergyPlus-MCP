#!/usr/bin/env python3
"""Build a section index of the EnergyPlus reference documentation.

EnergyPlus keeps its manuals as LaTeX in the source repository; the PDFs that
ship with a release are compiled from the same files.  This script converts
the documents an agent needs while modelling into Markdown with pandoc and
splits them at every heading, so the server can return one object, field, or
topic instead of a whole manual.

Output (``--out``):

* ``manifest.json`` - EnergyPlus version, source tag/commit, pandoc version,
  per-document section counts.
* ``sections.json`` - one entry per heading, in book order: document, level,
  title, LaTeX label, parent, kind (object/field/output/section), the IDD
  object types the heading documents, and the Markdown body up to the next
  heading.
* ``LICENSE.txt`` - the EnergyPlus license that covers the documentation.

The script needs only the Python standard library, ``git`` (for ``--tag``),
and ``pandoc``.  It runs in a Docker build stage, pinned to the same release
tag as the installed engine, and can also be run locally:

    python build_reference_docs.py --tag v26.1.0 --expected-commit 6f2e40d102 --out DIR
    python build_reference_docs.py --source /path/to/EnergyPlus --version 26.1.0 --out DIR
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

SCHEMA_VERSION = 1
REPOSITORY = "https://github.com/NREL/EnergyPlus.git"
DOCUMENTS = {
    "input-output-reference": "Input Output Reference",
    "engineering-reference": "Engineering Reference",
    "output-details-and-examples": "Output Details and Examples",
    "plant-application-guide": "Plant Application Guide",
}
SPARSE_PATTERNS = ("/doc/**/*.tex", "/idd/Energy+.idd.in", "/LICENSE.txt")

# Pandoc Markdown keeps heading labels ({#label}) and $math$; the disabled
# extensions would otherwise add grid tables, div/span fences, and attribute
# syntax that only add noise for a reader.
PANDOC_FORMAT = (
    "markdown-grid_tables-multiline_tables-simple_tables-fenced_divs-native_divs"
    "-bracketed_spans-native_spans-raw_attribute-link_attributes-smart"
    "-fenced_code_attributes"
)
PANDOC_ARGS = ("-f", "latex", "-t", PANDOC_FORMAT, "--wrap=none", "--markdown-headings=atx")

_INPUT = re.compile(r"\\(?:input|include)\{([^}]+)\}")
_CHAPTER = re.compile(r"^[^%\n]*\\chapter\*?\{", re.M)
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*(?:\{#([^\s}]+)[^}]*\})?[ \t]*$")
_FENCE = re.compile(r"^(```|~~~)")
_ESCAPE = re.compile(r"\\([^A-Za-z0-9\s])")
_FIELD = re.compile(r"^Field(?:\s+Set)?\s*:\s*(.+)$", re.I)
_IDD_CLASS = re.compile(r"^([A-Za-z][A-Za-z0-9:_\-]*(?: [A-Za-z0-9:_\-]+)*)\s*[,;]\s*(?:!.*)?$")
_IDD_FIELD = re.compile(r"^[AN]\d+\s*[,;]")
_SPLIT_TITLE = re.compile(r",|\band\b|\(|\)")


class BuildError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Source discovery
# ---------------------------------------------------------------------------

def ordered_pieces(doc_root: Path, main_file: Path) -> List[Tuple[str, str]]:
    """Return (source path, LaTeX text) pieces in book order.

    ``\\input`` lines are resolved recursively relative to ``doc_root`` (the
    convention of the EnergyPlus manuals) and replaced by the included file's
    pieces, so each converted piece holds only its own text.
    """
    pieces: List[Tuple[str, str]] = []
    seen: set = set()

    def visit(path: Path) -> None:
        resolved = path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        text = path.read_text(encoding="utf-8", errors="replace")
        # The main file wraps the body in a document environment after a
        # preamble (\title, \hypersetup, ...); only the body is content.
        begin = text.find("\\begin{document}")
        if begin >= 0:
            end = text.find("\\end{document}", begin)
            text = text[begin + len("\\begin{document}"):end if end >= 0 else None]
        rel = path.relative_to(doc_root).as_posix()
        cursor = 0
        for match in _INPUT.finditer(text):
            # Ignore \input inside a comment line.
            line_start = text.rfind("\n", 0, match.start()) + 1
            if "%" in text[line_start:match.start()]:
                continue
            chunk = text[cursor:match.start()]
            if chunk.strip():
                pieces.append((rel, chunk))
            cursor = match.end()
            target = doc_root / match.group(1)
            if target.suffix != ".tex":
                target = target.with_name(target.name + ".tex")
            try:
                target.resolve().relative_to(doc_root.resolve())
            except ValueError:
                continue  # ../header and other shared preamble files
            if target.is_file():
                visit(target)
        tail = text[cursor:]
        if tail.strip():
            pieces.append((rel, tail))

    visit(main_file)
    return pieces


def read_idd_classes(idd_path: Path) -> Dict[str, str]:
    """Return {UPPER class name: canonical name} from an IDD (or Energy+.idd.in)."""
    classes: Dict[str, str] = {}
    for line in idd_path.read_text(encoding="latin-1").splitlines():
        stripped = line.strip()
        if not stripped or stripped[0] in "!\\" or _IDD_FIELD.match(stripped):
            continue
        match = _IDD_CLASS.match(stripped)
        if match:
            name = match.group(1).strip()
            classes.setdefault(name.upper(), name)
    return classes


# ---------------------------------------------------------------------------
# Conversion and splitting
# ---------------------------------------------------------------------------

def pandoc_version(pandoc: str) -> str:
    out = subprocess.run([pandoc, "--version"], capture_output=True, text=True, check=True)
    return out.stdout.splitlines()[0].strip()


def convert(pandoc: str, latex: str, source: str) -> str:
    result = subprocess.run(
        [pandoc, *PANDOC_ARGS], input=latex, capture_output=True, text=True, encoding="utf-8"
    )
    if result.returncode != 0:
        raise BuildError(f"pandoc failed on {source}: {result.stderr.strip()[:500]}")
    return result.stdout


def auto_identifier(title: str) -> str:
    """Pandoc's auto identifier, used when a heading's label equals it."""
    text = re.sub(r"[^\w\s.\-]", "", title.lower(), flags=re.UNICODE)
    text = re.sub(r"\s+", "-", text.strip())
    return re.sub(r"^[^a-z]+", "", text)


def split_markdown(markdown: str, has_chapter: bool) -> List[Dict]:
    """Split one converted piece at its headings.

    Returns entries with ``level`` normalized to LaTeX depth (chapter=1,
    section=2, subsection=3, subsubsection=4, paragraph=5).  Pandoc numbers
    levels from the highest division present in the piece, so a piece without
    a chapter is shifted down by one.  Text before the first heading is
    returned as an entry with ``level`` None (a continuation of the previous
    piece's last section).
    """
    shift = 0 if has_chapter else 1
    entries: List[Dict] = []
    current: Dict = {"level": None, "title": None, "label": None, "lines": []}
    in_fence = False
    # LaTeX \- (discretionary hyphen) becomes an invisible soft hyphen that
    # breaks title matching, e.g. "Output:\-Meter".
    markdown = markdown.replace("­", "")
    for line in markdown.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        match = None if in_fence else _HEADING.match(line)
        if match:
            entries.append(current)
            title = _ESCAPE.sub(r"\1", match.group(2)).strip()
            current = {
                "level": len(match.group(1)) + shift,
                "title": title,
                "label": match.group(3) or auto_identifier(title),
                "lines": [],
            }
        else:
            current["lines"].append(line)
    entries.append(current)
    for entry in entries:
        entry["text"] = "\n".join(entry.pop("lines")).strip()
    return [e for e in entries if e["level"] is not None or e["text"]]


def object_types_for(title: str, classes: Dict[str, str]) -> List[str]:
    candidates = [title] + [part.strip() for part in _SPLIT_TITLE.split(title)]
    found: List[str] = []
    for candidate in candidates:
        name = classes.get(candidate.upper())
        if name and name not in found:
            found.append(name)
    return found


def index_document(
    key: str,
    pieces: Iterable[Tuple[str, Dict]],
    classes: Dict[str, str],
    sections: List[Dict],
) -> int:
    """Append one document's sections to ``sections``; return how many."""
    start = len(sections)
    stack: List[Dict] = []  # open ancestors
    for source, entry in pieces:
        if entry["level"] is None:
            if len(sections) > start:
                previous = sections[-1]
                previous["text"] = (previous["text"] + "\n\n" + entry["text"]).strip()
            continue
        level = entry["level"]
        while stack and stack[-1]["level"] >= level:
            stack.pop()
        parent = stack[-1] if stack else None
        title = entry["title"]
        objects = object_types_for(title, classes) if key == "input-output-reference" else []
        field_match = _FIELD.match(title)
        owner = next((s for s in reversed(stack) if s["object_types"]), None)
        if objects:
            kind = "object"
        elif field_match and owner is not None:
            kind = "field"
        elif owner is not None and any(s["title"].lower() == "outputs" for s in stack):
            kind = "output"
        else:
            kind = "section"
        section = {
            "id": len(sections),
            "doc": key,
            "level": level,
            "title": title,
            "label": entry["label"],
            "parent": parent["id"] if parent else None,
            "kind": kind,
            "object_types": objects,
            "field": field_match.group(1).strip() if kind == "field" else None,
            "owner": owner["id"] if owner is not None and kind in ("field", "output") else None,
            "source": f"doc/{key}/{source}",
            "text": entry["text"],
        }
        sections.append(section)
        stack.append(section)
    return len(sections) - start


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build(source_root: Path, out_dir: Path, version: str, tag: Optional[str], commit: Optional[str],
          pandoc: str = "pandoc", jobs: Optional[int] = None) -> Dict:
    if shutil.which(pandoc) is None and not Path(pandoc).is_file():
        raise BuildError("pandoc is required to build the reference documentation")
    idd = source_root / "idd" / "Energy+.idd.in"
    if not idd.is_file():
        idd = source_root / "idd" / "Energy+.idd"
    if not idd.is_file():
        raise BuildError(f"IDD not found under {source_root / 'idd'}")
    classes = read_idd_classes(idd)

    sections: List[Dict] = []
    documents: Dict[str, Dict] = {}
    with ThreadPoolExecutor(max_workers=jobs or max(1, (os.cpu_count() or 2))) as pool:
        for key, title in DOCUMENTS.items():
            doc_root = source_root / "doc" / key
            main = doc_root / f"{key}.tex"
            if not main.is_file():
                raise BuildError(f"missing {main}")
            pieces = ordered_pieces(doc_root, main)
            converted = pool.map(lambda p: convert(pandoc, p[1], p[0]), pieces)
            split = (
                (source, entry)
                for (source, latex), markdown in zip(pieces, converted)
                for entry in split_markdown(markdown, bool(_CHAPTER.search(latex)))
            )
            count = index_document(key, split, classes, sections)
            documents[key] = {
                "title": title,
                "sections": count,
                "chars": sum(len(s["text"]) for s in sections[-count:]) if count else 0,
            }

    documented = {name.upper() for s in sections for name in s["object_types"]}
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "energyplus_version": version,
        "source": {"repository": REPOSITORY.removesuffix(".git"), "tag": tag, "commit": commit},
        "pandoc": pandoc_version(pandoc),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "documents": documents,
        "idd_object_types": len(classes),
        "documented_object_types": len(documented),
        "license": "LICENSE.txt",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "sections.json").write_text(
        json.dumps(sections, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    license_file = source_root / "LICENSE.txt"
    if license_file.is_file():
        shutil.copyfile(license_file, out_dir / "LICENSE.txt")
    return manifest


def sparse_clone(tag: str, destination: Path, repository: str = REPOSITORY) -> str:
    def git(*args: str, cwd: Optional[Path] = None) -> str:
        return subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
        ).stdout.strip()

    git("clone", "--quiet", "--depth", "1", "--filter=blob:none", "--no-checkout",
        "--branch", tag, repository, str(destination))
    git("sparse-checkout", "set", "--no-cone", *SPARSE_PATTERNS, cwd=destination)
    git("checkout", "--quiet", cwd=destination)
    return git("rev-parse", "HEAD", cwd=destination)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    origin = parser.add_mutually_exclusive_group(required=True)
    origin.add_argument("--tag", help="EnergyPlus release tag to fetch, e.g. v26.1.0")
    origin.add_argument("--source", type=Path, help="existing EnergyPlus source checkout")
    parser.add_argument("--version", help="EnergyPlus version (default: derived from --tag)")
    parser.add_argument("--expected-commit", help="abort unless the tag's commit starts with this")
    parser.add_argument("--repository", default=REPOSITORY)
    parser.add_argument("--pandoc", default="pandoc")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    version = args.version or (args.tag or "").lstrip("v")
    if not version:
        parser.error("--version is required with --source")
    try:
        if args.tag:
            with tempfile.TemporaryDirectory() as tmp:
                checkout = Path(tmp) / "EnergyPlus"
                commit = sparse_clone(args.tag, checkout, args.repository)
                if args.expected_commit and not commit.startswith(args.expected_commit):
                    raise BuildError(
                        f"{args.tag} resolved to {commit}, expected {args.expected_commit}"
                    )
                manifest = build(checkout, args.out, version, args.tag, commit, args.pandoc)
        else:
            commit = None
            if (args.source / ".git").exists():
                commit = subprocess.run(
                    ["git", "rev-parse", "HEAD"], cwd=args.source,
                    capture_output=True, text=True,
                ).stdout.strip() or None
            manifest = build(args.source, args.out, version, None, commit, args.pandoc)
    except (BuildError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or ""
        print(f"error: {exc} {detail}".strip(), file=sys.stderr)
        return 1
    summary = ", ".join(f"{k}: {v['sections']}" for k, v in manifest["documents"].items())
    print(
        f"EnergyPlus {manifest['energyplus_version']} reference docs -> {args.out} "
        f"({summary}; {manifest['documented_object_types']}/{manifest['idd_object_types']} "
        "IDD object types documented)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
