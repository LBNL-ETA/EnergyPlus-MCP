# Native IDF version-upgrade proof

This is a copy-only EnergyPlus transition proof for one SF baseline model. It
does **not** establish 9.2-to-26.1 simulation equivalence, calibrated fit, or
approval to migrate the remaining 110 models.

## MCP tool contract

The always-on `model_upgrade` tool provides a one-model local workflow without
Docker, network access, simulation, or calibration-state changes:

1. `action: "plan"` reads the Version object without loading the IDF through a
   newer IDD, then reports the discovered adjacent chain and required
   executable, source/target IDDs, and `Report Variables <from> to <to>.csv`
   mapping files. Planning creates no files.
2. `action: "run"` rechecks that plan and requires a new `output_directory`.
   It stages only copies, records each hop and logs in
   `migration-manifest.json`, and preserves the original hash. Existing output
   trees, downgrades, incomplete chains, and missing assets are refused.

By default it targets the actual configured EnergyPlus runtime. A same-version
request is an explicit no-op. Every result states
`simulation_validated: false`: transition completion neither validates physical
simulation behavior nor adopts a calibration candidate or creates a simulation
`run_record.json`.

At runtime the container supplies the official flat asset directory through
`EPLUS_TRANSITION_DIR=/app/software/energyplus-transitions`; each executable,
version IDD, and report-variable CSV is discovered locally. If that variable is
not set, the tool falls back to the configured EnergyPlus installation's
`PreProcess/IDFVersionUpdater` directory. It never downloads assets or invokes
Docker. The current validated container candidate is
`energyplus-mcp-dev:26.1.0-upgrade-20260910` (EnergyPlus
`26.1.0-6f2e40d102`).

Example plan (read-only):

```json
{
  "tool": "model_upgrade",
  "arguments": {
    "action": "plan",
    "idf_path": "/models/model.idf",
    "target_version": "26.1"
  }
}
```

Example run (only after a `ready` plan; the output path must not exist):

```json
{
  "tool": "model_upgrade",
  "arguments": {
    "action": "run",
    "idf_path": "/models/model.idf",
    "target_version": "26.1",
    "output_directory": "/outputs/model-upgrade-mcp-20260910/sf-69"
  }
}
```

The completed one-model MCP evidence is at
`energyplus-mcp-server/outputs/model-upgrade-mcp-20260910/sf-69-stdio-clean/`:
its `migration-manifest.json` records all 13 adjacent hops, source hash
preservation, and final 26.1 copy. It is an upgrade-mechanics record only, not
simulation or calibration validation.

## Verified representative

- Original (never modified):
  `/Users/hanli/Energy Technologies Dropbox/Han Li/Shared_with_me/OpenStudio/OpenStudio AI/Energy Models from 2 Districts in SF/baseline_models/69/model.idf`
  - Version: 9.2
  - SHA-256 before and after: `335c66350fdd4c009fe8c1f689f33289baab54bcc94b93fbdfe0826121d3a7d3`
- Final transitioned copy:
  `energyplus-mcp-server/outputs/model-upgrade-20260910/sf-69/stages/model-V26-1-0.idf`
  - Version: 26.1
  - SHA-256: `bd179eab9b59126474a66fb5bb8f99ae8c8da79df0dd98d79bf332d12c62ea0f`

Model 69 was selected without reading historical results: it is small but
structurally representative (six zones, 43 opaque surfaces, four fenestration
surfaces, five DX cooling coils, five fuel heating coils, five constant-volume
fans, and the native load/infiltration object types).

## Official sequential chain

The final proof ran these adjacent official transitions, retaining every
intermediate IDF, official audit sidecar, stdout/stderr and hash:

`9.2 → 9.3 → 9.4 → 9.5 → 9.6 → 22.1 → 22.2 → 23.1 → 23.2 → 24.1 → 24.2 → 25.1 → 25.2 → 26.1`

The 9.2-through-25.1 executables came from the installed official EnergyPlus
25.1 IDFVersionUpdater. The last two transitions came from the isolated
`energyplus-mcp-dev:26.1.0-20260910` Linux arm64 candidate, which runs
EnergyPlus `26.1.0-6f2e40d102`.

For each step, the utility stages these required files into a writable runtime
directory before invoking the executable:

- the transition executable;
- its source and target `Energy+.idd` files; and
- its `Report Variables <from> to <to>.csv` mapping.

The mapping CSV is required: omitting it can leave legacy output/meter names
unmapped. The `Rules` and `ObjectStatus` files are documentation, not
transition runtime inputs. The final logs have no report-variable `not found`
notice.

## Historical prototype artifacts and rerun

The final manifest is
`energyplus-mcp-server/outputs/model-upgrade-20260910/sf-69/migration-manifest.json`.
It records 13 successful adjacent steps, 14 versioned IDFs, and 78 transition
artifacts. The output directory is Git-ignored.

The following host-25.1 plus Docker CLI script predates the MCP tool. It is
retained to reproduce historical evidence only, not as the recommended
workflow for new upgrades:

```bash
/usr/bin/python3 scripts/transition_idf_chain.py \
  --source '/absolute/path/to/original/model.idf' \
  --output-dir energyplus-mcp-server/outputs/model-upgrade-YYYYMMDD/model-id \
  --local-transition-dir /Applications/EnergyPlus-25-1-0/PreProcess/IDFVersionUpdater \
  --container-image energyplus-mcp-dev:26.1.0-20260910
```

The Docker candidate must contain both `25.1 → 25.2` and `25.2 → 26.1`
executables, their three adjacent IDDs, and both report-variable mapping CSVs.
The script refuses a missing local adjacent transition, IDD, or mapping and
records source hashes before/after.

## Warning review and limitations

The transition proof validates sequential conversion mechanics and the final
Version object only. It deliberately does not treat a successful transition as
evidence that HVAC controls, output semantics, results, or calibration
behavior are unchanged. Any later runtime test must use the final 26.1 copy,
record the EnergyPlus runtime and weather, inspect the transition audits and
simulation `.err` output, and remain labeled an engineering smoke unless it is
separately validated against an approved reference.

Earlier isolated attempts are preserved under the same output root with
explicit names: `sf-69-preflight-script-error`,
`sf-69-infrastructure-failure`, `sf-69-mapping-assets-incomplete`, and
`sf-69-mapping-staging-error`. They are tooling/infrastructure evidence only
and must not be used for runtime, meter, calibration, or semantic validation.
