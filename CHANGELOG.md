# Changelog

All notable changes to this project are documented here.
This file follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

The project follows [Semantic Versioning](https://semver.org/). Before 0.2.0
there were no tagged releases; untagged snapshots of `main` also reported
version `0.1.0`.

## [Unreleased]

### Changed
- **Tool replies are 80–96 percent smaller.** For a typical set of read
  calls an agent now receives 59 KB instead of 300 KB on a five-zone model,
  and 55 KB instead of 1,339 KB on a 950 KB OpenStudio-generated model:
  - Every JSON reply is sent without indentation (25–57 percent of each
    reply); `MCP_COMPACT_JSON=0` restores the tools' own formatting.
  - `schedule_manager` `inspect`, `geometry_manager` `extract_and_summary`,
    `envelope_manager` `inspect` (focus `all`) and `hvac_manager`
    `inspect_controls` return a summary by default and take
    `detail="full"` for the previous reply, which is unchanged. Summaries
    keep problems (skipped, ambiguous, invalid, missing items) and the
    schedule consumers that edits refer to while there are at most 100; a
    list is never truncated, only replaced by counts, and each summary says
    what it omitted and how to get it.
  - `geometry_manager` and `envelope_manager` `generate_html_str` save the
    viewer to `reports/` (or `output_path`) and reply with its path and
    size; `return_html=True` returns the page inline as before.
  - Replies that name a saved file include `workspace_path`, relative to
    the caller's workspace, and `how_to_open` (over HTTP, a `file_transfer`
    download), instead of only the server's absolute path.
- **Capability checks and model parsing are about ten times faster.** The
  aggregate `parameter_capabilities` call on six test models went from
  0.11–5.10 s to 0.02–0.50 s locally (5-zone model: 2.09 s to 0.19 s;
  a 950 KB OpenStudio-generated model: 5.10 s to 0.50 s), with identical
  output. Four changes:
  - eppy's field-name helpers (`makefieldname`, `onlylegalchar`) are
    memoized for the process (`utils/eppy_speedups.py`). They depend only on
    IDD label text, so this speeds up every model parse in every tool.
  - Within one capability call, read-only callers share one parsed model
    (`utils/model_cache.py`): twelve parses of the same file became one.
    Applied edits still parse their own copy.
  - The schedule graph is built once per call instead of seven times, and
    the schedule-reference field check is memoized.
  - Zone geometry is computed once per call and copied to each caller.
  Shared data lives only for one call, is keyed by the file's path, size and
  modification time, and is never shared between concurrent calls. Setting
  `EPLUS_MCP_VERIFY_SHARED_MODELS=1` re-parses each shared model when the
  call ends and fails if one was changed in memory.

### Added
- `parameter_capabilities` reports are tamper-evident: `report_sha256` is
  the SHA-256 of the report's own content (sorted-key compact JSON without
  that field; the method is stated in `report_digest_method`), in the inline
  reply, the file, and the short file-mode reply.
  `domains.capabilities.verify_report_digest` is the reference check for
  consumers. A rewritten copy, such as one with `coverage` removed from a
  declaration, which calibration gates currently accept, fails it.
- `parameter_capabilities` enforces the capability contract at runtime:
  every declaration must state `coverage` (complete, partial, none,
  ambiguous or unverified) and a boolean `supported`, true only with
  complete coverage. A manager that breaks it is listed in `errors` and the
  report has `success: false`, so a consumer never has to guess coverage.
- `parameter_capabilities` takes `runs_dir` or `output_path` and then writes
  the full response (`detail="full"` unless given) to
  `<runs_dir>/capabilities/<model_sha256>.json` or `output_path`, replying
  with `capabilities_path`, `capabilities_sha256`, `model_sha256` and the
  coverage index (3 KB instead of 38 KB on a five-zone model). A consumer
  such as the calibration gates can read the file instead of the agent
  copying the response; calibration run counting only looks for
  `<runs_dir>/*/run_record.json`, so the file is never counted as a run.
  The response also states `model_sha256` at the top level.
