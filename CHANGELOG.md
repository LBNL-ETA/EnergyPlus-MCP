# Changelog

All notable changes to this project are documented here.
This file follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Once the project starts cutting tagged releases, entries will graduate from
`[Unreleased]` to a dated version heading (e.g. `[0.2.0] - 2026-05-01`).
Until then, `[Unreleased]` captures all changes landed on the `agentic-bem`
branch since the README/install-instructions cleanup.

## [Unreleased]

### Added
- **`idf_modification(action="find")`**, a read-only object lookup: objects of
  a type (exact or wildcard, e.g. `SetpointManager:*`), objects with any field
  equal to a name (node, schedule, construction; case-insensitive), or both,
  narrowed by `name_contains` and capped by `limit`. Results use the eppy field
  names that `modify` accepts and mark each match as `defines` or
  `references`. When the name is listed in a `*NodeList`, objects that use the
  list are returned too, marked `via`. The `diagnose-simulation-errors` skill
  and catalog use it for missing-reference, duplicate-name, node, and
  setpoint errors.
- **`reference_docs` tool.** Section-level access to the EnergyPlus Input
  Output Reference, Engineering Reference, Output Details and Examples, and
  Plant Application Guide for the installed release: `status`, `search`,
  `get_section` (by object type, cross-reference label, or section id, paged),
  and `get_field`, which pairs a field's constraints from the installed IDD
  with its documentation. A Dockerfile build stage generates the index from
  the documentation's LaTeX source at the release tag matching `EPLUS_VER`
  (`.devcontainer/build_reference_docs.py`, git + pandoc in the build stage
  only) and installs it under `<EnergyPlus>/ReferenceDocs`;
  `EPLUS_REFERENCE_DOCS_DIR` overrides the location.
- **Agent skills.** `list_skills` and `get_skill` serve Markdown skills from
  `energyplus_mcp_server/skills/`, and the server now sends MCP instructions
  pointing agents to them. First skill: `learn-from-examples`, with a
  DataSets guide.
- **`example_library` tool.** Read-only `status`, `object_types`, `search`,
  `describe`, and `get_objects` over the installed EnergyPlus `ExampleFiles`
  and `DataSets`. The inventory is rebuilt automatically when the installation
  changes; `EPLUS_EXAMPLE_INVENTORY_CACHE` optionally persists it.
  `get_objects` returns eppy field names and follows IDD reference lists to
  the schedules, curves, constructions, and zones an object uses.
- `idf_modification` and `file_utils` descriptions point to the skill and the
  example library.
- **Read-only samples and a writable work area.** `sample_files/` is split
  into `basic/`, `mcp_paper/`, and `weather/`, and everything the server
  writes goes under `work/` (`models/uploads`, `models/derived`, `runs`,
  `reports`), which Git ignores. Tool calls whose `output_path`,
  `output_directory`, `target_path`, or `runs_dir` points into `sample_files/`
  or the EnergyPlus installation are rejected. A bare filename or the older
  `sample_files/<name>` path still resolves.

- **Concurrent simulations.** `simulation_manager` queues runs and executes
  up to `MCP_MAX_CONCURRENT_SIMULATIONS` (default: CPU count minus one) at
  once, each as its own EnergyPlus process with its own run and working
  directory. New actions: `submit`, `run_batch`, `wait`, `cancel`, and a real
  `status` (per run, or the whole queue). `run` keeps returning the finished
  result but no longer blocks the server, so parallel `run` calls overlap.
  `MCP_SIMULATION_TIMEOUT_SECONDS` optionally stops runs that exceed a
  wall-clock limit. Every run writes `run_record.json` at submission and at
  each status change; records orphaned by a stopped server are marked
  `interrupted` on the next start.

### Changed
- **Error parsing** (`post_processing(action="parse_errors")`, run status).
  The parser now reads the recurring-error summary (repeat counts, warmup and
  sizing counts, Max/Min) and attaches counts to matching messages; reports
  the run `status` (`completed`, `terminated`, or `incomplete` for a crash),
  EnergyPlus's own `totals`, and per-phase subtotals (replacing
  `phase_counts`, which added the phase subtotals to the totals and
  double-counted); tags each message with a `category`, object, and schema
  field; and takes the first Severe message, not the Fatal announcement, as
  the primary issue. `simulation_manager(action="status")` includes this
  summary for successful runs too. Tests use real 26.1 `.err` files.
