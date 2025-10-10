# EnergyPlus MCP Server

A Model Context Protocol (MCP) server that provides **35 comprehensive tools** for working with EnergyPlus building energy simulation models. This server enables AI assistants and other MCP clients to load, validate, modify, and analyze EnergyPlus IDF files through a standardized interface.

> **Version**: 0.1.0  
> **EnergyPlus Compatibility**: 25.1.0  
> **Python**: 3.10+

<details open>
<summary><h2>📑 Table of Contents</h2></summary>

- [EnergyPlus MCP Server](#energyplus-mcp-server)
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
- [Available Tools](#available-tools)
    - [Tool Surface Profiles (config.yaml)](#tool-surface-profiles-configyaml)
    - [🔍 Inspection](#-inspection)
    - [⚙️ Modification](#️-modification)
    - [✅ Preflight](#-preflight)
    - [🚀 Simulation](#-simulation)
    - [📊 Post-Processing](#-post-processing)
    - [🗂️ Files](#️-files)
    - [🖥️ Server Management](#️-server-management)
    - [Tool Exposure Flags](#tool-exposure-flags)
  - [Usage Examples](#usage-examples)
    - [Basic Workflow](#basic-workflow)
    - [Advanced Features](#advanced-features)
    - [Using with MCP Inspector](#using-with-mcp-inspector)
  - [Architecture](#architecture)
  - [Configuration](#configuration)
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

Choose the appropriate setup for your AI assistant or IDE:

#### Claude Desktop

1. **Build the Docker image** (one-time setup):
   ```bash
   git clone https://github.com/tsbyq/EnergyPlus_MCP.git
   cd EnergyPlus_MCP/.devcontainer
   docker build -t energyplus-mcp-dev .
   ```

2. **Configure Claude Desktop**:
   
   Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:
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
   - Replace `/path/to/EnergyPlus-MCP` with your actual repository path
   - Remove all comments (text after `//`) when adding to the actual config file, as JSON doesn't support comments

3. **Restart Claude Desktop** and the EnergyPlus server should connect automatically.

#### VS Code

1. **Build the Docker image** (same as Claude Desktop step 1 above)

2. **Configure VS Code**:
   
   Add to `.vscode/settings.json` in your project:
   ```json
   {
     "mcp.servers": {
       "energyplus": {              // Server name shown in VS Code
         "command": "docker",         // Main command to execute  
         "args": [
           "run",                     // Docker subcommand to run a container
           "--rm",                    // Remove container after it exits (cleanup)
           "-i",                      // Interactive mode for stdio communication
           "-v", "${workspaceFolder}:/workspace",      // Mount workspace to container
           "-w", "/workspace/energyplus-mcp-server",    // Working dir in container
           "energyplus-mcp-dev",      // Docker image name we built
           "uv", "run", "python", "-m", "energyplus_mcp_server.server"  // Server startup command
         ]
       }
     }
   }
   ```
   
   **Important**: Remove all comments (text after `//`) when adding to the actual config file

3. **Restart VS Code** for the changes to take effect.

#### Cursor

1. **Build the Docker image** (same as Claude Desktop step 1 above)

2. **Configure Cursor**:
   
   Add to `~/.cursor/mcp.json`:
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
   - Replace `/path/to/EnergyPlus-MCP` with your actual repository path
   - Remove all comments (text after `//`) when adding to the actual config file, as JSON doesn't support comments

3. **Restart Cursor** for the changes to take effect.

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
   git clone https://github.com/tsbyq/EnergyPlus_MCP.git
   cd EnergyPlus_MCP
   code .
   ```

2. Click "Reopen in Container" when prompted (or press `Ctrl+Shift+P` → "Dev Containers: Reopen in Container")

3. The container automatically installs EnergyPlus 25.1.0 and all dependencies

#### Docker Setup

For direct Docker development without VS Code:

```bash
# Clone repository
git clone https://github.com/tsbyq/EnergyPlus_MCP.git
cd EnergyPlus_MCP

# Build container
docker build -t energyplus-mcp-dev -f .devcontainer/Dockerfile .

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
- [EnergyPlus 25.1.0](https://github.com/NREL/EnergyPlus/releases)

```bash
# Clone and install
git clone https://github.com/tsbyq/EnergyPlus_MCP.git
cd EnergyPlus_MCP/energyplus-mcp-server
uv sync --extra dev

# Run server for testing
uv run python -m energyplus_mcp_server.server
```

## Available Tools

### Tool Registration Modes

The `mode` field in `config.yaml` controls how tools are organized and registered at startup:

- **`domains`** (default): Tools organized by building domain - separate managers for envelope, internal loads, HVAC, and outputs. Best for domain-specific workflows.
- **`masters`**: Unified tools that combine multiple operations - fewer tools with action/focus parameters. Best for reducing tool clutter.
- **`hybrid`**: Both approaches available simultaneously.

**Important:** MCP clients only see tools registered at startup. Change the mode in `config.yaml` before starting the server.

### Core Tools (Always Available)
- `model_preflight` — Load, validate, info, resolve_paths, readiness (preflight)
- `simulation_manager` — Run/update simulations, status
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

### Optional Wrapper Tools

- `MCP_EXPOSE_INSPECT_WRAPPERS=true` — Expose individual inspection wrappers (`inspect_people`, `inspect_lights`, `list_zones`, etc.).
- `MCP_EXPOSE_OUTPUT_WRAPPERS=true` — Expose legacy output wrappers (`get_output_variables`, `get_output_meters`).
- `MCP_EXPOSE_SUMMARY_WRAPPER=true` — Expose `get_model_summary` wrapper.
- `MCP_EXPOSE_MODIFY_WRAPPERS=true` — Expose legacy modify wrappers (`modify_people`, `modify_lights`, etc.).
- `MCP_EXPOSE_SERVER_WRAPPERS=true` — Expose legacy server wrappers (`get_server_status`, `get_server_logs`, `get_error_logs`, `clear_logs`).
- `MCP_EXPOSE_HVAC_WRAPPERS=true` — Expose legacy HVAC wrappers (`discover_hvac_loops`, `get_loop_topology`).
- `MCP_EXPOSE_FILE_WRAPPERS=true` — Expose legacy file wrappers (`list_available_files`, `copy_file`).
- `MCP_EXPOSE_SIM_WRAPPERS=true` — Expose simulation wrappers (`run_simulation`, legacy `run_energyplus_simulation`, `modify_simulation_control`, `modify_run_period`).
- `MCP_EXPOSE_MODEL_WRAPPERS=true` — Expose model preflight wrappers (`load_idf_model`, `validate_idf`).
- `MCP_EXPOSE_POST_WRAPPERS=true` — Expose post-processing wrappers (`create_interactive_plot`).
- `MCP_EXPOSE_DOMAIN_MANAGERS=true` — Expose domain manager tools (`envelope_manager`, `internal_load_manager`, `hvac_manager`).
  - Controlled via YAML too: `tool_surface.mode: domains|hybrid`; per-domain toggles under `tool_surface.domains.*`.

By default, master tools are exposed when `mode: masters` (or `hybrid`): `inspect_model`, `get_outputs`, `modify_basic_parameters`, `hvac_loop_inspect`. Core tools are always available in all modes: `model_preflight`, `simulation_manager`, `file_utils`, `post_processing`, `server_manager`. Enable thin wrappers via the flags above if/when implemented. MCP clients only see the tools registered at startup (as configured via `config.yaml` or env flags).

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
     "tool": "run_simulation",
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

Test tools interactively:
```bash
cd energyplus-mcp-server
uv run mcp-inspector energyplus_mcp_server.server
```

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
│     Tools Layer         │  Tools organized into categories (aggregated inspectors/outputs)
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

## License

See [LICENSE](License.txt) file for details.
**Outputs via Domain Manager**
```json
{
  "tool": "outputs_manager",
  "arguments": {
    "action": "list",
    "idf_path": "sample_files/5ZoneAirCooled.idf",
    "type": "both",
    "discover_available": true,
    "run_days": 1
  }
}
```
## Tool Surface Profiles (config.yaml)

You can control how tools are presented via `config.yaml` (default path `energyplus-mcp-server/config.yaml`, override with `MCP_CONFIG_PATH`). The server loads this on startup to decide which tool groups to register.

- Location: `energyplus-mcp-server/config.yaml` (checked first), or path in `MCP_CONFIG_PATH`.
- Parser: requires `pyyaml` (included in dependencies). If missing, the server falls back to env flags and logs a note.
- Restart required after edits.

Schema (minimal):
```yaml
tool_surface:
  mode: masters | domains | hybrid
  enable_wrappers: true | false   # optional, overrides all wrapper flags
  domains:                        # optional fine-grained controls
    envelope: true | false
    internal_loads: true | false
    hvac: true | false
    outputs: true | false
```

Profiles
- Masters (default):
```yaml
tool_surface:
  mode: masters
  enable_wrappers: false
```

- Domains-only (all domains):
```yaml
tool_surface:
  mode: domains
  domains:
    envelope: true
    internal_loads: true
    hvac: true
    outputs: true
```

- Hybrid (both):
```yaml
tool_surface:
  mode: hybrid
  enable_wrappers: false
  domains:
    outputs: true
```

Env flags remain supported and act as defaults when YAML is absent. YAML, if present, takes precedence for mode and global wrapper exposure.
