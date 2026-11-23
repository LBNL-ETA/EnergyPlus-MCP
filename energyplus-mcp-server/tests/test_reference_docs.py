import asyncio
import importlib.util
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from energyplus_mcp_server.utils.reference_docs import (
    DOCS_ENV,
    SCHEMA_VERSION,
    ReferenceDocs,
    ReferenceDocsError,
    parse_idd,
)

BUILDER_PATH = Path(__file__).resolve().parents[2] / ".devcontainer" / "build_reference_docs.py"
_spec = importlib.util.spec_from_file_location("build_reference_docs", BUILDER_PATH)
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)

FAKE_IDD = """!IDD_Version 26.1.0
\\group Fans
Fan:SystemModel,
       \\memo Versatile fan model
       \\extensible:2 repeat the last two fields
  A1 , \\field Name
       \\required-field
  N1 , \\field Design Maximum Air Flow Rate
       \\units m3/s
       \\minimum> 0
       \\autosizable
  A2 , \\field Speed Control Method
       \\key Continuous
       \\key Discrete
       \\default Discrete
       \\note Continuous needs a power curve.
  N2 , \\field Speed 1 Flow Fraction
       \\begin-extensible
  N3 ; \\field Speed 1 Electric Power Fraction
\\group Output Reporting
Output:Meter,
  A1 ; \\field Key Name
"""

LONG = "Fan text. " * 120  # > 500 chars so paging can be exercised

MARKDOWN = f"""Continuation of the previous piece.

# Group -- Fans

Intro to fans.

## Fan:SystemModel

{LONG}

### Inputs {{#inputs-fansysmodel}}

#### Field: Name {{#field-name-fansysmodel}}

A unique name. See [Fan:OnOff](#fanonoff).

#### Field: Design Maximum Air Flow Rate {{#field-flow}}

The design flow rate, in m$^3$/s. This field can be autosized.

#### Field: Speed \\<\\#\\> Flow Fraction {{#field-speed-flow}}

Flow fraction at each speed.

```
# not a heading inside a fence
```

### Outputs {{#outputs-fansysmodel}}

#### Fan Electricity Rate \\[W\\] {{#fan-rate}}

Electric power.

## Output:\u00adMeter and Output:\u00adMeter:\u00adMeterFileOnly {{#outputmeter}}

Meters.

## Fan:OnOff

On/off fan.
"""

CLASSES = {
    "FAN:SYSTEMMODEL": "Fan:SystemModel",
    "FAN:ONOFF": "Fan:OnOff",
    "OUTPUT:METER": "Output:Meter",
    "OUTPUT:METER:METERFILEONLY": "Output:Meter:MeterFileOnly",
}


def build_index(directory: Path, version: str = "26.1.0") -> list:
    # Two pieces: a chapter, then a group file whose leading text continues it.
    pieces = [("src/overview.tex", e) for e in builder.split_markdown(
        "Title page text is dropped.\n\n# Input-Output Reference\n\nOverview.", has_chapter=True)]
    pieces += [("src/overview/group-fans.tex", e) for e in builder.split_markdown(MARKDOWN, has_chapter=False)]
    sections: list = []
    builder.index_document("input-output-reference", pieces, CLASSES, sections)
    err = builder.split_markdown("# eplusout.err\n\nWarnings and severe errors.\n", has_chapter=False)
    builder.index_document("output-details-and-examples", (("src/eplusout-err.tex", e) for e in err), CLASSES, sections)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "sections.json").write_text(json.dumps(sections))
    (directory / "manifest.json").write_text(json.dumps({
        "schema_version": SCHEMA_VERSION, "energyplus_version": version,
        "source": {"tag": f"v{version}"}, "documents": {}, "license": "LICENSE.txt",
    }))
    return sections


@pytest.fixture
def docs(tmp_path, monkeypatch):
    index = tmp_path / "ReferenceDocs"
    build_index(index)
    idd = tmp_path / "Energy+.idd"
    idd.write_text(FAKE_IDD)
    monkeypatch.delenv(DOCS_ENV, raising=False)
    config = SimpleNamespace(
        energyplus=SimpleNamespace(installation_path=str(tmp_path), idd_path=str(idd)),
        paths=SimpleNamespace(work_dir=str(tmp_path / "work")),
    )
    return ReferenceDocs(config)


# --- builder ----------------------------------------------------------------

def test_split_markdown_normalizes_levels_labels_and_fences():
    entries = builder.split_markdown(MARKDOWN, has_chapter=False)
    assert entries[0]["level"] is None and entries[0]["text"].startswith("Continuation")
    headings = [(e["level"], e["title"], e["label"]) for e in entries[1:]]
    assert headings[0] == (2, "Group -- Fans", "group----fans")
    assert headings[1] == (3, "Fan:SystemModel", "fansystemmodel")  # pandoc auto identifier
    assert (5, "Field: Speed <#> Flow Fraction", "field-speed-flow") in headings
    assert (3, "Output:Meter and Output:Meter:MeterFileOnly", "outputmeter") in headings
    assert not any("not a heading" in title for _, title, _ in headings)
    # A piece that contains \chapter keeps pandoc's levels.
    assert builder.split_markdown("# Chapter\n\ntext", has_chapter=True)[0]["level"] == 1


