import asyncio
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from energyplus_mcp_server.utils import example_library as example_module
from energyplus_mcp_server.utils.example_library import (
    ExampleLibrary,
    ExampleLibraryError,
    count_object_types,
    extract_header,
    read_example_catalog,
    read_idd_classes,
    scan_objects,
    summarize_header,
)

REAL_IDD = os.getenv("EPLUS_IDD_PATH", "/app/software/EnergyPlusV26-1-0/Energy+.idd")
REAL_INSTALL = os.path.dirname(REAL_IDD)
needs_idd = pytest.mark.skipif(not os.path.isfile(REAL_IDD), reason="EnergyPlus IDD not installed")
needs_examples = pytest.mark.skipif(
    not os.path.isfile(os.path.join(REAL_INSTALL, "ExampleFiles", "ExampleFiles-ObjectsLink.html")),
    reason="EnergyPlus ExampleFiles not installed",
)

FAKE_IDD = """!IDD_Version 99.1.0
\\group Simulation Parameters
Version,
  A1 ; \\field Version Identifier
Zone,
  A1 , \\field Name
  N1 ; \\field X Origin
 Lights,
  A1 , \\field Name
  A2 , \\field Zone or ZoneList or Space or SpaceList Name
  A3 ; \\field Schedule Name
Schedule:Compact,
  A1 , \\field Name
  A2 ; \\field Schedule Type Limits Name
HVACTemplate:Thermostat,
  A1 ; \\field Name
Coil:Cooling:DX:SingleSpeed,
  A1 ; \\field Name
Coil:Cooling:DX:TwoSpeed,
  A1 ; \\field Name
"""

SMALL = """! Small.idf
! Basic file description:  One zone box with lights.
!
! Highlights:              Shows a Lights object and its schedule.

Version,99.1;
Zone, Office, 0;
Lights, Office Lights, Office, LIGHTS-SCH, LightingLevel, 500;
Schedule:Compact, LIGHTS-SCH, Fraction, Through: 12/31, For: AllDays, Until: 24:00, 1.0;
"""

BIG = """! Big.idf
! Basic file description:  Two zones with lights and a DX coil.

Version,99.1;
Zone, East, 0;
Zone, West, 0;
Lights, East Lights, East, LIGHTS-SCH, LightingLevel, 400;
Lights, West Lights, West, LIGHTS-SCH, LightingLevel, 400;
Schedule:Compact, LIGHTS-SCH, Fraction, Through: 12/31, For: AllDays, Until: 24:00, 1.0;
Coil:Cooling:DX:SingleSpeed, Main Coil;
"""

TEMPLATE = """! Templated.idf
! Basic file description:  Uses HVAC templates.

Version,99.1;
Zone, Core, 0;
Lights, Core Lights, Core, LIGHTS-SCH, LightingLevel, 100;
HVACTemplate:Thermostat, Constant;
"""

CATALOG = """<html><body><table>
<tr><th>Filename</th><th>Location</th><th>NumZones</th><th>Daylighting?</th><th>Chillers?</th><th>Description</th></tr>
<tr><td>Big.idf</td><td>Chicago</td><td>2</td><td>True</td><td>False</td><td>Catalog description of the big model.</td></tr>
<tr><td>Small.idf</td><td>Denver</td><td>1</td><td>False</td><td>False</td><td> </td></tr>
</table></body></html>
"""


def make_install(tmp_path: Path, idd_text: str = FAKE_IDD, idd_path: str | None = None) -> SimpleNamespace:
    install = tmp_path / "EnergyPlus"
    examples = install / "ExampleFiles"
    (examples / "Basics").mkdir(parents=True)
    (install / "DataSets").mkdir()
    (examples / "Small.idf").write_text(SMALL)
    (examples / "Big.idf").write_text(BIG)
    (examples / "Basics" / "Templated.idf").write_text(TEMPLATE)
    (examples / "ExampleFiles.html").write_text(CATALOG)
    (install / "DataSets" / "Schedules.idf").write_text(
        "SCHEDULE:COMPACT, Office Lighting, Fraction, Through: 12/31, For: AllDays, Until: 24:00, 0.9;\n"
    )
    if idd_path is None:
        (install / "Energy+.idd").write_text(idd_text)
        idd_path = str(install / "Energy+.idd")
    return SimpleNamespace(
        energyplus=SimpleNamespace(
            idd_path=idd_path,
            installation_path=str(install),
            example_files_path=str(examples),
        )
    )


