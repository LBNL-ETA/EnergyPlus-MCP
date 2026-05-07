# EnergyPlus MCP Server

A Model Context Protocol (MCP) server that provides **35 comprehensive tools** for working with EnergyPlus building energy simulation models. This server enables AI assistants and other MCP clients to load, validate, modify, and analyze EnergyPlus IDF files through a standardized interface.

> **Version**: 0.1.0  
> **EnergyPlus Compatibility**: 26.1.0 (default; see [Building against a different EnergyPlus version](#building-against-a-different-energyplus-version))  
> **Python**: 3.10+

<details open>
<summary><h2>📑 Table of Contents</h2></summary>

- [Overview](#overview)
- [Installation](#installation)
  - [Using the MCP Server](#using-the-mcp-server)
    - [Claude Desktop](#claude-desktop)
    - [VS Code](#vs-code)
    - [Cursor](#cursor)
  - [Development Setup](#development-setup)
    - [VS Code Dev Container](#vs-code-dev-container)
    - [Docker Setup](#docker-setup)
    - [Local Development](#local-development)
    - [Streamable HTTP Transport (Local Testing)](#streamable-http-transport-local-testing)
    - [Building against a different EnergyPlus version](#building-against-a-different-energyplus-version)
- [Available Tools](#available-tools)
- [Usage Examples](#usage-examples)
- [Architecture](#architecture)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [Cite this work](#cite-this-work)
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
   - Remove all comments (text after `//`) when adding to the actual config file, as JSON doesn't support comments.

3. **Restart Claude Desktop**. The EnergyPlus server should appear in the MCP servers panel.

4. **Verify**: in a new chat, ask *"List the EnergyPlus MCP tools you have access to."* You should see tools like `load_idf_model`, `run_energyplus_simulation`, `get_server_status`. If not, check [Troubleshooting](#troubleshooting).

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

4. **Verify**: ask the chat *"What EnergyPlus tools are available?"* — you should see the tool list.

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

4. **Verify**: ask Cursor chat *"What EnergyPlus tools are available?"* — you should see the tool list.

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
   git clone https://github.com/LBNL-ETA/EnergyPlus-MCP.git
   cd EnergyPlus-MCP
   code .
   ```

2. Click "Reopen in Container" when prompted (or press `Ctrl+Shift+P` → "Dev Containers: Reopen in Container")

3. The container automatically installs EnergyPlus 26.1.0 and all dependencies (to pin a different version, see [Building against a different EnergyPlus version](#building-against-a-different-energyplus-version))

#### Docker Setup

For direct Docker development without VS Code:

```bash
# Clone repository
git clone https://github.com/LBNL-ETA/EnergyPlus-MCP.git
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
- [EnergyPlus 26.1.0](https://github.com/NREL/EnergyPlus/releases/tag/v26.1.0) (or pin a different version — see [Building against a different EnergyPlus version](#building-against-a-different-energyplus-version))

```bash
# Clone and install
git clone https://github.com/LBNL-ETA/EnergyPlus-MCP.git
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
- The client config JSON you created for Claude Desktop / VS Code / Cursor — only if it sets `EPLUS_IDD_PATH` explicitly; otherwise `config.py`'s update is enough.

Alternatively, set `EPLUS_IDD_PATH` to the new install location in your client config's `env` block — `config.py` will derive everything else from it.

## Available Tools

The server provides **35 tools** organized into **5 categories**:

### 🗂️ Model Config & Loading (9 tools)
- `load_idf_model` - Load and validate IDF files
- `validate_idf` - Comprehensive model validation
- `list_available_files` - Browse sample files and weather data
- `copy_file` - Intelligent file copying with path resolution
- `get_model_summary` - Extract basic model information
- `check_simulation_settings` - Review simulation control settings
- `modify_simulation_control` - Modify simulation parameters
- `modify_run_period` - Adjust simulation time periods
- `get_server_configuration` - Get server configuration info

### 🔍 Model Inspection (9 tools)
- `list_zones` - List all thermal zones with properties
- `get_surfaces` - Get building surface information
- `get_materials` - Extract material definitions
- `inspect_schedules` - Analyze all schedule objects
- `inspect_people` - Analyze occupancy settings
- `inspect_lights` - Analyze lighting loads
- `inspect_electric_equipment` - Analyze equipment loads
- `get_output_variables` - Get/discover output variables
- `get_output_meters` - Get/discover energy meters

### ⚙️ Model Modification (8 tools)
- `modify_people` - Update occupancy settings
- `modify_lights` - Update lighting loads
- `modify_electric_equipment` - Update equipment loads
- `change_infiltration_by_mult` - Modify infiltration rates
- `add_window_film_outside` - Add window films
- `add_coating_outside` - Apply surface coatings
- `add_output_variables` - Add output variables
- `add_output_meters` - Add energy meters

### 🚀 Simulation & Results (4 tools)
- `run_energyplus_simulation` - Execute simulations
- `create_interactive_plot` - Generate HTML visualizations
- `discover_hvac_loops` - Find all HVAC loops
- `get_loop_topology` - Get HVAC loop details

### 🖥️ Server Management (5 tools)
- `visualize_loop_diagram` - Generate HVAC diagrams
- `get_server_status` - Check server health
- `get_server_logs` - View recent logs
- `get_error_logs` - Get error logs
- `clear_logs` - Clear/rotate log files

## Usage Examples

### Basic Workflow

1. **Load a model**:
   ```json
   {
     "tool": "load_idf_model",
     "arguments": {
       "idf_path": "sample_files/1ZoneUncontrolled.idf"
     }
   }
   ```

2. **Inspect zones**:
   ```json
   {
     "tool": "list_zones",
     "arguments": {
       "idf_path": "sample_files/1ZoneUncontrolled.idf"
     }
   }
   ```

3. **Run simulation**:
   ```json
   {
     "tool": "run_energyplus_simulation",
     "arguments": {
       "idf_path": "sample_files/1ZoneUncontrolled.idf",
       "weather_file": "sample_files/USA_CA_San.Francisco.Intl.AP.724940_TMY3.epw",
       "annual": true
     }
   }
   ```

4. **Create visualization**:
   ```json
   {
     "tool": "create_interactive_plot",
     "arguments": {
       "output_directory": "outputs/1ZoneUncontrolled",
       "file_type": "variable"
     }
   }
   ```

### Advanced Features

**HVAC System Analysis**:
```json
{
  "tool": "discover_hvac_loops",
  "arguments": {
    "idf_path": "sample_files/5ZoneAirCooled.idf"
  }
}
```

**Generate HVAC Diagram**:
```json
{
  "tool": "visualize_loop_diagram",
  "arguments": {
    "idf_path": "sample_files/5ZoneAirCooled.idf",
    "loop_name": "VAV Sys 1",
    "format": "png"
  }
}
```

**Discover Output Variables**:
```json
{
  "tool": "get_output_variables",
  "arguments": {
    "idf_path": "sample_files/5ZoneAirCooled.idf",
    "discover_available": true,
    "run_days": 1
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

Or, if you have a local dev environment (see [Local Development](#local-development)):
```bash
cd energyplus-mcp-server
npx @modelcontextprotocol/inspector uv run python -m energyplus_mcp_server.server
```

The Inspector opens a browser UI where you can list tools and invoke them with JSON arguments — useful for sanity-checking the install before wiring up a client.

## Architecture

The server follows a layered architecture:

```
┌─────────────────────────┐
│   MCP Protocol Layer    │  FastMCP server handling client communications
├─────────────────────────┤
│     Tools Layer         │  35 tools organized into 5 categories
├─────────────────────────┤
│  Orchestration Layer    │  EnergyPlus Manager & Config Module
├─────────────────────────┤
│  EnergyPlus Integration │  Direct interface to simulation engine
└─────────────────────────┘
```

**Project Structure:**
```
energyplus-mcp-server/
├── energyplus_mcp_server/
│   ├── server.py              # FastMCP server with tools
│   ├── energyplus_tools.py    # Core EnergyPlus integration
│   ├── config.py              # Configuration management
│   └── utils/                 # Specialized utilities
├── sample_files/              # Sample IDF and weather files
├── tests/                     # Unit tests
└── pyproject.toml            # Dependencies
```

## Configuration

The server auto-detects EnergyPlus installation and uses sensible defaults. Configuration can be customized via environment variables:

- `EPLUS_IDD_PATH`: Path to EnergyPlus IDD file
- `EPLUS_SAMPLE_PATH`: Custom sample files directory
- `EPLUS_OUTPUT_PATH`: Output directory for results

## Troubleshooting

**Common Issues:**

1. **"IDD file not found"**: Ensure EnergyPlus is installed
2. **"Module not found"**: Run `uv sync` to install dependencies
3. **"Permission denied"**: Check file permissions
4. **"Simulation failed"**: Check EnergyPlus error messages in output directory

**Debugging:**
- Check server status: `get_server_status`
- View logs: `get_server_logs`
- Check errors: `get_error_logs`

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

## Cite this work

If you use EnergyPlus-MCP in your research or project, please cite:

> Han Li, Yujie Xu, Tianzhen Hong, EnergyPlus-MCP: A model-context-protocol server for ai-driven building energy modeling, SoftwareX, Volume 32, 2025, 102367, ISSN 2352-7110, https://doi.org/10.1016/j.softx.2025.102367.

**BibTeX entry:**
```bibtex
@article{li2025energyplus,
  title={EnergyPlus-MCP: A model-context-protocol server for ai-driven building energy modeling},
  author={Li, Han and Xu, Yujie and Hong, Tianzhen},
  journal={SoftwareX},
  volume={32},
  pages={102367},
  year={2025},
  issn={2352-7110},
  doi={10.1016/j.softx.2025.102367},
  url={https://www.sciencedirect.com/science/article/pii/S2352711025003334}
}
```

## License

EnergyPlus Model Context Protocol Server (EnergyPlus-MCP) Copyright (c) 2025, The Regents of the University of California, through Lawrence Berkeley National Laboratory (subject to receipt of any required approvals from the U.S. Dept. of Energy). All rights reserved.

This software is distributed under a modified BSD license. See [License.txt](License.txt) for full license text and [Copyright.txt](Copyright.txt) for the copyright notice.

If you have questions about your rights to use or distribute this software, please contact Berkeley Lab's Intellectual Property Office at IPO@lbl.gov.

**Government Rights Notice**: This Software was developed under funding from the U.S. Department of Energy and the U.S. Government consequently retains certain rights. As such, the U.S. Government has been granted for itself and others acting on its behalf a paid-up, nonexclusive, irrevocable, worldwide license in the Software to reproduce, distribute copies to the public, prepare derivative works, and perform publicly and display publicly, and to permit others to do so.