- Google sign-in (OAuth) for the streamable-HTTP transport, for clients such
  as ChatGPT apps that cannot send a fixed bearer token. Set `MCP_OAUTH` and
  `MCP_PUBLIC_BASE_URL`; only listed emails get in, each mapped to a workspace
  label. Registered clients, codes and tokens are signed and self-contained,
  so no database is needed. `deploy.sh` takes `OAUTH_SECRET` and
  `PUBLIC_BASE_URL`.
- `parameter_capabilities(idf_path, detail="summary")` tool: the
  `parameter_capabilities` reports of every enabled parameter-owning domain
  manager (internal loads, envelope, schedules, HVAC, service water) in one
  response, with the model format, IDF path, EnergyPlus version, monthly
  meters, and simulation-evidence contract stated once and each manager's
  report under `domain_capabilities`. A consumer such as the calibration
  service's meter and measure-reach gates takes it unchanged. Agents
  previously called five managers and assembled the result by hand; in an
  LLM-driven calibration pilot the hand-built object dropped the heating and
  cooling setpoint, outdoor-air, and economizer reports, closing those
  parameters as unreachable. `detail="summary"` omits per-object target and
  relationship listings (on a 15-zone office model, a 31K-character response
  instead of 398K characters across the five manager calls);
  `detail="full"` keeps them. The tool is registered whenever at least one of
  those domain managers is enabled.
- `hvac_manager` `visualize` now writes HTML by default (`image_format`
  defaults to `html`; pass `png`, `svg`, `pdf` or `jpg` for a Graphviz image
  of one loop): a self-contained
  page (inline SVG; no Graphviz or network access) that draws each loop's
  supply side (left to right) and demand side (right to left) in dashed
  frames, with splitters, parallel branches, and mixers, and closes the loop
  outside the frames with arrows labelled by their nodes. Hovering a component
  shows its inlet and outlet nodes, and a table lists every component and its
  nodes. Clicking a frame focuses that side and filters the table (a short
  inline script; without scripts the frames still work as links). Without
  `loop_name` it draws every loop on one page.