def test_scan_objects_handles_comments_shared_lines_macros_and_tail():
    text = (
        "! header\n"
        "##include other.idf\n"
        "Zone,\n  A, ! the name\n  0;  Lights, L1, A, S; ! two objects on one line\n"
        "Schedule:Compact, S, Fraction, Through: 12/31, For: AllDays, Until: 24:00, 1;\n"
        "Zone, unterminated"
    )
    objects = scan_objects(text)

    assert [(obj.class_name, obj.name) for obj in objects] == [
        ("Zone", "A"),
        ("Lights", "L1"),
        ("Schedule:Compact", "S"),
    ]
    assert [obj.line for obj in objects] == [3, 5, 6]
    assert objects[2].fields[2:4] == ("Through: 12/31", "For: AllDays")


def test_count_object_types_reports_upper_keys_and_version():
    counts, version = count_object_types(SMALL + "lights, extra, Office, LIGHTS-SCH;\n")

    assert counts == {"VERSION": 1, "ZONE": 1, "LIGHTS": 2, "SCHEDULE:COMPACT": 1}
    assert version == "99.1"


def test_header_summary_prefers_description_and_highlights():
    header = extract_header(SMALL)

    assert header.startswith("Small.idf")
    assert "!-" not in header
    assert summarize_header(header) == "One zone box with lights. Shows a Lights object and its schedule."


def test_idd_reader_accepts_indented_class_lines(tmp_path):
    path = tmp_path / "Energy+.idd"
    path.write_text(FAKE_IDD)

    version, classes = read_idd_classes(str(path))

    assert version == "99.1.0"
    assert classes["LIGHTS"] == "Lights"
    assert "A1" not in classes and len(classes) == 7


def test_catalog_parser_reads_features_and_descriptions(tmp_path):
    path = tmp_path / "ExampleFiles.html"
    path.write_text(CATALOG)

    catalog = read_example_catalog(str(path))

    assert catalog["Big.idf"]["features"] == ["Daylighting"]
    assert catalog["Big.idf"]["zones"] == 2
    assert catalog["Small.idf"]["description"] == ""
    assert read_example_catalog(str(tmp_path / "missing.html")) == {}


def test_inventory_indexes_both_libraries_with_flags_and_catalog(tmp_path):
    library = ExampleLibrary(make_install(tmp_path), cache_dir="")
    status = library.status()

    assert status["energyplus_version"] == "99.1.0"
    assert status["libraries"]["examples"]["idf_files"] == 3
    assert status["libraries"]["datasets"]["idf_files"] == 1
    described = library.describe("Templated.idf")
    assert described["file"] == "Basics/Templated.idf"
    assert described["flags"] == ["needs_preprocessor"]
    assert "warning" in described
    big = library.describe("Big.idf")
    assert big["catalog"]["description"] == "Catalog description of the big model."
    assert big["objects"]["Lights"] == 2 and big["zones"] == 2
    # Dataset class names are canonicalized through the IDD.
    assert library.describe("Schedules.idf", "datasets")["objects"] == {"Schedule:Compact": 1}


