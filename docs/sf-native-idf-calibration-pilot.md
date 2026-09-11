# SF native-IDF calibration pilot

## Outcome

Building 69 completed a measured-bill, native-IDF calibration campaign through
the real EnergyPlus-MCP and calibration-MCP stdio servers. The campaign proves
that the two services can inspect and edit an upgraded SF IDF, run EnergyPlus,
record physical evidence, score complete step ladders, resume from a checkpoint,
and emit an auditable terminal report.

It did **not** reach the requested calibration criteria. The formal report has
`status: "fail"` and reason `No more parameters are available to tune.` This is
a useful boundary: the execution plumbing is functional, but the current
methodology-to-IDF parameter coverage is not yet sufficient for this building.

The authoritative campaign is
`energyplus-mcp-server/outputs/sf-pilot-20260910/campaign-004/` (Git-ignored).
Its calibration project is `69-c1a7a6`.

## Qualified inputs

- Model: SF building 69, office, packaged HVAC, 1366 m2. The source IDF was
  copied and upgraded from EnergyPlus 9.2 to 26.1 with the `model_upgrade` MCP
  operation. The source was not modified.
- Weather: San Francisco 2019 AMY EPW, SHA-256
  `c7f8947908bb4c4e4b3cc75f48343a824abbc5b9918c08efafd58b58993ef9dd`.
- Calendar: January 1 through December 31, 2019. The start weekday is derived
  from the explicit year. `Treat Weather as Actual` is `No` because this EPW's
  `DATA PERIODS` header omits a year. Every one of the 81 EIO files reports the
  2019 run period, and every ERR file reports successful completion with zero
  severe errors.
- Bills: row 38 of `original test results for 111 SF building dataset.xlsx`,
  sheet `test`. Electricity is `K38:V38` in kWh. Gas is `W38:AH38` in kWh and
  was explicitly converted to therms using 29.307106944444445 kWh/therm. The
  separate 11-building archive uses therms and must not be used to infer this
  workbook's gas unit.
- Blind-input policy: only the building identifier and the 24 utility values
  were used. Historical baseline, calibration trajectory, solution flag, and
  final-result fields were withheld from the campaign manifest.

The complete qualified-input record, including source paths and hashes, is in
`campaign-004/input-manifest.json`.

## Calibration result

The campaign used the relaxed convergence mode and a 150-run budget. It
completed 81 distinct physical runs: one baseline plus eight ten-point sweeps.

| Step | Parameter | Direction | Decision | Best-setting result |
|---:|---|---|---|---|
| 1 | LPD | decrease | adopted | -30% |
| 2 | EPD | decrease | adopted | -30% |
| 3 | FAN | increase | adopted | +30% |
| 4 | WIN-SHGC | decrease | adopted | -30% |
| 5 | COP | increase | adopted | +30% |
| 6 | OCD | decrease | adopted | -30% |
| 7 | WIN-U | decrease | retained incoming model | no rung improved the score |
| 8 | INF | decrease | retained incoming model | no rung improved the score |

Each ladder was generated from its incoming committed model with explicit
absolute assignments. The rungs were not compounded. Bounds were projected by
calibration-MCP before EnergyPlus-MCP saved a candidate.

| Metric | Baseline | Best model | Absolute-error reduction |
|---|---:|---:|---:|
| Electricity NMBE (%) | -1003.88 | -624.87 | 37.75% |
| Gas NMBE (%) | 68.88 | 40.86 | 40.68% |
| Source NMBE (%) | -578.07 | -360.62 | 37.62% |
| Electricity CVRMSE (%) | 968.33 | 603.87 | 37.64% |
| Gas CVRMSE (%) | 107.83 | 76.61 | 28.95% |
| Source CVRMSE (%) | 562.79 | 352.81 | 37.31% |

Annual electricity fell from 316,354 kWh at baseline to 208,623 kWh in the
best intermediate model, versus 31,008 kWh measured. Annual simulated gas rose
from 685 to 1,162 therms, versus 1,857 therms measured. The model therefore
remains far outside calibration criteria even though every adopted step moved
the combined score in the desired direction.

