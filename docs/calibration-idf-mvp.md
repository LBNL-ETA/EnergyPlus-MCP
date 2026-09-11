# Native-IDF calibration MVP

This document records the initial percentage-only slices. The subsequent
[absolute-setter and bound-planning slice](calibration-absolute-setters.md)
adds explicit inspection/set operations; the percentage-slice limitations
below describe what was verified at that earlier stage.

Implemented 2026-09-10 in EnergyPlus-MCP and the adjacent LBNL
`pattern-based-BEM-calibration-mcp` repository. This is the first integration
slice, not the full SF calibration campaign or PNNL harness integration.

## Minimal workflow

1. Select an EnergyPlus executable and IDD compatible with the input IDF.
   Call `parameter_capabilities` on `internal_load_manager`,
   `envelope_manager`, and `hvac_manager`, and pass the reports to the
   calibration service's backend-aware gate.
2. Create a calibration project with `backend="energyplus"` and a shared
   `runs_dir`; ingest the monthly bills and classify climate as usual.
3. Run the baseline with `simulation_manager(action="run", idf_path=...,
   weather_file=..., runs_dir=...)`. Record the returned run ID with the
   explicit baseline `model_path` in calibration-MCP.
4. Use the existing pattern/state/selection tools. Obtain, for example,
   `get_measure_recipe("COP", 10, project_id=...)` from Calibration-MCP.
   It resolves to `hvac_manager(action="adjust_percentage", parameter="COP")`;
   add explicit `idf_path` and a different `output_path`.
5. Simulate that output through the same `runs_dir` route. Record the
   candidate with its `model_path`, explicit `seed_model_path`, selection,
   value, and decision. Continue the existing sweep/commit procedure.

The first implementation exposed these operations through a workflow-specific
`calibration_manager`; current releases route the same semantics through the
owning domain manager. The deprecated façade is opt-in only.

LPD means a signed percentage change from the explicitly supplied input:
`after = before * (1 + value / 100)`. The native implementation scales each
Lights object's active power field (LightingLevel, Watts/Area, Watts/Person).
It returns before/after changes. The same interface now covers nine percentage
operations; OSM Ruby recipes remain unchanged.

## Native percentage coverage

| Parameter | Implemented scope |
|---|---|
| LPD | Lights: active LightingLevel, Watts/Area, Watts/Person field |
| EPD | ElectricEquipment: active EquipmentLevel, Watts/Area, Watts/Person field |
| OCD | People: Number, People/Area, or inverse Area/Person scaling |
| INF | ZoneInfiltration:DesignFlowRate: active flow/zone, area, exterior area/wall area, or ACH field |
| WIN-U / WIN-SHGC | Single SimpleGlazingSystem layer used by detailed Window surfaces; shared material edited once |
| COP | DX single-speed; both high/low COPs of DX two-speed; Chiller:Electric:EIR reference COP |
| HE | Fuel burner efficiency, hot-water boiler nominal thermal efficiency, electric coil efficiency, single-speed heating DX COP |
| FAN | ConstantVolume, VariableVolume, OnOff total efficiency (not motor efficiency) |

Capabilities with an input model report complete/partial/none coverage;
without a model they report unverified coverage. Partial coverage rejects
the entire operation before saving. Unsupported examples include layered
windows, windows sharing simple glazing with glass doors (cloning required),
ITE equipment, alternative infiltration/airflow-network objects, modern fan
types, and unimplemented DX/VRF equipment. Heating water coils are not an
efficiency knob; use the plant boiler. Zone exhaust fans are outside the FAN
operation's scope. This is a supported-object parameter operation, not a
general HVAC topology editor or an exact translation of every Ruby behavior.

All changes are relative to the explicit input file. `+10` means multiplying
the active parameter by 1.1, except inverse Area/Person storage divides by
1.1 to increase occupancy density. No hidden clipping is performed: invalid
physical values fail. Domain-specific calibration bounds, absolute-value
setters, bound repair, and coupled OCC-RATIO changes are **not implemented**.
EnergyPlus IDD field limits are checked, including eppy's list-valued limits.
The agent must stop or report a limitation if a workflow needs a missing
operation; it must not substitute a percentage for an absolute setter.

Calibration runs add monthly electricity/gas meters and SQLite output to a
working copy, leaving the source untouched. Each unique run has `in.idf`,
`run_record.json`, and `run/eplusout.sql`. The calibration service consumes
those artifacts; neither MCP calls the other. Execution is still synchronous.

## Expanded-operation verification

- 18 focused EnergyPlus calibration tests and all 22 calibration-MCP tests pass.
- A read-only audit of all 111 SF IDFs with the matching 9.2 IDD found
  complete object coverage for all nine operations. Plans at +10% (LPD,
  EPD, OCD, INF, COP) and -5% (U, SHGC, HE, FAN) passed native numeric field
  limits. All source hashes stayed unchanged; no SF models were saved or
  simulated. `sf-plan-audit.json` records per-model results. This directly
  tests planners, not the runtime-readiness gate: the 25.1 runtime still
  cannot execute those 9.2 inputs without a separate compatibility decision.
- Registered tool calls exercised capabilities, both calibration gates, all
  nine project recipes, all nine edits, and candidate IDF reload checks.
- EnergyPlus 25.1 completed a baseline and combined nine-parameter candidate
  using its `Fault_ThermostatOffset_RefBldgMediumOfficeNew2004.idf` example.
  Existing example faults were retained; SF weather was used only as a smoke
  input. Both outputs contain 12 monthly electricity/gas values, with zero
  severe errors (two warnings each). This is not a calibrated SF building.
- An initial simulation attempt exposed eppy's temporary-file write beside
  the read-only source. The calibration run now points eppy at the staged
  `in.idf`. The failed attempt is retained: two successful engine runs plus
  one failed pre-engine staging record, three run records in total.
- Expansion artifacts, scripts, and change evidence are under
  `energyplus-mcp-server/outputs/calibration-expanded-20260910/` (Git-ignored).
- No absolute setters, domain bound repair, full sweep/convergence, SF
  simulation campaign, or harness/plugin integration is claimed.

## Initial LPD slice verification (historical)

- Two focused EnergyPlus tests and the calibration repository's 20 tests pass.
- A registered-MCP integration check used the repository's EnergyPlus 25.1
  `5ZoneAirCooled.idf` with the installed 25.1 runtime and SF weather.
- Baseline and -10% lighting runs produced readable monthly SQL. All five
  Lights objects scaled correctly, source bytes stayed unchanged, and
  calibration-MCP recorded two distinct runs, metrics, patterns, and an LPD
  selection. Report-draft backend/IDF fields were checked as well.
- Bills were deliberately synthetic (90% of baseline electricity, unchanged
  gas). This checks integration, not calibration convergence or accuracy
  against real SF utility bills. The candidate is left uncommitted/rejected
  in this smoke; no complete sweep or terminal report is claimed.
- Final-source smoke artifacts are under
  `energyplus-mcp-server/outputs/calibration-mvp-20260910-final/` (Git-ignored).
  `smoke-summary.json` and `tool-responses.json` hold the results.
- The SF 9.2 models still need a runtime/version decision and qualified
  bills/weather. No source models were upgraded, and no PNNL or Archetype
  Foundry code was changed.

For local execution set `EPLUS_IDD_PATH` to the installed `Energy+.idd` and
`WORKSPACE_ROOT` to a writable workspace. When that workspace is not the
server source directory, set `MCP_CONFIG_PATH` explicitly to the repository's
`energyplus-mcp-server/config.yaml` to retain its configured domain-tool mode.
