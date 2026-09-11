# EnergyPlus-MCP project context

## Scope and working rules

This repository is LBNL's EnergyPlus-MCP, an IDF-native model inspection,
modification, and simulation backend. Preserve that identity when discussing
the broader OpenStudio-AI collaboration; participation does not require
converting every model to OpenStudio's OSM format.

Before changing code, read the current README, inspect the branch and worktree,
and check the actual implementation. The `agentic-bem` branch uses compact
domain-manager/master tools; do not assume the `main` branch's tool surface.
Server source and tests are under `energyplus-mcp-server/`. Preserve unrelated
user changes. Do not launch building simulations, migrate datasets, change
other repositories, or install/export plugins merely to answer an architecture
question.

## Ownership and local repository map

Han Li explicitly clarified that the existing calibration evaluation framework
was built by **LBNL**, not PNNL. Never conflate these two uses of “harness.”

- **LBNL evaluation framework — Archetype Foundry:**
  `/Users/hanli/Documents/projects/Openstudio-AI/OS-Prototype-Models/OS-model-utils`.
  A React/FastAPI application with an OpenStudio worker and separate host-side
  `agent_runner/`. It generates reference/controlled models, runs legacy Gem
  calibration and unattended agentic trials, and compares fit, simulation
  effort, runtime, cost, and truth recovery. Agentic trials use OpenCode and
  isolated NLR OpenStudio-MCP execution. Consult its README and
  `agent_runner/README.md` for the current contract.
- **LBNL calibration domain service:**
  `/Users/hanli/Documents/projects/Openstudio-AI/pattern-based-BEM-calibration-mcp`.
  Prototype deterministic metrics, pattern analysis, parameter-selection
  support, calibration state, audit ledger, and report finalization. The thin
  LBNL domain skill supplies methodology, phase procedure, and engineering
  judgment. Backend-independent arithmetic does not mean every gate or
  parameter recipe already supports IDF.
- **LBNL EnergyPlus-MCP:** this repository,
  `/Users/hanli/Documents/GitHub/BEM-AI/EnergyPlus-MCP`.
- **PNNL deployable agent harness — source of truth:**
  `/Users/hanli/Documents/GitHub/BEM-AI/openstudio-ai-harness`.
  A portable agent runtime and developer workbench, not LBNL's calibration
  benchmark application. It packages its own foundational MCP, host adapters,
  workflow skills, reviewed knowledge, SDK lookup, blackboard state, artifact
  tracking, learning contracts, and behavioral evals.
- **PNNL generated plugin distribution:**
  `/Users/hanli/Documents/GitHub/BEM-AI/openstudio-ai-plugins`.
  Generated Claude (`openstudio-ai/`) and Codex (`plugins/openstudio-ai/`)
  packages. Change harness source and re-export; do not hand-edit generated
  plugin files. `.generated.json` records export provenance and compatibility.
- **NLR OpenStudio-MCP:** a separate modeling/simulation server, not PNNL's
  `openstudio_mcp/` package. A previously inspected local checkout is at
  `/Users/hanli/Library/Mobile Documents/com~apple~CloudDocs/LBNL/projects/OpenStudio-AI/openstudio-mcp`.
  Verify the actual connected server/image and version before using it.

## PNNL architecture and current integration boundaries

Inspected local source on 2026-09-10: harness revision `48783fc`, plugins
revision `2a3c05a`. Plugin metadata reports version `0.2.3`, MCP interface
contract `3`, and export source revision `593c5720f900ca135b5c84903fff12e99a5fd3ed`.
These are inspection snapshots, not guarantees about installed or remote state.

- PNNL's host connection is `openstudio_ai`, launching `openstudio-ai-mcp`.
  NLR's configured connection is `openstudio-mcp`; the PNNL workflow's stable
  NLR provider identifier is `nlr_openstudio`. Keep these names distinct.
- PNNL already has its own `model_*`, `sim_*`, `results_*`, SDK, approved-measure,
  storage, and `blackboard_*` tools. Its runtime keeps metadata and workflow
  state in SQLite; large models, SQL outputs, and logs remain on disk.
- `skills/openstudio_modeling_orchestrator.md` routes compatible configured NLR
  work to `skills/delegated_nlr_modeling.md`. That policy selects NLR exclusively
  for a modeling phase, while PNNL retains workflow state and provenance.
  It requires preflight, checkpoints between critical mutations, and explicit
  staged provider transitions. Do not allow two providers to mutate the same
  unstaged model. If NLR is unavailable or unsuitable, the current fallback is
  PNNL's own OpenStudio route, **not EnergyPlus-MCP**.
