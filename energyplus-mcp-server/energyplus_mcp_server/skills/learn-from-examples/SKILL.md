---
name: learn-from-examples
description: >-
  Learn how to add or edit an unfamiliar EnergyPlus object by reading the
  example models and DataSets installed with EnergyPlus, then adapt it to the
  target IDF. Use before adding an object type you have not modelled with this
  server, when no domain manager operation covers the change, or when you need
  realistic component data (materials, glazing, equipment curves, schedules).
---

# Learn from EnergyPlus examples

EnergyPlus ships about 760 runnable example models (`ExampleFiles/`) and a
library of component data (`DataSets/`). The `example_library` tool searches
both and returns objects with the exact field names `idf_modification`
accepts. Treat examples as evidence of *structure*; values still need a source.

## Use this skill when

- You need an object type you have not added before (a coil, setpoint
  manager, daylighting control, EMS program, output object, ...).
- No domain manager operation (`envelope_manager`, `internal_load_manager`,
  `schedule_manager`, `hvac_manager`, `service_water_manager`,
  `outputs_manager`) performs the change. Prefer those operations when they
  exist: they preserve shared objects, bounds, and before/after checks.
- You need realistic inputs such as a window construction, a material, or a
  chiller performance curve set. See `datasets-guide.md` in this skill.

## Procedure

1. **Know the target model.** Run `model_preflight(action="info")` on it and
   record its `Version`. Compare with `example_library(action="status")`.
   If versions differ, field names and order may differ: verify each field
   against the target (step 7 reports valid names on error) or ask whether to
   run a copy-only `model_upgrade`. Never upgrade implicitly.
2. **Find the exact object type name.**
   `example_library(action="object_types", pattern="Coil:Cooling:DX*")`.
   Types with zero example files have no reference; say so instead of guessing.
3. **Find a small, relevant example.**
   `example_library(action="search", object_types=[...], keywords=[...], max_zones=...)`.
   - List the companion types you expect (for example the coil *and* its
     parent `AirLoopHVAC:UnitarySystem`) so the file shows the whole pattern.
   - Results rank smallest first. Skip files flagged `needs_preprocessor`
     (HVACTemplate objects are expanded at run time, so the native objects
     are missing). Note `external_dependencies` (Schedule:File, Python plugins).
4. **Confirm it demonstrates what you need.**
   `example_library(action="describe", file=...)` returns the author's header
   and object counts. Read the header before trusting the example.
5. **Fetch the objects and their dependencies.**
   `example_library(action="get_objects", file=..., object_type=..., reference_depth=1)`.
   - `references` lists which fields point at other objects;
     `referenced_objects` contains the schedules, curves, constructions,
     and zones found in the file. Raise `reference_depth` (max 3) for chains
     such as construction → material.
   - Node names are not objects. For HVAC, also fetch the objects that list
     the same nodes (the parent system, `Branch`, `NodeList`,
     `ZoneHVAC:EquipmentList`, splitters/mixers) and inspect the target's
     topology with `hvac_manager(action="topology")` before changing loops.
6. **Plan the adaptation before writing.** Build a mapping for every
   reference: example name → target name (zones, schedules, nodes, curves,
   constructions). Reuse equivalent objects already in the target (inspect
   them with the domain managers) instead of duplicating them, and check that
   no new name collides with an existing object. Choose values in this order:
   user or project data → the target model's existing values → `DataSets` →
   example values, which you must report as assumptions. Keep calculation
   methods consistent with the populated field (for example
   `Design_Level_Calculation_Method` must match the level field you set).
   Check a field's meaning, units, limits, and choices with
   `reference_docs(action="get_field", object_type=..., field=...)`.
7. **Apply on one working copy.** Copy the model first
   (`file_utils(action="copy", ...)`), then call
   `idf_modification(action="add", idf_path=<copy>, output_path=<copy>, object_type=..., fields={...})`
   once per object, using absolute paths. After each call check `errors`:
   the file is saved even when a field fails, leaving a partial object, so fix
   it with `action="modify"` or remove it with `action="delete"` before moving on.
8. **Check the result.** `model_preflight(action="validate")` is shallow: it
   checks required objects and construction layers, not every reference, so
   compare each new object's reference fields against objects that exist in
   the target. The decisive check is an EnergyPlus run; a design-day run
   (`simulation_manager(action="run", annual=False, design_day=True)`) is
   quick, but only simulate when the user has asked for it or approved it.
9. **Report provenance.** List the objects added, the source example file
   and object names for each, every assumed value, and anything unresolved.

## Pitfalls

- Library files are read-only references. Never pass an `ExampleFiles` or
  `DataSets` path as an edit target or output path.
- Do not copy location, design day, run period, simulation control, or
  weather-specific objects from an example unless asked; they describe the
  example's site, not the target's.
- Example names such as `ALWAYS ON`, `SPACE1-1`, or `Fraction` limits may
  exist in the target with different contents; compare before reusing a name.
- One HVAC component rarely stands alone. Adding a coil or fan usually also
  changes its parent system, branch lists, and node connections.
- `autosize` in an example relies on the example's sizing objects
  (`Sizing:Zone`, `Sizing:System`, `Sizing:Plant`, design days). Confirm the
  target has them, or supply fixed values.
- `get_objects` returns at most 20 objects and 40 referenced objects per call;
  narrow with `names` or `name_contains` rather than raising limits.
