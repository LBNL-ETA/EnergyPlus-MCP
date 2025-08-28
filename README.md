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
    - [🗂️ Model Config \& Loading (9 tools)](#️-model-config--loading-9-tools)
    - [🔍 Model Inspection (Aggregated)](#-model-inspection-aggregated)
    - [⚙️ Model Modification (Aggregated)](#️-model-modification-aggregated)
    - [🚀 Simulation \& Results (4 tools)](#-simulation--results-4-tools)
    - [🖥️ Server Management (5 tools)](#️-server-management-5-tools)
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

Use the unified tools first; expose individual wrappers via env flags only when needed. Tree below shows unified → wrappers.

### 🔍 Inspection
- `inspect_model`
  - Focus: `summary | zones | surfaces | materials | schedules | people | lights | electric_equipment | all`
  - Includes `get_outputs` (type: `variables|meters|both`)
  - Wrappers (optional): `get_model_summary`, `inspect_people`, `inspect_lights`, `inspect_electric_equipment`, `list_zones`, `get_surfaces`, `get_materials`, `get_output_variables`, `get_output_meters`
- `hvac_loop_inspect`
  - Actions: `discover | topology | visualize`
  - Wrappers (optional): `discover_hvac_loops`, `get_loop_topology`, `visualize_loop_diagram`

### ⚙️ Modification
- `modify_basic_parameters`
  - Ops: `people.update`, `lights.update`, `electric_equipment.update`, `simulation_control.update`, `run_period.update`, `infiltration.scale`, `envelope.add_window_film`, `envelope.add_coating`, `outputs.add_variables`, `outputs.add_meters`
  - Wrappers (optional): `modify_people`, `modify_lights`, `modify_electric_equipment`, `modify_simulation_control`, `modify_run_period`, `change_infiltration_by_mult`, `add_window_film_outside`, `add_coating_outside`, `add_output_variables`, `add_output_meters`

### 🗂️ Files
- `file_utils`
  - Actions: `list` (sample/example/weather), `copy` (with dry_run/apply)
  - Wrappers (optional): `list_available_files`, `copy_file`

### 🖥️ Server Management
- `server_housekeeping`
  - Actions: `status` (optionally include_config), `logs` (server/error/both, filters), `clear_logs` (dry_run/apply)
  - Wrappers (optional): `get_server_status`, `get_server_logs`, `get_error_logs`, `clear_logs`

### 🚀 Lifecycle & Results
- `load_idf_model`, `validate_idf`
- `run_energyplus_simulation`, `create_interactive_plot`

### Tool Exposure Flags

- `MCP_EXPOSE_INSPECT_WRAPPERS=true` — Expose individual inspection wrappers (`inspect_people`, `inspect_lights`, `list_zones`, etc.).
- `MCP_EXPOSE_OUTPUT_WRAPPERS=true` — Expose legacy output wrappers (`get_output_variables`, `get_output_meters`).
- `MCP_EXPOSE_SUMMARY_WRAPPER=true` — Expose `get_model_summary` wrapper.
- `MCP_EXPOSE_MODIFY_WRAPPERS=true` — Expose legacy modify wrappers (`modify_people`, `modify_lights`, etc.).
- `MCP_EXPOSE_SERVER_WRAPPERS=true` — Expose legacy server wrappers (`get_server_status`, `get_server_logs`, `get_error_logs`, `clear_logs`).
- `MCP_EXPOSE_HVAC_WRAPPERS=true` — Expose legacy HVAC wrappers (`discover_hvac_loops`, `get_loop_topology`).
- `MCP_EXPOSE_FILE_WRAPPERS=true` — Expose legacy file wrappers (`list_available_files`, `copy_file`).

By default, only `inspect_model` and `get_outputs` are exposed for read-only inspection/output.

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
  "tool": "server_housekeeping",
  "arguments": { "action": "status" }
}
```

**Housekeeping: Error Logs (raw)**
```json
{
  "tool": "server_housekeeping",
  "arguments": { "action": "logs", "type": "error", "lines": 100, "format": "raw" }
}
```

**Housekeeping: Rotate Logs (dry-run)**
```json
{
  "tool": "server_housekeeping",
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