- The parent workflow owns blackboard mutations; child skills return narrow
  patches. Record provider identity, run IDs, model lineage, host/container
  paths, hashes when available, and warnings. A container path such as `/runs`
  must not be treated as a host path.
- Blackboard schemas permit extensible state/artifact metadata. This offers
  a plausible integration point, but does not prove an IDF provider workflow
  is implemented or validated.
- Skills and references are registered in `harness/asset_manifest.yaml` and
  exported through `adapters/`. Exported learning contracts support candidate
  drafting, not automatic persistence or promotion into trusted assets.

Useful PNNL source references (relative to the harness repository):
`README.md`, `CONTRIBUTING.md`, `docs/HARNESS_DETAILS.md`,
`skills/delegated_nlr_modeling.md`, `skills/openstudio_modeling_orchestrator.md`,
`blackboard/README.md`, `blackboard/schemas/workflow_state.schema.json`,
`blackboard/schemas/artifact_record.schema.json`, `openstudio_mcp/README.md`,
and `evals/README.md`. The README's `docs/MULTILAB_ONE_MONTH_PLAN.md` link was
missing from this checkout; do not cite it as inspected evidence.

## Calibration integration direction and initial MVP

The working recommendation is one shared calibration methodology with two
execution paths: OSM through NLR OpenStudio-MCP; native IDF through enhanced
LBNL EnergyPlus-MCP. LBNL's existing evaluation framework is the immediate
testing venue. PNNL harness integration is a separate deployment/integration
target, not a replacement for that framework or a prerequisite for IDF trials.

Keep three responsibilities distinct:

1. LBNL evaluation framework: datasets, isolated trials, comparative metrics.
2. PNNL harness, when integrated: agent hosting, workflow routing/checkpoints,
   provider decisions, artifact provenance, and reviewed skill distribution.
3. LBNL calibration-MCP: authoritative calibration arithmetic, domain state,
   accepted candidates, audit ledger, and report evidence. Reference these
   records from the PNNL blackboard rather than independently recomputing them.

The agent coordinates domain and execution MCP calls. The current LBNL
calibration-MCP and simulation MCP do not call one another; they share a runs
directory. Its documented evidence contract is:

- `<runs_dir>/<run_id>/run/eplusout.sql`, with monthly facility electricity/gas;
- `<runs_dir>/<run_id>/run_record.json`, used to count physical simulations.

Do not assume PNNL artifact IDs, NLR run IDs, and LBNL calibration run records
are interchangeable. Integration needs explicit identity/path mappings and
consistent provenance, units, calendars, runtime versions, and budget counting.

The initial native-IDF LPD slice was implemented on 2026-09-10; see
`docs/calibration-idf-mvp.md` for the verified scope and usage. EnergyPlus-MCP
now exposes `calibration_manager` capabilities/perturbation and an opt-in
`simulation_manager(..., runs_dir=...)` evidence layout. Calibration-MCP has
an EnergyPlus backend with capability-based gates, while retaining OpenStudio
as its default. The next implementation slice adds percentage operations for
EPD, OCD, INF, WIN-U, WIN-SHGC, COP, HE, and FAN alongside LPD. The shared
calibration_manager dispatches native planners in utils/calibration_loads.py
and utils/calibration_hvac.py; calibration-MCP supplies recipes and enables
only model-specific complete coverage. Partial/absent coverage is pre-closed,
not silently substituted. A subsequent slice adds native inspect/set operations
and calibration-MCP explicit bound-repair/bounded-trial recipes; see
`docs/calibration-absolute-setters.md`. Load setters preserve existing schedules
and scale aggregate per-zone contributions, rather than recreating objects as
some Ruby measures do. Shared unequal-zone targets, zero-to-positive allocation,
mixed HE unit families and incompatible two-speed COP bounds remain explicit
limitations. Do not infer convergence from the small integration smokes;
consult the measured-bill campaign below for the first full-loop evidence.
The expansion passed 18 focused EnergyPlus tests and 22 calibration-MCP tests.
A read-only 111-model audit using the installed 9.2 IDD found complete coverage
for all nine operations and validated sample perturbation field ranges; it
did not simulate or save those SF models. Two 25.1 reference-example runs
validated the expanded tool path. Native 9.2/25.1 load-field aliases are
resolved by the planners; do not assume field labels are version-invariant.
Absolute changes can use an atomic target-ID/value map bound to the inspected
source hash. No-op repairs use a tight numeric tolerance, not repeated edits
for floating-point noise. Calibration-MCP still does not edit or simulate
models or adopt repaired candidates; its recipes are only plans, and existing
ledger/state acceptance remains authoritative.
The absolute slice passed 29 focused EnergyPlus tests and 23 calibration-MCP
tests. All nine absolute operations were verified in memory at sample targets
across 111 original 9.2 SF models with unchanged source hashes, plus two 25.1
example simulations. Shared infiltration scopes may contain interior zones
with zero exterior area: exclude them only when their flow is provably zero
and geometry exists. See the absolute handoff for audit files and remaining
limits; these are not full SF calibration or bounds-extreme campaigns.

