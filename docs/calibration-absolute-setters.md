# Native absolute setters and explicit calibration bounds

The existing `calibration_manager` now distinguishes inspection, percentage
changes, and absolute targets. It does not silently clip percentage edits.
Calibration-MCP decides the allowed range; EnergyPlus-MCP performs the edit.

## Workflow

1. Check model-specific `calibration_manager(action="capabilities", idf_path=...)`.
   Percentage and absolute coverage are separate. Inspect `absolute_set` for
   the desired parameter; partial coverage is not enabled.
2. Inspect the incoming model with `action="inspect", parameter=...`.
   The response contains canonical values, units, stable target IDs and the
   input model's SHA-256. It does not expose raw IDF objects.
3. For a direct absolute target, request Calibration-MCP's
   `get_measure_recipe(..., operation="absolute_set")`. Execute `action="set"`
   with `value`, an explicit input and a different output path. Optional
   `target_ids` restricts the edit to known targets. Pass the inspected hash
   as `expected_model_sha256` to refuse stale input.
4. For bounds, call Calibration-MCP's `get_bound_repair_recipe` with the
   project, parameter and inspection. It uses the methodology's bound table
   or the existing state's override. Without `percentage_change`, it repairs
   only out-of-range targets. With it, it projects a percentage trial and
   clips the proposed canonical values explicitly before any model is saved.
5. Execute the returned atomic `set` recipe. `assignments` maps target IDs to
   absolute values and replaces the scalar `value`/`target_ids` arguments.
   Conflicting shared-field assignments fail. The manager verifies achieved
   canonical quantities before saving and reports each underlying field edit.
6. Reinspect the saved candidate, then simulate and record it through the
   existing evidence/ledger workflow. A repair recipe itself is not a run,
   an adopted calibration result, or authority to overwrite current-best state.

An in-range inspection produces no repair calls. A bounded trial reports both
the requested percentage and the resulting targets. No intermediate physical
invalidity is needed: for example, a proposed fan efficiency of 1.1 can be
explicitly bounded to 0.9 before the candidate is constructed.

## Meaning of an absolute target

| Parameter | Canonical value and behavior |
|---|---|
| LPD / EPD | Total lighting/equipment W/m² per zone, not W/m² for each load object |
| OCD | Total people/m²; inverse area/person fields are handled correctly |
| INF | m³/s per m² exterior surface area, not an arbitrary raw flow-field value |
| WIN-U / WIN-SHGC | Simple-glazing U in W/m²-K or SHGC fraction |
| COP | Rated cooling COP; two-speed high COP is the target and low/high ratio is preserved |
| HE | Fraction for fuel/electric coils and boilers, COP for heat pumps; incompatible unit families cannot share one scalar target |
| FAN | Total efficiency fraction for supported conventional fans; motor efficiency is unchanged |

Existing schedules and object methods are preserved. This intentionally differs
from Ruby setters that rebuild load objects: the native load setters redistribute
by scaling existing contributions. Shared ZoneList components must permit the
requested per-zone target without splitting an object. Unequal shared-zone
densities, missing geometry, or zero-to-positive loads requiring a new allocation
are explicit limitations, not guesses. Zero remains inspectable and can be a
valid requested EPD target.

Bounds handling respects ancillary two-speed COP values. If preserving the
low/high ratio cannot satisfy the requested bounds, the recipe is unavailable;
it does not silently change the ratio or claim both speeds are within bounds.
Mixed heat-pump/fraction HE targets likewise require an explicit domain decision.

## Scope

These are primitives for explicit candidate construction, not a replacement
optimizer, completed calibration, or implementation of all four Phase-3
bounds-extreme stacks. OAF, schedules, geometry changes and other unsupported
parameters remain outside this slice. OSM Ruby recipes and scoring/state
arithmetic remain separate. SF 9.2 simulation still requires a matching runtime
decision; finding fields with a 9.2 IDD is not evidence of executable readiness.

## Verification (2026-09-10)

- 29 focused EnergyPlus calibration tests pass, plus all 23 calibration-MCP
  tests. Scoped Ruff and both repositories' diff checks pass.
- Registered tools exercised all nine exact setters, candidate reload and
  canonical reinspection, project-specific recipes, a 2 → 6.5 W/m² LPD repair,
  an in-range no-op, and a +200% trial on 12 W/m² clipped explicitly to the
  office upper bound of 27.8 W/m². State-bound overrides, stale input hashes,
  incompatible HE units and two-speed COP bound conflicts have focused tests.
- Two annual EnergyPlus 25.1 example runs completed with monthly electricity
  and gas SQL output: `absolute-nine` and `bounded-trial`. They had zero severe
  errors and respectively four and thirteen warnings. These use the shipped
  thermostat-fault medium-office example (faults retained) and SF weather;
  they are interface checks, not calibrated SF buildings or convergence proof.
- Read-only, in-memory tests with the matching 9.2 IDD verified all nine
  absolute operations on all 111 original SF models. Requested values were
  LPD 12, EPD 10, OCD 0.1, INF 0.0005, U 2, SHGC 0.4, COP 3, HE 0.85,
  and FAN 0.7 in the canonical units above. All source hashes stayed unchanged;
  no SF IDF was saved or simulated. This tests those values and object types,
  not every possible bound combination or future model.
- Artifacts/scripts are in
  `energyplus-mcp-server/outputs/calibration-absolute-20260910/` (Git-ignored):
  `smoke-summary.json`, `tool-responses.json`, `hvac-audit.json`, `load-audit.json`,
  and `inf-audit.json`. The last file supersedes the initial infiltration audit
  after the zero-exterior-area interior-zone correction; the other five load
  and window audit results remain valid.