### Fixed
- **`idf_modification` no longer applies unsafe edits.** Probing it on a
  five-zone model found that a target without `name:` or `zone:` changed every
  object of the type, an edit with one invalid field was saved with the
  others, `output_path` could overwrite the source, and invalid choices,
  references to missing objects, duplicate names, and deletes of objects still
  in use were all accepted. Now:
  - `target` must be `all`, `name:<name>` or `zone:<zone>`; names, zones and
    field names match case-insensitively; anything else is refused.
  - Edits are all or nothing: if any requested change fails, nothing is saved
    and every problem is listed.
  - Values are checked against the IDD's allowed choices (`\key`), and
    references against objects that exist (`\object-list`/`\reference`); `add`
    refuses a duplicate name.
  - `delete` refuses to remove an object others still use, and renaming one is
    refused; the reply lists the users. `force=True` accepts missing references
    and broken uses as warnings, but never invalid fields, values or duplicates.
  - An original model is never overwritten; a working copy in
    `models/derived/` may still be edited in place.
  - `mode="dry_run"` checks and reports without writing.
  Valid edits produce byte-identical files to before (nine edits checked,
  including `internal_load_manager`'s Lights update, which shares the editor).
- **Tools no longer block the server's event loop.** Most tools are `async`
  but did synchronous eppy and file work, so one large IDF load or capability
  scan stalled every other request, including other users' calls and
  `/health`. The tool wrapper in `utils/output_guard.py` now runs every tool
  in a worker thread (`utils/tool_threads.py`). Tools that eppy may touch
  still run one at a time under a process-wide reentrant lock, which
  simulation staging shares; tools marked `eppy_free` (file transfer and
  listing, reference docs, skills, `server_manager`) skip the lock. Tools that
  await real asynchronous work are marked `native_async` and stay on the loop
  (`simulation_manager`, `model_upgrade`); `simulation_manager`'s
  `update_settings`/`update_run_period` edits and run-record lookups now run
  in a thread as well. The caller's identity, and so the per-user workspace,
  is visible inside the worker thread.
- Schedule capability checks and schedule edits were quadratic in a
  schedule's field count: `_field_names` removed duplicate names with a
  list-membership test, and reading every field through Eppy attributes
  scans the field list once per name. Both are now linear, with field values
  read by position under Eppy's own lookup rules. Results are byte-identical
  (capability reports, edit reports, and edited IDFs on three models). The
  aggregate `parameter_capabilities` call on the ASHRAE 90.1 medium office
  example went from 205 s to 8 s, the small office from 103 s to 4 s, and a
  15-zone SF office from 42 s to 5 s.
- The installed EnergyPlus version is cached per executable (keyed by path,
  size, and modification time) instead of starting `energyplus --version`
  for every manager.
- `model_upgrade` `action="run"` failed on Cloud Run with `[Errno 1]
  Operation not permitted`. It copied the transition programs into the output
  directory with `shutil.copy2` and ran them there; over HTTP that directory
  is the caller's workspace, which on Cloud Run is a Cloud Storage mount that
  refuses `chmod`/`utime` and cannot execute programs. Transitions now run in
  a local temporary directory that is removed afterwards, and only the
  stages, logs, and manifest are written to the output directory, as plain
  data copies. The output directory no longer contains `transition-runtime/`
  or `work/`. `file_utils` copy also no longer fails when the destination
  refuses file metadata.
- Duplicate meter checks compared names and frequencies case-sensitively and
  treated `Output:Meter` and `Output:Meter:MeterFileOnly` for the same meter
  as unrelated, so adding `Electricity:Facility, Monthly` to a model that
  already had it as `MeterFileOnly, monthly` (as the 26.1 `5ZoneAirCooled`
  example does) made EnergyPlus warn and report the meter twice. Checks now
  ignore case; a `MeterFileOnly` request already covered by the full meter is
  skipped, and a full-meter request replaces its `MeterFileOnly` variant
  (reported as `replaced_meter_file_only`). A model that already had both is
  tidied for the requested meters (`removed_redundant_meters`). The monthly
  meters that calibration runs add follow the same rules.
- `hvac_manager` `visualize` never drew the detailed loop diagram on Cloud
  Run: the production image lacked the Graphviz `dot` program, so every call
  fell back to a sketch of plant-loop boxes while reporting success, and for
  an air loop drew nothing. `Dockerfile.prod` now installs `graphviz`. If
  Graphviz still cannot run, the diagram is written as HTML and the result
  gives `fallback_reason`; an unknown `loop_name` or a model without loops is
  an error listing `available_loops`; `image_format` (svg, pdf, jpg) now
  reaches Graphviz instead of always producing PNG; and a failed render no
  longer leaves the DOT source file in `reports/`. A loop whose topology
  cannot be read is skipped (`skipped_loops`) instead of failing the whole
  call, and only when no loop can be read does the plant-loop sketch run, with
  a `fallback_reason` that names the failing step. The HTML writer creates a
  missing output folder.

## [0.2.0] - 2026-11-23

First tagged release. It combines the `main` branch with the domain-manager
work developed on `develop` (formerly `agentic-bem`).

### Security
- **Per-token file isolation for the streamable-HTTP transport** (#5, fixes
  #3). Before this release, any valid bearer token could read and write any
  file the server process could reach, including other users' files and
  `/proc/self/environ`. Each token is now confined to its own workspace
  (`<MCP_USER_DATA_ROOT>/<label>`) plus the read-only shared sample, example,
  and weather folders; `..` traversal and symlinks out of the workspace are
  rejected; file access fails closed when a request has no identity; and an
  MCP session is bound to the token that opened it. Operators who ran the HTTP
  transport with real tokens before 0.2.0 should rotate `MCP_TOKENS`.
  Reported by Syed Anas Mohiuddin (@SyedAnas01).
- Over HTTP, every tool output (edited models, simulation runs, reports,
  `output_path`/`output_directory`/`runs_dir`/`target_path` arguments) is
  written inside the caller's workspace, using the same layout as `work/`:
  `models/derived/`, `models/uploads/`, `runs/`, `reports/`. Paths outside
  it, including other users' workspaces, are rejected.
- Simulation runs are private to the token that submitted them: other tokens
  cannot see, wait on, or cancel them, and two tokens may use the same
  `run_id`.
- Over HTTP, models that would escape the caller's workspace are refused
  before EnergyPlus runs them (simulations and output discovery runs):
  `PythonPlugin:*` objects, which make EnergyPlus run Python code from the
  model, `ExternalInterface:*` objects (co-simulation and FMUs), and file
  references (`Schedule:File`, `Schedule:File:Shading`,
  `Construction:WindowDataFile`, ASHRAE 205 representation files, and
  `Table:Lookup`/`Table:IndependentVariable` external files) that use `..` or
  point outside the caller's readable folders. Stdio users are unaffected.
- `server_manager` actions `logs`, `clear_logs`, and `status` with the full
  configuration require a token listed in `MCP_ADMIN_LABELS`. Tokens are
  compared in constant time.

### Known limitations
- The HTTP transport is experimental and meant for a group of trusted
  colleagues, not the public: EnergyPlus was not designed to run untrusted
  models, and tokens do not expire and are not rate limited.
- Links issued by `file_transfer` are kept in memory, so a server restart
  invalidates outstanding links (stored files are kept).

### Added
- **Streamable-HTTP transport** with bearer-token authentication
  (`MCP_TRANSPORT=streamable-http`, `MCP_TOKENS`), a `/health` endpoint, and
  optional DNS-rebinding protection (`MCP_ALLOWED_HOSTS`).
- **`file_transfer` tool for remote clients** (#1). Over HTTP, the server
  issues one-time upload and download links: `request_upload`,
  `upload_status`, `list_uploads`, `delete_upload`, `request_download`. Files
  move directly over HTTP (`curl` or a browser upload page) instead of through
  the conversation. Uploads go to the caller's `models/uploads/` folder;
  downloads are single use, limited to files the caller may read, and send
  folders as `.zip`. Links expire (`MCP_TRANSFER_TTL_SECONDS`), and uploads are
  capped per file and per user (`MCP_UPLOAD_MAX_BYTES`,
  `MCP_USER_QUOTA_BYTES`). Registered only with the HTTP transport.
- GitHub Actions CI running the test suite on Python 3.10-3.13.
- **`idf_modification(action="find")`**, a read-only object lookup: objects of
  a type (exact or wildcard, e.g. `SetpointManager:*`), objects with any field
  equal to a name (node, schedule, construction; case-insensitive), or both,
  narrowed by `name_contains` and capped by `limit`. Results use the eppy field
  names that `modify` accepts and mark each match as `defines` or
  `references`. When the name is listed in a `*NodeList`, objects that use the
  list are returned too, marked `via`. The `diagnose-simulation-errors` skill
  and catalog use it for missing-reference, duplicate-name, node, and
  setpoint errors.
- **`diagnose-simulation-errors` skill**, with `error-catalog.md`: real
  EnergyPlus 26.1 messages for input-schema, missing-reference,
  duplicate-name, node-connection, setpoint, sizing, weather, geometry, and
  psychrometric problems, how to inspect each with the server's tools, and
  which warnings affect results.
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
- `EPLUS_DIST_SUFFIX` Docker build-arg so users can rebuild against older
  (`Ubuntu22.04`) or newer EnergyPlus releases without editing the Dockerfile.
- README section **"Building against a different EnergyPlus version"**
  documenting the `EPLUS_VER` / `EPLUS_HASH` / `EPLUS_PREFIX` /
  `EPLUS_DIST_SUFFIX` overrides, including the extra files that still need
  manual updates when overriding (until path auto-detection lands).
- README **Codex** setup section — UI form fields for the *Connect to a
  custom MCP* dialog plus a `~/.codex/config.toml` variant for the CLI.
- A prerequisites block in the README listing Docker and git.
- Cross-platform config paths (macOS / Windows / Linux) for Claude Desktop
  and Cursor; Windows path-escaping guidance (JSON vs form vs TOML).
- Verify step after each client config.

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
- `mcp` is pinned below 2.0, whose API the server does not support yet.
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

### Fixed
- Output variable and meter discovery use unique temporary files and clean
  them up on failure, so concurrent requests no longer collide.
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
