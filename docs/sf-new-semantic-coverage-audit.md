# SF new semantic coverage audit

Audited 2026-09-11. The full, machine-readable matrix is in
`energyplus-mcp-server/outputs/audits/sf_new_semantic_coverage.json`.

## Method

The audit loaded all 111 original SF baseline IDFs with the archived
`V9-2-0-Energy+.idd` transition IDD and used the current non-mutating
utilities: `ScheduleGraph`/`ScheduleEditor`, `hvac_controls` with the graph
adapter, `coupled_occupancy`, and `service_water`. Each operation used a no-op
dry plan or inspection. No source model was saved, upgraded, or simulated; the
audit recorded a SHA-256 before and after each source read and all 111 matched.

One existing upgraded copy was also inspected, without creating it:
`outputs/model-upgrade-mcp-20260910/sf-69/stages/model-V26-1-0.idf`, using its
archived 26.1 IDD. It is a compatibility comparison for SF model 69, not
evidence of a new upgrade, a simulation, or calibration validity.

Coverage requires all relevant targets discovered by an operation. `partial`
and `ambiguous` are therefore unsupported; no convenient subset is treated as
an editable whole-model operation.

## Original 111 EnergyPlus 9.2 IDFs

| Semantic family | Complete | Partial | None | Ambiguous |
| --- | ---: | ---: | ---: | ---: |
| `lighting_schedule` | 111 | 0 | 0 | 0 |
| `equipment_schedule` | 111 | 0 | 0 | 0 |
| `hvac_availability_schedule` | 111 | 0 | 0 | 0 |
| `heating_setpoint` | 111 | 0 | 0 | 0 |
| `cooling_setpoint` | 111 | 0 | 0 | 0 |
| `outdoor_air_flow` | 111 | 0 | 0 | 0 |
| `economizer_control` | 111 | 0 | 0 | 0 |
| `coupled_occupancy` | 111 | 0 | 0 | 0 |
| `service_water_efficiency` | 111 | 0 | 0 | 0 |

The relevant positive object-family inventory across the originals includes
1,544 `ZoneControl:Thermostat`, 716 `Controller:OutdoorAir`, 125
`DesignSpecification:OutdoorAir`, 125 each of `Lights`, `ElectricEquipment`,
and `People`, 111 `WaterHeater:Mixed`, and 310 each of `WaterUse:Equipment`
and `WaterUse:Connections`. The schedule graph contains 2,432
`Schedule:Compact`, 2,185 `Schedule:Constant`, 15,762
`Schedule:Day:Interval`, 1,776 `Schedule:Week:Daily`, and 1,776
`Schedule:Year` objects.

The supported-target inventory provides a more direct view of the exercised
families: 888 terminal `Schedule:Day:Interval` targets for each of lighting
and equipment schedules; 1,544 dual-setpoint thermostat targets for each
setpoint operation; 125 DSOA targets; 716 outdoor-air controller targets; and
666 water-heater plus 310 water-use service-water targets. HVAC availability
targets cover 509 `Fan:ConstantVolume`, 207 `Fan:VariableVolume`, 509
`Coil:Cooling:DX:SingleSpeed`, 207 two-speed DX cooling coils, 509 fuel
heating coils, and 1,242 water heating coils.

## Dominant gaps and smallest next slices

No semantic family has a non-complete result in the re-audited originals. The
three narrow corrections were verified across all 111 models: canonical
thermostat consumer matching restores the existing deadband and terminal-
schedule closure checks; occupancy resolves only geometry-proven floor area;
and `Controller:WaterCoil` is not treated as an economizer controller. The
object inventory contains 207 water-coil controllers, which are deliberately
outside economizer-operation relevance rather than newly editable objects.

This is coverage-only evidence. It does not imply calibrated behavior,
simulation validity, or that currently supported structures cover all possible
EnergyPlus object families.

## Existing 26.1 comparison

The one existing model-69 26.1 copy is complete for all nine operations. This
comparison is read-only compatibility evidence, not an upgrade, simulation, or
calibration result.
