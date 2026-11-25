"""IDD rules the generic object editor checks before it writes a model.

Uses the IDD's own declarations rather than guessing from names:

- ``\\key``: the allowed values of a choice field (compared case-insensitively,
  as EnergyPlus does);
- ``\\object-list``: the reference classes a field may name (a Lights
  ``Schedule Name`` takes ``ScheduleNames``);
- ``\\reference``: the reference classes an object's field provides (every
  ``Schedule:*`` Name provides ``ScheduleNames``).

So a node that happens to share a schedule's name is never mistaken for a use
of that schedule.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple


def _fold(value: Any) -> str:
    return str(value).strip().casefold()


def _blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


class IDDIndex:
    """Reference classes, defined names, and field roles for one parsed model."""

    def __init__(self, idf: Any) -> None:
        self.idf = idf
        self._class_fields: Dict[str, List[dict]] = {}
        for upper, info in zip(idf.model.dtls, idf.idd_info):
            self._class_fields[upper.upper()] = info or []
        self._names: Optional[Dict[str, Set[str]]] = None

    def field_idd(self, object_type: str, index: int) -> dict:
        fields = self._class_fields.get(object_type.upper(), [])
        if 0 <= index < len(fields) and isinstance(fields[index], dict):
            return fields[index]
        return {}

    def _defined_names(self) -> Dict[str, Set[str]]:
        """{reference class (folded): names defined for it (folded)}."""
        if self._names is None:
            names: Dict[str, Set[str]] = {}
            for object_type, objects in self.idf.idfobjects.items():
                fields = self._class_fields.get(object_type.upper(), [])
                providing = [
                    (index, field.get("reference") or [])
                    for index, field in enumerate(fields)
                    if isinstance(field, dict) and field.get("reference")
                ]
                if not providing:
                    continue
                for obj in objects:
                    values = obj.fieldvalues
                    for index, classes in providing:
                        if index < len(values) and not _blank(values[index]):
                            for reference_class in classes:
                                names.setdefault(_fold(reference_class), set()).add(_fold(values[index]))
            self._names = names
        return self._names

    def refresh(self) -> None:
        self._names = None

    def value_issue(self, obj: Any, field: str, value: Any) -> Tuple[Optional[str], Optional[str]]:
        """(error, reference_problem) for setting ``field`` to ``value`` on ``obj``.

        ``error`` is an invalid choice; ``reference_problem`` names an object
        that does not exist (callers may accept it with force).
        """
        if _blank(value):
            return None, None
        try:
            index = obj.fieldnames.index(field)
        except ValueError:
            return None, None
        idd = self.field_idd(obj.key, index)
        keys = idd.get("key") or []
        if keys and _fold(value) not in {_fold(key) for key in keys}:
            return f"'{value}' is not an allowed value for {field}; allowed: {', '.join(keys)}", None
        classes = idd.get("object-list") or []
        if classes:
            defined = self._defined_names()
            if not any(_fold(value) in defined.get(_fold(c), set()) for c in classes):
                return None, (
                    f"{field} names '{value}', but no object of the kind it needs "
                    f"({', '.join(classes)}) has that name in this model"
                )
        return None, None

    def users_of(self, obj: Any, exclude: Optional[Set[int]] = None) -> List[Dict[str, str]]:
        """Objects with a field that refers to ``obj`` (by its IDD reference classes)."""
        provided: List[Tuple[Set[str], str]] = []
        fields = self._class_fields.get(obj.key.upper(), [])
        for index, field in enumerate(fields):
            if isinstance(field, dict) and field.get("reference") and index < len(obj.fieldvalues):
                value = obj.fieldvalues[index]
                if not _blank(value):
                    provided.append(({_fold(c) for c in field["reference"]}, _fold(value)))
        if not provided:
            return []
        exclude = exclude or set()
        users: List[Dict[str, str]] = []
        for object_type, objects in self.idf.idfobjects.items():
            type_fields = self._class_fields.get(object_type.upper(), [])
            listing = [
                (index, {_fold(c) for c in field.get("object-list") or []})
                for index, field in enumerate(type_fields)
                if isinstance(field, dict) and field.get("object-list")
            ]
            if not listing:
                continue
            for other in objects:
                if other is obj or id(other) in exclude:
                    continue
                values = other.fieldvalues
                for index, classes in listing:
                    if index >= len(values) or _blank(values[index]):
                        continue
                    if any(classes & reference_classes and _fold(values[index]) == name
                           for reference_classes, name in provided):
                        users.append({
                            "object_type": other.key,
                            "name": str(getattr(other, "Name", "") or "") if "Name" in other.fieldnames else "",
                            "field": other.fieldnames[index],
                        })
                        break
        return users
