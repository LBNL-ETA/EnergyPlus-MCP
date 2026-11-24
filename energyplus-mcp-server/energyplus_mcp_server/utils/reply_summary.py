"""Summaries of large inspection replies.

Inspection actions list every schedule, surface or control target. On real
models those listings run to hundreds of kilobytes (395 KB for a schedule
inspection of one OpenStudio-generated house), and every reply is read by an
agent. With ``detail="summary"`` (the default) these functions replace bulky
per-object listings with counts, and keep what an agent needs to act:

- Problems are kept: skipped, ambiguous, invalid and missing items.
- A list is never truncated. A list is either complete or replaced by counts,
  because a partial list of edit targets could lead to a partial edit.
- Lists an edit refers to (schedule consumers) are kept complete while they
  have at most ``KEEP_LIMIT`` items.
- Every summary says what it omitted and how to get it
  (``detail="full"``, or a narrower scope).
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Callable, Dict, Iterable, List, Optional

KEEP_LIMIT = 100


def summarize_text(text: str, summarize: Callable[[Dict[str, Any]], Dict[str, Any]], indent: Optional[int] = 2) -> str:
    """Summarize a JSON object reply; return anything else (such as an error message) unchanged."""
    try:
        result = json.loads(text)
    except (TypeError, ValueError):
        return text
    if not isinstance(result, dict) or "error" in result:
        return text
    return json.dumps(summarize(result), indent=indent)


def _counts(items: Iterable[Any], field: str) -> Dict[str, int]:
    counter = Counter(
        str(item.get(field)) for item in items if isinstance(item, dict) and item.get(field) not in (None, "")
    )
    return dict(sorted(counter.items(), key=lambda pair: (-pair[1], pair[0])))


def _mark(result: Dict[str, Any], omitted: Dict[str, int], hint: str) -> Dict[str, Any]:
    result["detail"] = "summary"
    if omitted:
        result["omitted"] = omitted
        result["full_detail"] = hint
    return result


def _keep_or_count(
    container: Dict[str, Any], key: str, by: List[str], omitted: Dict[str, int], prefix: str = ""
) -> None:
    """Keep a list when it is short; otherwise replace it with counts (never truncate)."""
    items = container.get(key)
    if not isinstance(items, list) or len(items) <= KEEP_LIMIT:
        return
    container[f"{key}_count"] = len(items)
    for field in by:
        container[f"{key}_by_{field}"] = _counts(items, field)
    del container[key]
    omitted[f"{prefix}{key}"] = len(items)


def _drop(
    container: Dict[str, Any], key: str, by: List[str], omitted: Dict[str, int], prefix: str = ""
) -> Optional[list]:
    """Replace a list with its count and breakdowns."""
    items = container.get(key)
    if not isinstance(items, list):
        return None
    container[f"{key}_count"] = len(items)
    for field in by:
        container[f"{key}_by_{field}"] = _counts(items, field)
    del container[key]
    if items:
        omitted[f"{prefix}{key}"] = len(items)
    return items


def schedule_inspection(result: Dict[str, Any]) -> Dict[str, Any]:
    """schedule_manager(action="inspect") summary."""
    omitted: Dict[str, int] = {}
    schedules = _drop(result, "schedules", ["object_type", "kind"], omitted)
    if schedules is not None:
        invalid = [
            {key: schedule.get(key) for key in ("schedule_id", "schedule_name", "object_type") if key in schedule}
            for schedule in schedules
            if isinstance(schedule, dict) and schedule.get("valid") is False
        ]
        result["invalid_schedules"] = invalid
    _keep_or_count(result, "consumers", ["role", "object_type"], omitted)
    for key in ("skipped", "ambiguous"):
        _keep_or_count(result, key, ["reason"], omitted)
    hint = (
        "Per-schedule entries (segments, references) were omitted. Use scope=<role> "
        "(lighting, electric_equipment, hvac_availability, thermostat_setpoint, occupancy) "
        "for a smaller list with its consumers, or detail='full' for everything."
    )
    return _mark(result, omitted, hint)


def geometry_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    """geometry_manager(action="extract_and_summary") summary."""
    omitted: Dict[str, int] = {}
    geometry = result.get("geometry")
    if isinstance(geometry, dict):
        for key in ("surfaces", "subsurfaces", "shading_surfaces"):
            items = geometry.pop(key, None)
            if isinstance(items, list) and items:
                omitted[f"geometry.{key}"] = len(items)
    hint = "Per-surface vertices were omitted. Use detail='full' for every surface and its vertices."
    return _mark(result, omitted, hint)


def envelope_inspection(result: Dict[str, Any]) -> Dict[str, Any]:
    """envelope_manager(action="inspect", focus="all") summary."""
    omitted: Dict[str, int] = {}
    surfaces = _drop(result, "surfaces", ["surface_type", "outside_boundary_condition", "construction_name"], omitted)
    if surfaces is not None:
        result["surfaces_by_zone_name"] = _counts(surfaces, "zone_name")
    hint = (
        "The per-surface list was omitted. Use focus='surfaces' or detail='full' for every "
        "surface with its construction and layers."
    )
    return _mark(result, omitted, hint)


def hvac_controls(result: Dict[str, Any]) -> Dict[str, Any]:
    """hvac_manager(action="inspect_controls") summary."""
    omitted: Dict[str, int] = {}
    for section, value in result.items():
        if not isinstance(value, dict) or "targets" not in value:
            continue
        _drop(value, "targets", ["role", "object_type"], omitted, prefix=f"{section}.")
        _drop(value, "shared_object_relationships", [], omitted, prefix=f"{section}.")
        for key in ("skipped", "ambiguous"):
            _keep_or_count(value, key, ["reason"], omitted, prefix=f"{section}.")
    hint = (
        "Per-target listings were omitted; coverage problems (skipped, ambiguous) are kept. "
        "Use detail='full' for every target and shared relationship."
    )
    return _mark(result, omitted, hint)