def test_index_document_assigns_kinds_owners_and_object_types(tmp_path):
    sections = build_index(tmp_path)
    by_title = {s["title"]: s for s in sections}
    fan = by_title["Fan:SystemModel"]
    assert fan["kind"] == "object" and fan["object_types"] == ["Fan:SystemModel"]
    field = by_title["Field: Design Maximum Air Flow Rate"]
    assert field["kind"] == "field" and field["owner"] == fan["id"]
    assert field["field"] == "Design Maximum Air Flow Rate"
    assert by_title["Fan Electricity Rate [W]"]["kind"] == "output"
    assert by_title["Inputs"]["kind"] == "section" and by_title["Inputs"]["parent"] == fan["id"]
    meter = by_title["Output:Meter and Output:Meter:MeterFileOnly"]
    assert meter["object_types"] == ["Output:Meter", "Output:Meter:MeterFileOnly"]
    # Text before a document's first heading (title page) is dropped; text
    # before the first heading of a later piece continues the previous section.
    assert sections[0]["title"] == "Input-Output Reference"
    assert sections[0]["text"] == "Overview.\n\nContinuation of the previous piece."
    assert by_title["Group -- Fans"]["parent"] == sections[0]["id"]


def test_ordered_pieces_follows_inputs_in_book_order(tmp_path):
    root = tmp_path / "doc" / "guide"
    (root / "src").mkdir(parents=True)
    (root / "guide.tex").write_text(
        "\\input{../header}\n\\title{Guide}\n\\begin{document}\n\\input{src/a}\n\\end{document}\n"
    )
    (root / "src" / "a.tex").write_text(
        "\\chapter{A}\nbefore\n\\input{src/b}\n% \\input{src/c}\nafter\n"
    )
    (root / "src" / "b.tex").write_text("\\section{B}\nbody\n")
    (root / "src" / "c.tex").write_text("\\section{C}\nskipped\n")
    pieces = builder.ordered_pieces(root, root / "guide.tex")
    assert [source for source, _ in pieces] == ["src/a.tex", "src/b.tex", "src/a.tex"]
    assert "\\title" not in "".join(text for _, text in pieces)
    assert "skipped" not in "".join(text for _, text in pieces)


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_build_end_to_end_with_pandoc(tmp_path, monkeypatch):
    source = tmp_path / "EnergyPlus"
    (source / "idd").mkdir(parents=True)
    (source / "idd" / "Energy+.idd.in").write_text(FAKE_IDD)
    (source / "LICENSE.txt").write_text("license")
    for key in builder.DOCUMENTS:
        doc_root = source / "doc" / key
        (doc_root / "src").mkdir(parents=True)
        (doc_root / f"{key}.tex").write_text("\\begin{document}\n\\input{src/body}\n\\end{document}\n")
        (doc_root / "src" / "body.tex").write_text(
            "\\section{Group -- Fans}\\label{group-fans}\n"
            "\\subsection{Fan:SystemModel}\\label{fansystemmodel}\nA fan.\n"
            "\\subsubsection{Inputs}\\label{inputs-fan}\n"
            "\\paragraph{Field: Design Maximum Air Flow Rate}\\label{field-flow}\n"
            "The design flow, in m\\(^{3}\\)/s.\n"
        )
    out = tmp_path / "out"
    manifest = builder.build(source, out, "26.1.0", "v26.1.0", "abc")
    assert manifest["documented_object_types"] == 1
    assert (out / "LICENSE.txt").read_text() == "license"

    idd = tmp_path / "Energy+.idd"
    idd.write_text(FAKE_IDD)
    monkeypatch.setenv(DOCS_ENV, str(out))
    config = SimpleNamespace(
        energyplus=SimpleNamespace(installation_path="/nonexistent", idd_path=str(idd)),
        paths=SimpleNamespace(work_dir="/nonexistent"),
    )
    field = ReferenceDocs(config).get_field("Fan:SystemModel", "Design Maximum Air Flow Rate")
    assert "design flow" in field["documentation"]["text"]
    assert field["idd"]["units"] == "m3/s"


# --- runtime ----------------------------------------------------------------

def test_parse_idd_reads_fields_and_annotations(tmp_path):
    idd = tmp_path / "Energy+.idd"
    idd.write_text(FAKE_IDD)
    classes = parse_idd(str(idd))
    fan = classes["FAN:SYSTEMMODEL"]
    assert fan["properties"]["memo"] == ["Versatile fan model"]
    names = [f["field"] for f in fan["fields"]]
    assert names[:3] == ["Name", "Design Maximum Air Flow Rate", "Speed Control Method"]
    assert fan["fields"][1]["minimum>"] == "0" and fan["fields"][1]["autosizable"] is True
    assert fan["fields"][2]["key"] == ["Continuous", "Discrete"]
    assert classes["OUTPUT:METER"]["fields"][0]["field"] == "Key Name"


