# EnergyPlus MCP Server

A Model Context Protocol (MCP) server that provides **35 comprehensive tools** for working with EnergyPlus building energy simulation models. This server enables AI assistants and other MCP clients to load, validate, modify, and analyze EnergyPlus IDF files through a standardized interface.

> **Version**: 0.1.0  
> **EnergyPlus Compatibility**: 25.1.0  
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
- [Available Tools](#available-tools)
- [Usage Examples](#usage-examples)
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

The server provides tools organized into categories. To reduce cognitive load for LLMs, use the aggregated inspection/output tools by default (wrappers can be re-exposed via env flags).

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

### 🔍 Model Inspection (Aggregated)
- `inspect_model` — Unified inspector. Args: `idf_path`, `focus: list["summary"|"zones"|"surfaces"|"materials"|"schedules"|"people"|"lights"|"electric_equipment"|"all"]`, `detail`, `include_values` (schedules only).
- `get_outputs` — Unified outputs accessor. Args: `idf_path`, `type: "variables"|"meters"|"both"`, `discover_available`, `run_days`.

Wrappers like `inspect_people`, `inspect_lights`, `list_zones`, `get_surfaces`, `get_materials`, `get_output_variables`, `get_output_meters` are hidden by default but can be exposed by setting env flags (see below).

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

### Tool Exposure Flags

- `MCP_EXPOSE_INSPECT_WRAPPERS=true` — Expose individual inspection wrappers (`inspect_people`, `inspect_lights`, `list_zones`, etc.).
- `MCP_EXPOSE_OUTPUT_WRAPPERS=true` — Expose legacy output wrappers (`get_output_variables`, `get_output_meters`).
- `MCP_EXPOSE_SUMMARY_WRAPPER=true` — Expose `get_model_summary` wrapper.

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

### Using with MCP Inspector

Test tools interactively:
```bash
cd energyplus-mcp-server
uv run mcp-inspector energyplus_mcp_server.server
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