def test_search_requires_all_types_and_ranks_small_native_files_first(tmp_path):
    library = ExampleLibrary(make_install(tmp_path), cache_dir="")

    lights = library.search(object_types=["lights"], library="examples")["results"]["examples"]
    assert [row["file"] for row in lights["files"]] == ["Small.idf", "Big.idf", "Basics/Templated.idf"]
    assert lights["files"][2]["flags"] == ["needs_preprocessor"]

    both = library.search(object_types=["Lights", "Coil:Cooling:DX:SingleSpeed"])["results"]
    assert [row["file"] for row in both["examples"]["files"]] == ["Big.idf"]
    assert both["examples"]["files"][0]["matched_objects"] == {
        "Lights": 2,
        "Coil:Cooling:DX:SingleSpeed": 1,
    }
    assert both["datasets"]["total_matches"] == 0

    assert library.search(object_types=["Lights"], max_zones=1, library="examples")["results"]["examples"][
        "total_matches"
    ] == 2
    by_feature = library.search(features=["daylighting"], library="examples")["results"]["examples"]
    assert [row["file"] for row in by_feature["files"]] == ["Big.idf"]
    by_keyword = library.search(keywords=["catalog description"], library="examples")["results"]["examples"]
    assert [row["file"] for row in by_keyword["files"]] == ["Big.idf"]


def test_search_resolves_wildcards_and_suggests_unknown_types(tmp_path):
    library = ExampleLibrary(make_install(tmp_path), cache_dir="")

    result = library.search(object_types=["Coil:Cooling:DX:*"], library="examples")
    assert result["object_types"] == ["Coil:Cooling:DX:SingleSpeed", "Coil:Cooling:DX:TwoSpeed"]
    assert result["results"]["examples"]["total_matches"] == 0

    with pytest.raises(ExampleLibraryError, match=r"Close matches: \['Lights'\]"):
        library.search(object_types=["Lites"])
    with pytest.raises(ExampleLibraryError, match="at least one"):
        library.search()

    types = library.object_types("coil:cooling", library="examples")
    assert types["object_types"] == [
        {"object_type": "Coil:Cooling:DX:SingleSpeed", "examples_files": 1},
        {"object_type": "Coil:Cooling:DX:TwoSpeed", "examples_files": 0},
    ]


def test_locate_only_serves_inventoried_files(tmp_path):
    library = ExampleLibrary(make_install(tmp_path), cache_dir="")

    with pytest.raises(ExampleLibraryError, match="not in the EnergyPlus library"):
        library.describe("../../Energy+.idd")
    with pytest.raises(ExampleLibraryError, match="not in the EnergyPlus library"):
        library.describe("/etc/passwd")
    with pytest.raises(ExampleLibraryError, match="library must be one of"):
        library.describe("Small.idf", "weather")


def test_inventory_rebuilds_when_installed_files_change(tmp_path):
    config = make_install(tmp_path)
    library = ExampleLibrary(config, cache_dir="")
    assert library.search(object_types=["Coil:Cooling:DX:TwoSpeed"], library="examples")["results"][
        "examples"
    ]["total_matches"] == 0

    small = Path(config.energyplus.example_files_path) / "Small.idf"
    small.write_text(SMALL + "Coil:Cooling:DX:TwoSpeed, New Coil;\n")

    result = library.search(object_types=["Coil:Cooling:DX:TwoSpeed"], library="examples")
    assert [row["file"] for row in result["results"]["examples"]["files"]] == ["Small.idf"]


def test_persistent_cache_is_reused_by_a_new_process(tmp_path, monkeypatch):
    config = make_install(tmp_path)
    cache = tmp_path / "cache"
    first = ExampleLibrary(config, cache_dir=str(cache))
    first.inventory()
    assert len(list(cache.glob("example-inventory-*.json"))) == 1

    second = ExampleLibrary(config, cache_dir=str(cache))
    monkeypatch.setattr(second, "_build", lambda fingerprint: pytest.fail("cache was not reused"))
    assert second.status()["libraries"]["examples"]["idf_files"] == 3


def test_cache_directory_comes_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv(example_module.CACHE_ENV, str(tmp_path / "env-cache"))

    assert ExampleLibrary(make_install(tmp_path)).cache_dir == str(tmp_path / "env-cache")


