# Workflow-neutral tool-surface migration

EnergyPlus-MCP is an IDF-native modeling and simulation provider. Calibration,
retrofit selection, priorities, bounds, candidate acceptance, and reporting
belong to workflow/domain services. The default MCP surface therefore exposes
modeling-domain managers and no workflow-specific manager.

## Operation map

| Historical call | Generic replacement |
|---|---|
| `calibration_manager(action="capabilities")` | Call `parameter_capabilities` on `internal_load_manager`, `envelope_manager`, and `hvac_manager`; the workflow owner aggregates the reports. |
| `calibration_manager(action="inspect", parameter=...)` | Call the owning manager with `action="inspect_parameter"`. |
| `calibration_manager(action="perturb", parameter=...)` | Call the owning manager with `action="adjust_percentage"`. |
| `calibration_manager(action="set", parameter=...)` | Call the owning manager with `action="set_parameter"`. |
| `retrofit_manager(..., measure="add_window_film")` | `envelope_manager(action="modify", op="window.add_film", ...)` |
| `retrofit_manager(..., measure="add_cool_roof_coating")` | `envelope_manager(action="modify", op="surface.apply_coating", target="roof", ...)` |
| `retrofit_manager(..., measure="add_cool_wall_coating")` | `envelope_manager(action="modify", op="surface.apply_coating", target="wall", ...)` |
| `retrofit_manager(..., measure="reduce_infiltration")` | `envelope_manager(action="modify", op="infiltration.scale", ...)` |

Parameter ownership is fixed: LPD, EPD, and OCD belong to
`internal_load_manager`; INF, WIN-U, and WIN-SHGC belong to
`envelope_manager`; COP, HE, and FAN belong to `hvac_manager`.

The generic actions preserve the existing source-hash binding, target IDs,
canonical units, complete/partial/none coverage, no-op tolerance, before/after
validation, shared-object handling, and explicit limitations. They do not
embed calibration bounds or workflow decisions.

## Temporary compatibility façade

For an existing client that cannot migrate atomically:

```yaml
tool_surface:
  mode: domains
  compatibility:
    workflow_managers: true
```

The equivalent environment setting is
`MCP_ENABLE_WORKFLOW_COMPATIBILITY=true`. This exposes both deprecated managers
as aliases over the domain implementation. The aliases are disabled by default
and are intended for removal after downstream recipes use the generic calls.

## Surface modes and wrappers

`domains`, `masters`, and `hybrid` are supported and registration tests assert
their exact, duplicate-free tool sets. `idf_modification` is a core tool and is
registered only once in every mode.

The former `enable_wrappers` option and `MCP_EXPOSE_*_WRAPPERS` environment
variables never registered the documented wrapper tools. They are removed;
enabling one now produces an explicit startup error. Use the relevant manager
or master tool instead.

## Integration boundary

Calibration-MCP owns the parameter ontology, model-specific capability gate,
bounds, recipes, audit ledger, and evidence interpretation. It returns generic
EnergyPlus-MCP calls for IDF work and OpenStudio/Ruby-measure calls for OSM
work. Neither server calls the other; the existing simulation evidence layout
under `<runs_dir>/<run_id>/` is unchanged.

The PNNL harness is not modified by this migration. A future integration can
route an IDF modeling phase to EnergyPlus-MCP while retaining parent-owned
blackboard state, provider identity, model lineage, hashes, host/container path
mapping, and artifact provenance. Generated plugin distributions must continue
to be produced from harness source rather than hand-edited.