`model_upgrade` is a separate, copy-only MCP operation for one IDF. Its
read-only plan discovers the local adjacent official transition chain and
required executable, IDDs, and report-variable mapping CSVs; a run creates a
new migration tree and `migration-manifest.json`, never a simulation
`run_record.json`. It reports `simulation_validated: false`, so a successful
transition is not equivalent to a physical simulation, a calibrated fit, or
calibration-candidate adoption. The container sets
`EPLUS_TRANSITION_DIR=/app/software/energyplus-transitions`; otherwise the
configured EnergyPlus `PreProcess/IDFVersionUpdater` is used. Do not add a
transition step implicitly to a simulation or calibration workflow.

Remaining work includes more semantic parameter operations, explicit PNNL
IDF routing/delegation, and LBNL runner input/output generalization. PNNL
plugin connector setup and exported calibration assets also need deliberate
integration; connecting a server alone is not enough.

Port measure semantics, not just Ruby syntax: for example, the inspected
`Set Occupancy Ratio` measure changes people, lighting, and equipment together.
Preserve bounds, shared-object behavior, baseline-versus-current semantics,
and before/after validation. Keep the agent's auditable stepwise calibration
loop rather than replacing it with an unrequested monolithic optimizer.

## Building dataset and evidence cautions

New SF models are under
`/Users/hanli/Energy Technologies Dropbox/Han Li/Shared_with_me/OpenStudio/OpenStudio AI/Energy Models from 2 Districts in SF`.
Prior inspection found 111 baseline IDFs, all declaring EnergyPlus 9.2, and a
matching historical-results workbook. Do not feed historical calibrated
answers into blind agent trials. Verify bill units, weather, calendar, IDD,
and EnergyPlus compatibility before running or transitioning models; the
EnergyPlus-MCP README currently specifies a 26.1.0 default.

The workbook `original test results for 111 SF building dataset.xlsx` stores
the building-69 gas bill row in kWh, despite a separate 11-building archive
using therms. Convert this workbook's gas values explicitly using
29.307106944444445 kWh/therm; never transfer unit assumptions between the two
sources without verification.

The first qualified measured-bill native-IDF campaign is documented in
`docs/sf-native-idf-calibration-pilot.md`. Campaign 004 upgraded building 69 to
EnergyPlus 26.1, enforced the 2019 RunPeriod, and completed 81 distinct physical
runs through EnergyPlus-MCP plus calibration-MCP. The final report is an honest
failure: six parameter sweeps improved the score, but the model remained far
outside convergence when the active priority list was exhausted. Campaign 002
used a synthetic 2007 calendar and is integration-only evidence; campaign 003
is a retained pre-calibration failure caused by an incompatible
`Treat Weather as Actual=Yes` setting. Do not cite either as measured-calendar
calibration evidence.

The campaign establishes full-loop plumbing, not broad SF calibratability.
Highest-priority semantic gaps are lighting/equipment/HVAC schedules, coupled
occupancy ratio, heating/cooling setpoints, outdoor-air/economizer controls,
service hot water, and the four Phase-3 bounds-extreme diagnostic stacks.

IDF-to-OSM reverse translation must be assessed for HVAC/control loss; creating
an OSM file is not proof of equivalent simulation behavior. Prefer native-IDF
testing or recovering original OSMs; treat conversion as a separately validated
option, not a required first step.

Han reports an 11-building completed campaign. Prior inspection found inputs
for all 11 and completed agent summaries for three distinct SF buildings in
Archetype Foundry's `data/agentic_jobs/`; the full 11-building agent results
location was not established. Distinguish reference/Gem archives from agent
results, and do not claim that all 11 agent outcomes were independently verified.