@needs_idd
def test_get_objects_returns_idd_field_names_and_references(tmp_path):
    library = ExampleLibrary(make_install(tmp_path, idd_path=REAL_IDD), cache_dir="")

    result = library.get_objects("Big.idf", "lights", names=["west lights"], output_format="both")

    assert result["total_in_file"] == 2 and result["returned"] == 1
    [lights] = result["objects"]
    assert lights["fields"]["Zone_or_ZoneList_or_Space_or_SpaceList_Name"] == "West"
    assert lights["fields"]["Lighting_Level"] == 400
    assert "!- Schedule Name" in lights["idf_text"]
    assert {(ref["field"], tuple(ref["types"]), ref["found"]) for ref in lights["references"]} == {
        ("Zone_or_ZoneList_or_Space_or_SpaceList_Name", ("Zone",), True),
        ("Schedule_Name", ("Schedule:Compact",), True),
    }
    assert [(obj["type"], obj["name"]) for obj in result["referenced_objects"]] == [
        ("Zone", "West"),
        ("Schedule:Compact", "LIGHTS-SCH"),
    ]


@needs_idd
def test_get_objects_limits_filters_and_explains_misses(tmp_path):
    library = ExampleLibrary(make_install(tmp_path, idd_path=REAL_IDD), cache_dir="")

    limited = library.get_objects("Big.idf", "Lights", limit=1, include_references=False)
    assert limited["returned"] == 1 and limited["more_available"] == 1
    assert limited["referenced_objects"] == [] and "references" not in limited["objects"][0]

    missing = library.get_objects("Small.idf", "Coil:Cooling:DX:SingleSpeed")
    assert missing["returned"] == 0 and "action='search'" in missing["hint"]

    with pytest.raises(ExampleLibraryError, match="exactly one"):
        library.get_objects("Big.idf", "Coil:Cooling:DX:*")
    with pytest.raises(ExampleLibraryError, match="format"):
        library.get_objects("Big.idf", "Lights", output_format="xml")


@needs_examples
def test_real_inventory_is_consistent_with_energyplus_objects_link():
    config = SimpleNamespace(
        energyplus=SimpleNamespace(
            idd_path=REAL_IDD,
            installation_path=REAL_INSTALL,
            example_files_path=os.path.join(REAL_INSTALL, "ExampleFiles"),
        )
    )
    library = ExampleLibrary(config, cache_dir="")
    inventory = library.inventory()
    classes = {name.upper() for name in inventory["classes"]}

    top_level: dict[str, int] = {}
    for relative, entry in inventory["libraries"]["examples"]["files"].items():
        assert set(name.upper() for name in entry["objects"]) <= classes, relative
        if "/" not in relative:
            for name in entry["objects"]:
                top_level[name.upper()] = top_level.get(name.upper(), 0) + 1

    # ObjectsLink is generated from the upstream test-file set, which includes
    # files that are not shipped, so shipped counts may be lower, never higher.
    link = Path(REAL_INSTALL, "ExampleFiles", "ExampleFiles-ObjectsLink.html").read_text(encoding="latin-1")
    rows = re.findall(r"<tr>\s*<td>(.*?)</td>\s*<td>(\d+)</td>", link, re.S)
    assert rows
    assert [name for name, count in rows if top_level.get(name.upper(), 0) > int(count)] == []
    assert inventory["libraries"]["datasets"]["files"]


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self, *args, **kwargs):
        def decorate(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorate


def test_tool_wrapper_returns_json_results_and_errors(tmp_path, monkeypatch):
    from energyplus_mcp_server.tools import example_library as tool_module

    library = ExampleLibrary(make_install(tmp_path), cache_dir="")
    monkeypatch.setattr(tool_module, "get_example_library", lambda config: library)
    mcp = FakeMCP()
    tool_module.register(mcp, object(), object())
    call = mcp.tools["example_library"]

    found = json.loads(asyncio.run(call(action="search", object_types=["Lights"], library="examples")))
    assert found["results"]["examples"]["total_matches"] == 3
    capabilities = json.loads(asyncio.run(call(action="capabilities")))
    assert capabilities["skill"] == "learn-from-examples"
    error = json.loads(asyncio.run(call(action="get_objects", file="Small.idf")))
    assert error["error"] == "object_type is required for get_objects"
