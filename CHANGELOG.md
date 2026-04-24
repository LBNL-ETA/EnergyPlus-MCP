# Changelog

All notable changes to this project are documented here.
This file follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Once the project starts cutting tagged releases, entries will graduate from
`[Unreleased]` to a dated version heading (e.g. `[0.2.0] - 2026-05-01`).
Until then, `[Unreleased]` captures all changes landed on the `agentic-bem`
branch since the README/install-instructions cleanup.

## [Unreleased]

### Changed
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
