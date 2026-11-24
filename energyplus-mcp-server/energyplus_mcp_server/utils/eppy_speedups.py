"""Speed up eppy's IDF parsing without changing its results.

When eppy reads a model it converts the IDD label of every field of every
object (``"Zone or ZoneList or Space or SpaceList Name"``) into an attribute
name (``"Zone_or_ZoneList_or_Space_or_SpaceList_Name"``) with
``bunchhelpers.makefieldname`` and ``bunchhelpers.onlylegalchar``, walking the
label one character at a time. It does this again for every object on every
parse: about three million calls for one capability check on a five-zone model.

Both functions depend only on the label text (an IDD schema string, never a
model value), so their results are memoized for the life of the process. The
cache holds one entry per distinct IDD label, is shared by every model and
user, and never needs invalidating: the same label always maps to the same
name, and a model edit changes values, not labels.
"""

from __future__ import annotations

import functools
from typing import Callable

# Distinct IDD labels across all object types, including numbered extensible
# fields ("Vertex 120 Xcoordinate"), are in the tens of thousands.
CACHE_SIZE = 65536

_applied = False


def apply() -> None:
    """Memoize eppy's field-name helpers (idempotent)."""
    global _applied
    if _applied:
        return
    import eppy.bunch_subclass as bunch_subclass
    import eppy.bunchhelpers as bunchhelpers

    original_onlylegalchar: Callable[[str], str] = bunchhelpers.onlylegalchar
    original_makefieldname: Callable[[str], str] = bunchhelpers.makefieldname

    onlylegalchar = functools.lru_cache(maxsize=CACHE_SIZE)(original_onlylegalchar)
    makefieldname = functools.lru_cache(maxsize=CACHE_SIZE)(original_makefieldname)
    onlylegalchar.__wrapped_original__ = original_onlylegalchar  # type: ignore[attr-defined]
    makefieldname.__wrapped_original__ = original_makefieldname  # type: ignore[attr-defined]

    # idfreader, iddgaps and ext_field_functions look these up on the module at
    # call time; bunch_subclass imported makefieldname by name, so it keeps its
    # own reference that must be replaced too.
    bunchhelpers.onlylegalchar = onlylegalchar
    bunchhelpers.makefieldname = makefieldname
    bunch_subclass.makefieldname = makefieldname
    _applied = True