def test_status_reports_index_and_version_mismatch(tmp_path, monkeypatch):
    build_index(tmp_path / "docs", version="25.2.0")
    idd = tmp_path / "Energy+.idd"
    idd.write_text(FAKE_IDD)
    monkeypatch.setenv(DOCS_ENV, str(tmp_path / "docs"))
    config = SimpleNamespace(
        energyplus=SimpleNamespace(installation_path="/nonexistent", idd_path=str(idd)),
        paths=SimpleNamespace(work_dir="/nonexistent"),
    )
    status = ReferenceDocs(config).status()
    assert status["available"] and status["energyplus_version"] == "25.2.0"
    assert "26.1.0" in status["version_warning"]


def test_missing_index_is_reported_not_raised(tmp_path, monkeypatch):
    monkeypatch.delenv(DOCS_ENV, raising=False)
    config = SimpleNamespace(
        energyplus=SimpleNamespace(installation_path=str(tmp_path), idd_path=""),
        paths=SimpleNamespace(work_dir=str(tmp_path / "work")),
    )
    status = ReferenceDocs(config).status()
    assert status["available"] is False and "build_reference_docs.py" in status["error"]
    with pytest.raises(ReferenceDocsError):
        ReferenceDocs(config).search("fan")


def test_get_field_combines_idd_and_documentation(docs):
    result = docs.get_field("fan:systemmodel", "Design_Maximum_Air_Flow_Rate")
    assert result["object_type"] == "Fan:SystemModel"
    assert result["field"] == "Design Maximum Air Flow Rate"
    assert result["idd"]["units"] == "m3/s" and result["idd"]["autosizable"] is True
    assert result["idd"]["object_extensible"].startswith("extensible:2")
    assert "autosized" in result["documentation"]["text"]
    assert "version_warning" not in result


def test_get_field_matches_repeated_fields_and_choices(docs):
    speed = docs.get_field("Fan:SystemModel", "Speed 3 Flow Fraction")
    assert speed["documentation"]["title"] == "Field: Speed <#> Flow Fraction"
    method = docs.get_field("Fan:SystemModel", "speed control method")
    assert method["idd"]["choices"] == ["Continuous", "Discrete"]
    assert method["idd"]["default"] == "Discrete"
    assert "documentation_note" in method  # no paragraph in the fixture


def test_get_field_suggests_close_names(docs):
    with pytest.raises(ReferenceDocsError, match="Design Maximum Air Flow Rate"):
        docs.get_field("Fan:SystemModel", "Desgin Max Air Flow")
    with pytest.raises(ReferenceDocsError, match="Fan:SystemModel"):
        docs.get_field("Fan:SystemModle", "Name")


def test_get_section_by_object_label_and_id_with_paging(docs):
    full = docs.get_section(object_type="Fan:SystemModel", max_chars=500)
    assert full["content"].startswith("# Fan:SystemModel")
    assert full["truncated"] and full["next_offset"] == 500
    assert any(item["title"] == "Inputs" for item in full["outline"])
    rest = docs.get_section(object_type="Fan:SystemModel", offset=full["next_offset"], max_chars=40000)
    assert not rest["truncated"] and "#### Field: Name" not in rest["content"][:1]
    assert "## Inputs" in full["content"] + rest["content"]
    assert "Fan:OnOff" not in (full["content"] + rest["content"]).split("[Fan:OnOff]")[-1]

    linked = docs.get_section(label="#fanonoff")
    assert linked["title"] == "Fan:OnOff" and linked["kind"] == "object"
    own = docs.get_section(section_id=full["section_id"], include_subsections=False)
    assert "## Inputs" not in own["content"] and own["outline"]
    with pytest.raises(ReferenceDocsError):
        docs.get_section(label="fanonoff", object_type="Fan:OnOff")


def test_search_ranks_titles_and_filters(docs):
    result = docs.search("Fan:SystemModel", kind="object")
    assert result["results"][0]["title"] == "Fan:SystemModel"
    assert all(item["kind"] == "object" for item in result["results"])
    fields = docs.search("the design flow rate", kind="field")
    assert fields["results"][0]["object"] == "Fan:SystemModel"
    err = docs.search("severe errors", doc="output-details-and-examples")
    assert [item["title"] for item in err["results"]] == ["eplusout.err"]
    with pytest.raises(ReferenceDocsError):
        docs.search("fan", doc="getting-started")


def test_tool_returns_json(docs, monkeypatch):
    from energyplus_mcp_server.tools import reference_docs as tool_module

    monkeypatch.setattr(tool_module, "get_reference_docs", lambda config: docs)
    tools = {}

    class FakeMCP:
        def tool(self, *args, **kwargs):
            def decorator(fn):
                tools[fn.__name__] = fn
                return fn
            return decorator

    tool_module.register(FakeMCP(), object(), object())
    tool = tools["reference_docs"]
    caps = json.loads(asyncio.run(tool(action="capabilities")))
    assert "get_field" in caps["actions"]
    field = json.loads(asyncio.run(tool(action="get_field", object_type="Fan:SystemModel", field="Name")))
    assert field["idd"]["required"] is True
    error = json.loads(asyncio.run(tool(action="get_section")))
    assert "error" in error