The best model is `models/sweep-06-OCD-10-m30.idf`, SHA-256
`831897d46e60d6300280543d15983d232665a5450139cc3ee605a6dd4fa78622`.
The formal report is
`calibration-workspace/projects/69-c1a7a6/output/calibration_report.json`.

## What is working

- Copy-only 9.2 to 26.1 upgrade with a migration manifest.
- Model-specific capability checks for LPD, EPD, OCD, INF, WIN-U, WIN-SHGC,
  COP, HE, and FAN.
- Canonical inspection and hash-bound absolute assignments.
- Calibration-bound projection before candidate construction.
- Native EnergyPlus 26.1 simulation with monthly electricity and gas SQL.
- One physical `run_record.json` per attempted simulation and distinct-result
  accounting in calibration-MCP.
- Pattern detection, priority selection, complete ladder scoring, commit,
  resumable current-best state, terminal evaluation, and report finalization.
- Explicit, source-qualified escape for an annual-ratio guard. Known unit slips
  remain fatal; the opt-in and warning persist in project evidence.

## What still blocks robust SF calibration

The active electricity universal-bias priority list encountered parameters
that the native path could not yet use:

| Methodology action | Current state | Required next work |
|---|---|---|
| Occupancy ratio | unresolvable | Port the Ruby measure's coupled people, lighting, and equipment behavior rather than treating it as OCD alone. |
| Lighting schedule | unimplemented | Add schedule inspection and bounded schedule-shape/operating-hour edits. |
| Equipment schedule | unimplemented | Add schedule edits with shared-schedule and normalization safeguards. |
| Cooling setpoint | unresolvable | Map thermostats and schedule objects, including shared schedules and deadband checks. |
| HVAC schedule | unimplemented | Add availability-schedule edits without breaking night-cycle/control semantics. |
| Economizer | unresolvable | Support the actual outdoor-air controller families and control limits. |
| Outdoor-air flow | unresolvable | Port flow-method-aware, per-person/per-area semantics and shared design-specification handling. |
| Heating setpoint | unresolvable | Add thermostat schedule editing with deadband validation. |
| Service hot water | unresolvable | Add water-use and plant-side object coverage with fuel attribution checks. |

HE is supported by EnergyPlus-MCP but was not in the active electricity-bias
priority path. WIN-U and INF were exercised but neither improved the score in
the requested direction. These facts must not be reported as general lack of
tool support.

The native path also lacks the methodology's four combined Phase-3
bounds-extreme diagnostic stacks. Until these operations and diagnostics are
available, “parameters exhausted” can be an honest terminal state but not proof
that an SF model is intrinsically uncalibratable.

## Reproduction and resume

Start a fresh qualified campaign with:

```bash
energyplus-mcp-server/.venv/bin/python \
  scripts/run_native_idf_calibration_pilot.py \
  --manifest /absolute/path/to/input-manifest.json
```

Resume an existing project without repeating completed sweeps with:

```bash
energyplus-mcp-server/.venv/bin/python \
  scripts/continue_native_idf_calibration_pilot.py \
  --manifest /absolute/path/to/input-manifest.json \
  --project-id PROJECT_ID \
  --max-sweeps 8
```

The driver sets the container's `UV_PROJECT_ENVIRONMENT` to
`/tmp/energyplus-mcp-venv`; this prevents container-side `uv run` from replacing
the host macOS virtual environment through the repository bind mount.

## Superseded attempts

- `campaign-002` is useful integration evidence only. Its IDF had blank years
  and a hard-coded Monday start, so EnergyPlus used a synthetic 2007 calendar.
  It must not be presented as a valid 2019 measured-bill calibration.
- `campaign-003` correctly failed before calibration because `Treat Weather as
  Actual=Yes` is incompatible with this EPW's yearless `DATA PERIODS` header.
  The failure also led to a simulation error-file lookup correction.
- `campaign-004` is the first qualified measured-calendar campaign.
