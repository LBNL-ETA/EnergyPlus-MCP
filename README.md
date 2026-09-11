# EnergyPlus MCP Server

A Model Context Protocol (MCP) server for EnergyPlus that exposes a **compact, agent-friendly tool surface** built around domain managers (`envelope_manager`, `hvac_manager`, `internal_load_manager`, …) and a few unified master tools. It lets AI assistants load, validate, modify, and simulate EnergyPlus IDF files through a consolidated interface.

> This README documents the compact domain-manager / master-tool architecture
> and its workflow-neutral default surface. Older releases may expose a
> fine-grained tool layout; always use the documentation from the checked-out
> revision.
>
> **Version**: 0.1.0
> **EnergyPlus Compatibility**: 26.1.0 (default; see [Building against a different EnergyPlus version](#building-against-a-different-energyplus-version))
> **Python**: 3.10+

<details open>
<summary><h2>📑 Table of Contents</h2></summary>

- [Overview](#overview)
- [Installation](#installation)
  - [Using the MCP Server](#using-the-mcp-server)
    - [Claude Desktop](#claude-desktop)
    - [Codex](#codex)
    - [VS Code](#vs-code)
    - [Cursor](#cursor)
  - [Development Setup](#development-setup)
    - [VS Code Dev Container](#vs-code-dev-container)
    - [Docker Setup](#docker-setup)
    - [Local Development](#local-development)
    - [Streamable HTTP Transport (Local Testing)](#streamable-http-transport-local-testing)
    - [Building against a different EnergyPlus version](#building-against-a-different-energyplus-version)
- [Available Tools](#available-tools)
  - [Tool Registration Modes](#tool-registration-modes)
  - [Core Tools (Always Available)](#core-tools-always-available)
  - [Mode-Specific Tools](#mode-specific-tools)
  - [Deprecated Workflow Compatibility](#deprecated-workflow-compatibility)
- [Usage Examples](#usage-examples)
  - [Basic Workflow](#basic-workflow)
  - [Advanced Features](#advanced-features)
  - [Using with MCP Inspector](#using-with-mcp-inspector)
- [Architecture](#architecture)
- [Configuration](#configuration)
  - [Environment variables](#environment-variables)
  - [Tool Surface Profiles (config.yaml)](#tool-surface-profiles-configyaml)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

</details>

## Overview

EnergyPlus MCP Server makes EnergyPlus building energy simulation accessible to AI assistants and automation tools through the Model Context Protocol.

**Key Features:**
- 🏗️ **Complete Model Lifecycle**: Load, validate, analyze, modify, and simulate IDF files
- 🔍 **Deep Building Analysis**: Extract detailed information about zones, surfaces, materials, and schedules
- 🚀 **Automated Simulation**: Execute EnergyPlus simulations with weather files
- 📊 **Advanced Visualization**: Create interactive plots and HVAC system diagrams
- 🔧 **HVAC Intelligence**: Discover, analyze, and visualize HVAC system topology
- 📈 **Smart Output Management**: Auto-discover and configure output variables/meters

## Installation

### Using the MCP Server

**Prerequisites (all clients):**
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (macOS / Windows) or Docker Engine (Linux), running
- `git` on your PATH
- The `energyplus-mcp-dev` image built locally (step 1 below — do this once)
- Check out the revision whose tool-surface contract you intend to deploy.

Choose the appropriate setup for your AI assistant or IDE:

#### Claude Desktop

1. **Build the Docker image** (one-time setup):
   ```bash
   git clone https://github.com/LBNL-ETA/EnergyPlus-MCP.git
   cd EnergyPlus-MCP
   docker build -t energyplus-mcp-dev -f .devcontainer/Dockerfile .devcontainer
   ```

2. **Locate the Claude Desktop config file** for your OS:
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
   - **Linux**: Claude Desktop is not officially supported on Linux. If you use a community build, check its docs for the config path (commonly `~/.config/Claude/claude_desktop_config.json`).

   Create the file if it does not exist, then add:
   ```json
   {
     "mcpServers": {
       "energyplus": {              // Server name shown in Claude Desktop
         "command": "docker",         // Main command to execute
         "args": [
           "run",                     // Docker subcommand to run a container
           "--rm",                    // Remove container after it exits (cleanup)
           "-i",                      // Interactive mode for stdio communication
           "-v", "/path/to/EnergyPlus-MCP:/workspace",  // Mount local dir to container
           "-w", "/workspace/energyplus-mcp-server",    // Working dir in container
           "energyplus-mcp-dev",      // Docker image name we built
           "uv", "run", "python", "-m", "energyplus_mcp_server.server"  // Server startup command
         ]
       }
     }
   }
   ```

   **Important**:
   - Replace `/path/to/EnergyPlus-MCP` with the absolute path to your cloned repo.
     - macOS/Linux example: `/Users/yourname/code/EnergyPlus-MCP`
     - Windows example: `C:\\Users\\yourname\\code\\EnergyPlus-MCP` (use double backslashes in JSON)
   - Remove all comments (text after `//`) when saving — JSON does not support comments.

3. **Restart Claude Desktop**. The EnergyPlus server should appear in the MCP servers panel.

4. **Verify**: in a new chat, ask *"List the EnergyPlus MCP tools you have access to."* With the default `domains` profile you should see the domain managers (`envelope_manager`, `hvac_manager`, `internal_load_manager`, …) plus core tools (`model_preflight`, `model_upgrade`, `simulation_manager`, `idf_modification`, `file_utils`, `post_processing`, `server_manager`).

#### Codex

Codex supports local (stdio) MCP servers through its built-in *Connect to a custom MCP* dialog — no JSON editing required.

1. **Build the Docker image** (same as Claude Desktop step 1 above).

2. **Open the custom MCP dialog** in Codex (*Settings → MCP servers → Connect to a custom MCP*) and fill in:

   | Field | Value |
   |---|---|
   | **Name** | `energyplus` |
   | **Transport** | *STDIO* (the default tab) |
   | **Command to launch** | `docker` |
   | **Arguments** | Add each token as a **separate** entry via *Add argument* (see list below). Do not paste them as a single string. |
   | **Environment variables** | *(leave empty)* |
   | **Environment variable passthrough** | *(leave empty)* |
   | **Working directory** | *(leave empty — Docker sets cwd via `-w`)* |

   **Arguments**, one per entry, in order:
   ```
   run
   --rm
   -i
   -v
   /path/to/EnergyPlus-MCP:/workspace
   -w
   /workspace/energyplus-mcp-server
   energyplus-mcp-dev
   uv
   run
   python
   -m
   energyplus_mcp_server.server
   ```

   Replace `/path/to/EnergyPlus-MCP` with the absolute path to your cloned repo.
   - macOS/Linux example: `/Users/yourname/code/EnergyPlus-MCP`
   - Windows example: `C:\Users\yourname\code\EnergyPlus-MCP` *(single backslashes are fine here — this is a form field, not JSON)*

3. Click **Save**, then restart any active Codex session so the new server is picked up.

4. **Verify**: ask Codex *"What EnergyPlus tools are available?"* — you should see the domain managers (`envelope_manager`, `hvac_manager`, …) and core tools. Same "flat-list → wrong branch" check as above applies.

> **Codex CLI users**: the terminal Codex reads MCP servers from `~/.codex/config.toml` instead of the UI:
> ```toml
> [mcp_servers.energyplus]
> command = "docker"
> args = [
>   "run", "--rm", "-i",
>   "-v", "/path/to/EnergyPlus-MCP:/workspace",
>   "-w", "/workspace/energyplus-mcp-server",
>   "energyplus-mcp-dev",
>   "uv", "run", "python", "-m", "energyplus_mcp_server.server",
> ]
> ```
> Windows users: escape backslashes in TOML strings (`"C:\\Users\\yourname\\code\\EnergyPlus-MCP:/workspace"`).

#### VS Code

VS Code 1.102+ ships native MCP support. Config goes in `.vscode/mcp.json` at the workspace root (or in user settings under `"mcp"`).

1. **Build the Docker image** (same as Claude Desktop step 1 above).

2. **Create `.vscode/mcp.json`** in your project:
   ```json
   {
     "servers": {
       "energyplus": {              // Server name shown in VS Code
         "command": "docker",         // Main command to execute
         "args": [
           "run",                     // Docker subcommand to run a container
           "--rm",                    // Remove container after it exits (cleanup)
           "-i",                      // Interactive mode for stdio communication
           "-v", "${workspaceFolder}:/workspace",       // Mount workspace to container
           "-w", "/workspace/energyplus-mcp-server",    // Working dir in container
           "energyplus-mcp-dev",      // Docker image name we built
           "uv", "run", "python", "-m", "energyplus_mcp_server.server"  // Server startup command
         ]
       }
     }
   }
   ```

   **Important**: Remove all comments (text after `//`) when saving — JSON does not support comments.

3. **Reload VS Code** (`Ctrl/Cmd+Shift+P` → *Developer: Reload Window*). Open the Chat view and confirm the `energyplus` MCP server shows as *Running*.

4. **Verify**: ask the chat *"What EnergyPlus tools are available?"* — you should see the domain managers and core tools listed above.

#### Cursor

1. **Build the Docker image** (same as Claude Desktop step 1 above).

2. **Locate the Cursor MCP config file** for your OS:
   - **macOS/Linux**: `~/.cursor/mcp.json`
   - **Windows**: `%USERPROFILE%\.cursor\mcp.json`

   Create the file if it does not exist, then add:
   ```json
   {
     "mcpServers": {
       "energyplus": {              // Server name shown in Cursor
         "command": "docker",         // Main command to execute
         "args": [
           "run",                     // Docker subcommand to run a container
           "--rm",                    // Remove container after it exits (cleanup)
           "-i",                      // Interactive mode for stdio communication
           "-v", "/path/to/EnergyPlus-MCP:/workspace",  // Mount local dir to container
           "-w", "/workspace/energyplus-mcp-server",    // Working dir in container
           "energyplus-mcp-dev",      // Docker image name we built
           "uv", "run", "python", "-m", "energyplus_mcp_server.server"  // Server startup command
         ]
       }
     }
   }
   ```

   **Important**:
   - Replace `/path/to/EnergyPlus-MCP` with the absolute path to your cloned repo (Windows users: use double backslashes in JSON, e.g. `C:\\Users\\yourname\\code\\EnergyPlus-MCP`).
   - Remove all comments (text after `//`) when saving — JSON does not support comments.

3. **Restart Cursor**. Open *Settings → MCP* and confirm the `energyplus` server is listed as connected.

4. **Verify**: ask Cursor chat *"What EnergyPlus tools are available?"* — you should see the domain managers and core tools listed above.

### Development Setup

For contributors who want to modify or extend the MCP server:

#### VS Code Dev Container

The easiest development setup with all dependencies pre-configured.

**Prerequisites:**
- [Visual Studio Code](https://code.visualstudio.com/)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)

**Steps:**
1. Clone and open in VS Code:
   ```bash
   git clone -b agentic-bem https://github.com/LBNL-ETA/EnergyPlus-MCP.git
   cd EnergyPlus-MCP
   code .
   ```

2. Click "Reopen in Container" when prompted (or press `Ctrl+Shift+P` → "Dev Containers: Reopen in Container")

3. The container automatically installs EnergyPlus 26.1.0 and all dependencies (to pin a different version, see [below](#building-against-a-different-energyplus-version))

#### Docker Setup

For direct Docker development without VS Code:

```bash
# Clone repository
git clone -b agentic-bem https://github.com/LBNL-ETA/EnergyPlus-MCP.git
cd EnergyPlus-MCP

# Build container
docker build -t energyplus-mcp-dev -f .devcontainer/Dockerfile .devcontainer

# Run container
docker run -it --rm -v "$(pwd)":/workspace -w /workspace/energyplus-mcp-server energyplus-mcp-dev bash

# Inside container, install dependencies
uv sync --extra dev
```

#### Local Development

For local development (requires EnergyPlus installation):

**Prerequisites:**
- Python 3.10+
- [uv package manager](https://github.com/astral-sh/uv)
- [EnergyPlus 26.1.0](https://github.com/NREL/EnergyPlus/releases/tag/v26.1.0) (or pin a different version — see [below](#building-against-a-different-energyplus-version))

```bash
# Clone and install
git clone -b agentic-bem https://github.com/LBNL-ETA/EnergyPlus-MCP.git
cd EnergyPlus-MCP/energyplus-mcp-server
uv sync --extra dev

# Run server for testing
uv run python -m energyplus_mcp_server.server
```

#### Streamable HTTP Transport (Local Testing)

By default the server runs over **stdio**, which is what every MCP client config in this README uses. The server can also run as a token-authenticated **streamable HTTP** service — useful for testing remote-style deployments, smoke-testing with `curl`, or connecting clients that expect an HTTP MCP endpoint.

**Prerequisites — pick one path:**

- **Docker (recommended; no local EnergyPlus install needed)**: build the `energyplus-mcp-dev` image once (per [Docker Setup](#docker-setup) above). The image ships with EnergyPlus 26.1.0 and all Python deps pre-installed.
- **Local Development**: follow [Local Development](#local-development) above — Python 3.10+, `uv`, and a local EnergyPlus install. HTTP mode pulls in `uvicorn` and `python-dotenv`, which are declared in `pyproject.toml` — `uv sync --extra dev` will install them.

**1. Generate a bearer token.** Tokens must be at least 32 characters:

```bash
openssl rand -hex 32
```

**2. Create `.env` in `energyplus-mcp-server/`** (gitignored). Copy from [.env.example](energyplus-mcp-server/.env.example) and fill in your values:

```bash
# EPLUS_IDD_PATH — ONLY set this for the Local variant.
# Leave it commented out / unset when using the Docker variant; the image has
# EnergyPlus 26.1.0 baked in and auto-detects it. Setting a host path
# (e.g. /Applications/...) inside the container will override the in-container
# install and crash the server with "IDD file not found".
# EPLUS_IDD_PATH=/Applications/EnergyPlus-26-1-0/Energy+.idd

MCP_TRANSPORT=streamable-http
MCP_HTTP_HOST=0.0.0.0
MCP_HTTP_PORT=8000
MCP_HTTP_PATH=/mcp

# JSON array. Required when MCP_TRANSPORT=streamable-http.
MCP_TOKENS=[{"label":"local-dev","token":"<paste-32+-char-hex-here>"}]
```

`MCP_TOKENS` is strict (parsed in [config.py](energyplus-mcp-server/energyplus_mcp_server/config.py)):

- JSON array of `{"label": "...", "token": "..."}` objects
- `label` matches `[a-z0-9_-]{1,32}` (lowercase only)
- `token` is at least 32 characters
- Labels and tokens must be unique within the array
- An empty list while `MCP_TRANSPORT=streamable-http` causes the server to refuse to start (fail-closed)

**3. Start the server.** Pick the variant that matches your setup:

*Docker (recommended):* publish the port, mount the repo, and let the container pick up `.env` via `--env-file`. Run from the **repo root**:

```bash
docker run --rm \
  -p 8000:8000 \
  -v "$(pwd)":/workspace \
  -w /workspace/energyplus-mcp-server \
  --env-file energyplus-mcp-server/.env \
  energyplus-mcp-dev \
  uv run python -m energyplus_mcp_server.server
```

> **Note**: `uv run python -m ...` outside `docker run` executes Python on your **host**, not in the container — even if the dev image is built. The container is only used when you actually invoke `docker run`. That's why the Local variant below requires a host-side EnergyPlus install.
>
> For the Docker command above, make sure `EPLUS_IDD_PATH` is **unset / commented out** in `.env` (see the note in step 2). `--env-file` forwards every uncommented line into the container, and a host-side `/Applications/...` path inside the container will override the image's auto-detected install and crash startup.

*Local:* (requires a host EnergyPlus install matching whatever `EPLUS_IDD_PATH` is set to in `.env`)

```bash
cd energyplus-mcp-server
uv run python -m energyplus_mcp_server.server
```

Either way you should see a log line like `Listening on http://0.0.0.0:8000 (path=/mcp, 1 tokens)`.

**4. Smoke-test with curl.** The server exposes two endpoints:

```bash
# Health check — no auth required, useful for confirming the server is up
curl -s http://localhost:8000/health
# → {"status":"ok"}

# Unauthenticated MCP request — should return 401
curl -i -X POST http://localhost:8000/mcp

# Authenticated initialize handshake
TOKEN=<paste-your-token>
curl -i -X POST http://localhost:8000/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```

**5. Connect MCP Inspector.** Run the Inspector and point it at `http://localhost:8000/mcp` with transport `Streamable HTTP` and an `Authorization: Bearer <your-token>` header.

**6. Connect an MCP client.** Replace the stdio command stanza in your client config with an HTTP one:

```json
{
  "mcpServers": {
    "energyplus": {
      "type": "http",
      "url": "http://localhost:8000/mcp",
      "headers": { "Authorization": "Bearer <your-token>" }
    }
  }
}
```

**Common pitfalls:**

- **`RuntimeError: IDD file not found at: /Applications/...`** when using Docker — `EPLUS_IDD_PATH` in `.env` is set to a host path and `--env-file` forwarded it into the container, overriding the image's auto-detected install. Comment out the `EPLUS_IDD_PATH` line in `.env` (or set it to the in-container path `/app/software/EnergyPlusV26-1-0/Energy+.idd`).
- **`streamable-http transport requires non-empty MCP_TOKENS`** — `MCP_TOKENS` is empty or unset. Generate a token and add it to `.env`.
- **JSON quoting in shells** — if you `export MCP_TOKENS=...` in zsh/bash instead of using `.env`, wrap the value in single quotes so the inner `"` characters survive.
- **Port conflict on 8000** — set `MCP_HTTP_PORT=8001` in `.env` (the Cloud Run-style `PORT` env var is also honored).
- **421 "Invalid Host header"** — `mcp>=1.10` ships DNS rebinding protection that rejects unrecognized Host headers. The server disables it by default for HTTP-behind-auth use cases. To re-enable with an allowlist, set `MCP_ALLOWED_HOSTS=host1.example.com,host2.example.com`.
- **Tests** — transport and auth behavior is covered by `tests/test_config_transport.py` and `tests/test_auth.py`. Run with `uv run pytest tests/test_config_transport.py tests/test_auth.py`.

#### Building against a different EnergyPlus version

The Docker image bakes EnergyPlus **26.1.0** in by default. To pin a different release, override the build args below when building the image. You'll need:

- `EPLUS_VER`: release version, e.g. `25.1.0`
- `EPLUS_HASH`: the short commit string NREL embeds in the release tarball filename. Find it by looking at any asset on the release page — e.g. for [v25.1.0](https://github.com/NREL/EnergyPlus/releases/tag/v25.1.0) the tarball `EnergyPlus-25.1.0-68a4a7c774-Linux-Ubuntu22.04-x86_64.tar.gz` gives `EPLUS_HASH=68a4a7c774`.
- `EPLUS_PREFIX`: install path inside the container. Must match `/app/software/EnergyPlusV<major>-<minor>-<patch>` (hyphens, not dots).
- `EPLUS_DIST_SUFFIX`: Ubuntu distro tag. Use `Ubuntu22.04` for EnergyPlus ≤ 25.1.0; `Ubuntu24.04` for ≥ 26.1.0 (NREL stopped shipping 22.04 builds from 26.1.0 onward).

**Example — rebuild against 25.1.0:**
```bash
docker build \
  --build-arg EPLUS_VER=25.1.0 \
  --build-arg EPLUS_HASH=68a4a7c774 \
  --build-arg EPLUS_PREFIX=/app/software/EnergyPlusV25-1-0 \
  --build-arg EPLUS_DIST_SUFFIX=Ubuntu22.04 \
  -t energyplus-mcp-dev \
  -f .devcontainer/Dockerfile .devcontainer
```

**Heads up — three other places reference the install path** (`/app/software/EnergyPlusV26-1-0`) and don't read the Dockerfile ARG, so if you override `EPLUS_PREFIX` you'll also need to update:

- `energyplus-mcp-server/energyplus_mcp_server/config.py` — `version` and `default_installation`
- `energyplus-mcp-server/.vscode/mcp.json` — the two `EnergyPlusV26-1-0` strings
- The client config JSON you created for Claude Desktop / Codex / VS Code / Cursor — only if it sets `EPLUS_IDD_PATH` explicitly; otherwise `config.py`'s update is enough.

Alternatively, set `EPLUS_IDD_PATH` to the new install location in your client config's `env` block — `config.py` will derive everything else from it.

## Available Tools

### Tool Registration Modes

The `mode` field in `config.yaml` controls how tools are organized and registered at startup:

- **`domains`** (default): Tools organized by building domain - separate managers for envelope, internal loads, HVAC, and outputs. Best for domain-specific workflows.
- **`masters`**: Unified tools that combine multiple operations - fewer tools with action/focus parameters. Best for reducing tool clutter.
- **`hybrid`**: Both approaches available simultaneously.

**Important:** MCP clients only see tools registered at startup. Change the mode in `config.yaml` before starting the server.

### Core Tools (Always Available)
- `model_preflight` — Load, validate, info, resolve_paths, readiness (preflight)
- `model_upgrade` — Read-only transition planning and copy-only one-model IDF upgrades
- `simulation_manager` — Run/update simulations, status
- `idf_modification` — Direct IDD-validated object changes when no semantic domain operation exists
- `file_utils` — List and copy sample/weather files
- `post_processing` — Interactive plots
- `server_manager` — Status, logs, clear logs

### Mode-Specific Tools

#### When `mode: masters` - Unified Tools
- `inspect_model` - Inspect model with focus parameter (zones, surfaces, materials, people, lights, etc.)
- `modify_basic_parameters` - Modify various parameters through a single tool
- `hvac_loop_inspect` - HVAC analysis with actions (discover, topology, visualize)
- `get_outputs` - Get output variables and meters

#### When `mode: domains` (default) - Domain-Specific Managers
- `envelope_manager` — Inspect/modify envelope (surfaces, materials, infiltration, window films, coatings)
- `internal_load_manager` — Inspect/modify people, lights, and electric equipment
- `hvac_manager` — Discover, analyze topology, and visualize HVAC loops
- `outputs_manager` — List or add output variables/meters with discovery
- `geometry_manager` — Extract, summarize, and visualize model geometry

The three modeling managers also expose workflow-neutral semantic parameter
operations. `internal_load_manager` owns LPD, EPD, and occupancy density;
`envelope_manager` owns infiltration, window U-factor, and window SHGC; and
`hvac_manager` owns cooling COP, heating efficiency, and fan efficiency. Each
uses the same actions: `parameter_capabilities`, `inspect_parameter`,
`adjust_percentage`, and `set_parameter`.

### Deprecated Workflow Compatibility

`calibration_manager` and `retrofit_manager` are no longer part of the default
surface. Existing consumers can temporarily enable both deprecated façades
with `tool_surface.compatibility.workflow_managers: true` or
`MCP_ENABLE_WORKFLOW_COMPATIBILITY=true`. They delegate to the same generic
domain implementation and are not separate operation stacks. See the
[tool-surface migration guide](docs/tool-surface-migration.md).

The historical `enable_wrappers` setting and `MCP_EXPOSE_*_WRAPPERS` variables
were documented but never implemented. Enabling them now fails at startup with
an actionable migration error instead of silently changing nothing.

### Copy-only IDF upgrades

`model_upgrade` is intentionally separate from simulation and calibration. Use
`action: "plan"` to read an IDF Version object and discover the complete local
adjacent transition chain before any write. Use `action: "run"` only with a new
`output_directory`; it stages one copied model plus each official transition
executable, adjacent IDDs, and report-variable mapping CSV there. Existing
output directories and downgrades are refused. The resulting
`migration-manifest.json` records hashes, logs, warnings, and transition state,
with `simulation_validated: false`; it is not a simulation `run_record.json`
and does not establish model equivalence, calibration adoption, or a physical
simulation budget event. The default target is the configured EnergyPlus
runtime; a same-version `run` is an explicit no-op. See
[IDF upgrade details](docs/idf-version-upgrade.md).

### Native-IDF semantic parameter operations

The domain managers support LPD, EPD, OCD, INF, WIN-U, WIN-SHGC, COP, HE,
and FAN without assigning calibration policy to EnergyPlus-MCP.
`adjust_percentage` applies a signed percentage; `inspect_parameter` reports
canonical quantities, units, and target IDs; `set_parameter` applies an
absolute value or target-to-value `assignments` map. Edits use an explicit
input and separate output, enforce physical limits without hidden clipping,
and report model-specific complete/partial/none coverage. Calibration-MCP owns
bounds and bounded-trial recipes. See [absolute setters and bounds](docs/calibration-absolute-setters.md),
[percentage-slice verification](docs/calibration-idf-mvp.md), and the
[migration map](docs/tool-surface-migration.md).

For calibration evidence, opt into the existing synchronous `simulation_manager` with `action: "run"` and `runs_dir`. It creates one unique run directory at `<runs_dir>/<run_id>/`, writes `run_record.json` for each launched success or failure, snapshots the staged input as `in.idf`, and produces monthly `Electricity:Facility` and `NaturalGas:Facility` meters in `run/eplusout.sql`. Normal simulation calls that omit `runs_dir` retain their existing behavior.

The first qualified measured-bill SF pilot is documented in
[SF native-IDF calibration pilot](docs/sf-native-idf-calibration-pilot.md).
Building 69 completed 81 distinct EnergyPlus 26.1 simulations on the explicit
2019 calendar and produced a formal terminal report. Six sweeps improved the
score, but the result did not converge; missing schedule, thermostat,
outdoor-air/economizer, occupancy-ratio, and service-hot-water semantics remain
the main coverage gap. Treat this as end-to-end integration proof, not as proof
that the current parameter surface can calibrate every SF model.

## Usage Examples

### Basic Workflow

1. **Preflight: Load a model**:
   ```json
   {
     "tool": "model_preflight",
     "arguments": {
       "action": "load",
       "idf_path": "sample_files/1ZoneUncontrolled.idf"
     }
   }
   ```

2. **Inspect geometry and zones**:
   ```json
   {
     "tool": "geometry_manager",
     "arguments": {
       "action": "extract_and_summary",
       "idf_path": "sample_files/1ZoneUncontrolled.idf"
     }
   }
   ```

3. **Run simulation**:
   ```json
   {
     "tool": "simulation_manager",
     "arguments": {
       "action": "run",
       "idf_path": "sample_files/1ZoneUncontrolled.idf",
       "weather_file": "sample_files/USA_CA_San.Francisco.Intl.AP.724940_TMY3.epw",
       "annual": true
     }
   }
   ```

4. **Create visualization**:
   ```json
   {
     "tool": "post_processing",
     "arguments": {
       "action": "interactive_plot",
       "output_directory": "outputs/1ZoneUncontrolled",
       "file_type": "variable"
     }
   }
   ```

5. **Parse simulation errors** (if simulation fails):
   ```json
   {
     "tool": "post_processing",
     "arguments": {
       "action": "parse_errors",
       "err_file_path": "outputs/1ZoneUncontrolled/1ZoneUncontrolled.err"
     }
   }
   ```
   Returns structured error analysis with severity levels, affected objects, and root cause analysis.

### Advanced Features

**HVAC System Analysis (discover + visualize)**:
```json
{
  "tool": "hvac_loop_inspect",
  "arguments": {
    "action": "discover",
    "idf_path": "sample_files/5ZoneAirCooled.idf",
    "types": "all"
  }
}
```

```json
{
  "tool": "hvac_loop_inspect",
  "arguments": {
    "action": "visualize",
    "idf_path": "sample_files/5ZoneAirCooled.idf",
    "loop_name": "VAV Sys 1",
    "image_format": "png"
  }
}
```

**Preflight: Readiness check**
```json
{
  "tool": "model_preflight",
  "arguments": {
    "action": "readiness",
    "idf_path": "sample_files/5ZoneAirCooled.idf",
    "weather_file": "sample_files/USA_CA_San.Francisco.Intl.AP.724940_TMY3.epw"
  }
}
```

**Discover Outputs (variables/meters)**:
```json
{
  "tool": "get_outputs",
  "arguments": {
    "idf_path": "sample_files/5ZoneAirCooled.idf",
    "type": "both",
    "discover_available": true,
    "run_days": 1
  }
}
```

**File Utilities: List**
```json
{
  "tool": "file_utils",
  "arguments": {
    "action": "list",
    "include_example_files": false,
    "include_weather_data": true,
    "extensions": [".idf", ".epw"],
    "limit": 50
  }
}
```

**File Utilities: Copy (dry-run)**
```json
{
  "tool": "file_utils",
  "arguments": {
    "action": "copy",
    "source_path": "5ZoneAirCooled.idf",
    "target_path": "outputs/5ZoneAirCooled_copy.idf",
    "file_types": [".idf"],
    "mode": "dry_run"
  }
}
```

**Housekeeping: Status**
```json
{
  "tool": "server_manager",
  "arguments": { "action": "status" }
}
```

**Housekeeping: Error Logs (raw)**
```json
{
  "tool": "server_manager",
  "arguments": { "action": "logs", "type": "error", "lines": 100, "format": "raw" }
}
```

**Housekeeping: Rotate Logs (dry-run)**
```json
{
  "tool": "server_manager",
  "arguments": { "action": "clear_logs", "mode": "dry_run" }
}
```

**Model Summary via Aggregator**:
```json
{
  "tool": "inspect_model",
  "arguments": {
    "idf_path": "sample_files/5ZoneAirCooled.idf",
    "focus": ["summary"]
  }
}
```

**Modify Basic Parameters (dry-run plan)**:
```json
{
  "tool": "modify_basic_parameters",
  "arguments": {
    "idf_path": "sample_files/5ZoneAirCooled.idf",
    "mode": "dry_run",
    "operations": [
      { "op": "people.update", "params": { "modifications": [{"target": "all", "field_updates": {"Number_of_People": 10}}] } },
      { "op": "envelope.add_window_film", "params": { "u_value": 4.94, "shgc": 0.45, "visible_transmittance": 0.66 } }
    ]
  }
}
```

**Discover Modifiable Parameters (capabilities)**:
```json
{
  "tool": "modify_basic_parameters",
  "arguments": {
    "idf_path": "sample_files/5ZoneAirCooled.idf",
    "capabilities": true,
    "detail": "summary"
  }
}
```

### Using with MCP Inspector

Test tools interactively (requires Node.js 18+):

```bash
# From the repo root, run the server inside the dev image under the Inspector
npx @modelcontextprotocol/inspector \
  docker run --rm -i \
    -v "$(pwd):/workspace" \
    -w /workspace/energyplus-mcp-server \
    energyplus-mcp-dev \
    uv run python -m energyplus_mcp_server.server
```

Or with a local dev environment (see [Local Development](#local-development)):
```bash
cd energyplus-mcp-server
npx @modelcontextprotocol/inspector uv run python -m energyplus_mcp_server.server
```

The Inspector opens a browser UI where you can list registered tools and invoke them with JSON arguments — useful for confirming the active `tool_surface.mode` matches what you expect before wiring up a client.

**HVAC Loops: Discover**
```json
{
  "tool": "hvac_loop_inspect",
  "arguments": {
    "action": "discover",
    "idf_path": "sample_files/5ZoneAirCooled.idf",
    "types": "all"
  }
}
```

**HVAC Loops: Topology**
```json
{
  "tool": "hvac_loop_inspect",
  "arguments": {
    "action": "topology",
    "idf_path": "sample_files/5ZoneAirCooled.idf",
    "loop_name": "VAV Sys 1",
    "detail": "detailed"
  }
}
```

## Architecture

The server follows a layered architecture:

```
┌─────────────────────────┐
│   MCP Protocol Layer    │  FastMCP server handling client communications
├─────────────────────────┤
│     Tools Layer         │  Master tools + domain managers (registered per config)
├─────────────────────────┤
│  Orchestration Layer    │  EnergyPlus Manager & Config Module
├─────────────────────────┤
│  EnergyPlus Integration │  Direct interface to simulation engine
└─────────────────────────┘
```

**Project Structure:**
```
energyplus-mcp-server/
├── config.yaml                  # Tool-surface config (mode, per-domain toggles)
├── energyplus_mcp_server/
│   ├── server.py                # Lean bootstrap: loads config, delegates registration
│   ├── energyplus_tools.py      # Core EnergyPlus integration (EnergyPlusManager)
│   ├── config.py                # Configuration management
│   ├── domains/                 # Domain managers (envelope, HVAC, internal loads, outputs, geometry)
│   ├── tools/                   # Master / core tools (inspect, modify, simulation, preflight, files, post, server)
│   └── utils/                   # Specialized utilities (idf_modifier, geometry, plots, …)
├── sample_files/                # Sample IDF and weather files
├── tests/                       # Unit tests
└── pyproject.toml               # Dependencies
```

## Configuration

The server auto-detects EnergyPlus installation and uses sensible defaults.

### Environment variables

- `EPLUS_IDD_PATH`: Path to EnergyPlus IDD file
- `EPLUS_SAMPLE_PATH`: Custom sample files directory
- `EPLUS_OUTPUT_PATH`: Output directory for results
- `MCP_CONFIG_PATH`: Override path to `config.yaml` (default: `energyplus-mcp-server/config.yaml`)
- `MCP_EXPOSE_MASTERS`, `MCP_EXPOSE_DOMAIN_MANAGERS`: mode controls when no YAML mode is supplied
- `MCP_ENABLE_WORKFLOW_COMPATIBILITY`: opt in to deprecated workflow-manager aliases

### Tool Surface Profiles (config.yaml)

You can control how tools are presented via `config.yaml`. The server reads this on startup to decide which tool groups to register. **A restart is required after edits** — MCP clients only see tools registered at startup.

- Location: `energyplus-mcp-server/config.yaml` (checked first), or the path in `MCP_CONFIG_PATH`.
- Parser: requires `pyyaml` (included in dependencies); invalid configuration fails closed.
- Precedence: YAML, when present, overrides the `MCP_EXPOSE_MASTERS` / `MCP_EXPOSE_DOMAIN_MANAGERS` env flags for mode selection.

Schema (minimal):
```yaml
tool_surface:
  mode: masters | domains | hybrid
  domains:                        # optional fine-grained controls
    envelope: true | false
    internal_loads: true | false
    hvac: true | false
    outputs: true | false
    geometry: true | false
  compatibility:
    workflow_managers: false      # deprecated calibration/retrofit façades
```

**Profiles:**

Masters-only (fewer, unified tools):
```yaml
tool_surface:
  mode: masters
```

Domains-only (default on `agentic-bem`; one manager per building domain):
```yaml
tool_surface:
  mode: domains
  domains:
    envelope: true
    internal_loads: true
    hvac: true
    outputs: true
    geometry: true
  compatibility:
    workflow_managers: false
```

Hybrid (expose both surfaces simultaneously):
```yaml
tool_surface:
  mode: hybrid
  domains:
    outputs: true
```

## Troubleshooting

**Common Issues:**

1. **"IDD file not found"**: Ensure EnergyPlus is installed
2. **"Module not found"**: Run `uv sync` to install dependencies
3. **"Permission denied"**: Check file permissions
4. **"Simulation failed"**: Check EnergyPlus error messages in output directory

**Debugging (use the `server_manager` tool with an `action`):**
- Check server status: `{"tool": "server_manager", "arguments": {"action": "status"}}`
- View logs: `{"tool": "server_manager", "arguments": {"action": "logs", "type": "all", "lines": 200}}`
- Check errors: `{"tool": "server_manager", "arguments": {"action": "logs", "type": "error", "lines": 100, "format": "raw"}}`

Use `server_manager` for status and logs. Historical per-function wrapper flags
were never implemented and are deliberately rejected; see the migration guide.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Run checks:
   ```bash
   uv run ruff check
   uv run black .
   uv run pytest
   ```
5. Submit a pull request

## License

See [LICENSE](License.txt) file for details.
