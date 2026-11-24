"""The memoized eppy field-name helpers must behave exactly like eppy's own."""

import os
import re

import pytest

import energyplus_mcp_server  # noqa: F401  (applies the speedups on import)
from energyplus_mcp_server.utils import eppy_speedups

REAL_IDD = os.getenv("EPLUS_IDD_PATH", "/app/software/EnergyPlusV26-1-0/Energy+.idd")

TRICKY_LABELS = [
    "Name",
    "Zone or ZoneList or Space or SpaceList Name",
    "Vertex 1 X-coordinate",
    "Vertex 120 Zcoordinate",
    "Watts per Zone Floor Area",
    "U-Factor",
    "Solar Heat Gain Coefficient",
    "Field 1",
    "Fraction of Autosized Design Cooling Supply Air Flow Rate",
    "Coefficient1 Constant",
    "Hour 24 Value",
    "Until: 24:00",
    "  leading and trailing  ",
    "Ünïcödé — and symbols #1 (W/m2) [C]",
    "",
]


def _helpers():
    import eppy.bunch_subclass as bunch_subclass
    import eppy.bunchhelpers as bunchhelpers

    return bunchhelpers, bunch_subclass


def test_helpers_are_memoized_everywhere_eppy_uses_them():
    bunchhelpers, bunch_subclass = _helpers()

    assert hasattr(bunchhelpers.makefieldname, "cache_info")
    assert hasattr(bunchhelpers.onlylegalchar, "cache_info")
    # bunch_subclass imported makefieldname by name and needs the same function.
    assert bunch_subclass.makefieldname is bunchhelpers.makefieldname


def test_apply_is_idempotent():
    bunchhelpers, _ = _helpers()
    before = bunchhelpers.makefieldname

    eppy_speedups.apply()

    assert bunchhelpers.makefieldname is before


@pytest.mark.parametrize("label", TRICKY_LABELS)
def test_memoized_helpers_match_eppy(label):
    bunchhelpers, _ = _helpers()
    original_make = bunchhelpers.makefieldname.__wrapped_original__
    original_only = bunchhelpers.onlylegalchar.__wrapped_original__

    assert bunchhelpers.makefieldname(label) == original_make(label)
    assert bunchhelpers.onlylegalchar(label) == original_only(label)
    # A second (cached) call returns the same value.
    assert bunchhelpers.makefieldname(label) == original_make(label)


@pytest.mark.skipif(not os.path.isfile(REAL_IDD), reason="EnergyPlus IDD not installed")
def test_every_idd_field_label_converts_like_eppy():
    bunchhelpers, _ = _helpers()
    original_make = bunchhelpers.makefieldname.__wrapped_original__
    with open(REAL_IDD, encoding="latin-1") as handle:
        labels = set(re.findall(r"\\field\s+(.+?)\s*$", handle.read(), re.M))

    assert len(labels) > 1000
    mismatches = [label for label in labels if bunchhelpers.makefieldname(label) != original_make(label)]
    assert mismatches == []
    assert bunchhelpers.makefieldname.cache_info().maxsize >= len(labels)