- Edits without an explicit `output_path` write to `work/models/derived/`
  instead of beside the source model; HVAC diagrams and geometry viewers
  default to `work/reports/`; simulations default to `work/runs/` (was
  `outputs/`) and stage their input copy in the run directory.
- Bare filenames resolve in the workspace (including `sample_files`
  categories and `work/models`) before EnergyPlus `ExampleFiles`.
- `idf_modification` resolves `idf_path` like the other tools.
- Simulations and the output variable/meter discovery runs launch the
  EnergyPlus command line directly instead of eppy's `IDF.run`, which changed
  the server's working directory and `sys.stderr` and (for meter discovery)
  printed to stdout, corrupting the stdio transport. Default run directories
  now carry a random suffix, so two runs of one model in the same second no
  longer share a directory.
- Calibration run records start as `queued` (with `started_at` updated when
  EnergyPlus launches) instead of `running`.
- `simulation_timeout` now defaults to 0 (no limit); it was never enforced.
- `illustrative examples/` is gone: its two models are now
  `sample_files/mcp_paper/5ZoneAirCooled_baseline.idf` and
  `5ZoneAirCooled_improved.idf`, its weather file is in `sample_files/weather/`,
  and its committed simulation outputs and diagram were removed.
- **EnergyPlus default bumped from 25.1.0 to 26.1.0.** The Docker image now
  bakes in [EnergyPlus v26.1.0](https://github.com/NREL/EnergyPlus/releases/tag/v26.1.0)
  (`EPLUS_HASH=6f2e40d102`). Updated in `.devcontainer/Dockerfile`,
  `energyplus_mcp_server/config.py` (`version` + default install path), and
  `energyplus-mcp-server/.vscode/mcp.json`.
- Dockerfile EnergyPlus download switched from `Linux-Ubuntu22.04-*` to
  `Linux-Ubuntu24.04-*`. NREL stopped shipping Ubuntu 22.04 builds starting
  with 26.1.0.

### Added
- `EPLUS_DIST_SUFFIX` Docker build-arg so users can rebuild against older
  (`Ubuntu22.04`) or newer EnergyPlus releases without editing the Dockerfile.
- README section **"Building against a different EnergyPlus version"**
  documenting the `EPLUS_VER` / `EPLUS_HASH` / `EPLUS_PREFIX` /
  `EPLUS_DIST_SUFFIX` overrides, including the extra files that still need
  manual updates when overriding (until path auto-detection lands).
- README **Codex** setup section — UI form fields for the *Connect to a
  custom MCP* dialog plus a `~/.codex/config.toml` variant for the CLI.
- Branch callout at the top of the README linking back to the `main` README,
  and a prerequisites block listing Docker/git plus the `git checkout
  agentic-bem` reminder.
- Cross-platform config paths (macOS / Windows / Linux) for Claude Desktop
  and Cursor; Windows path-escaping guidance (JSON vs form vs TOML).
- Verify step after each client config, with a branch-mismatch check
  (if the agent sees a flat list like `modify_lights`, the user is on `main`).

### Fixed
- The `.err` parser matched only unindented lines, but EnergyPlus indents
  every message, so warning, severe, and fatal counts were always zero.
- Repo URL and folder name across all install snippets
  (`tsbyq/EnergyPlus_MCP` → `LBNL-ETA/EnergyPlus-MCP`).
- VS Code client config updated from the outdated `"mcp.servers"` key in
  `.vscode/settings.json` to `"servers"` in `.vscode/mcp.json` (VS Code
  1.102+ native MCP format).
- MCP Inspector invocation corrected to
  `npx @modelcontextprotocol/inspector …` (was a non-existent
  `uv run mcp-inspector` command).
- Troubleshooting steps updated to use `server_manager` actions
  (the standalone `get_server_status` / `get_server_logs` / `get_error_logs`
  tools only exist on this branch when `MCP_EXPOSE_SERVER_WRAPPERS=true`).
- Table of Contents rebuilt to match the actual section headers (old TOC
  referenced several sections that no longer existed).
- Stray `outputs_manager` JSON block that had landed after `## License`
  removed; `Tool Surface Profiles (config.yaml)` section folded into
  `## Configuration` where the TOC can reach it.
