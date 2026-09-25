# Curated sample files

Read-only inputs distributed with the server. Use a model here as a source,
then copy it to `../work/models/derived/` before changing or simulating it.
The server rejects any output path inside this directory.

- `basic/`: compact EnergyPlus examples for general workflows.
- `mcp_paper/`: models from the EnergyPlus-MCP paper case studies
  (`5ZoneAirCooled_baseline.idf` and its `5ZoneAirCooled_improved.idf`
  retrofit, and `iUnit_Golden.idf`).
- `weather/`: weather files used by the examples above.

A bare filename such as `5ZoneAirCooled.idf` resolves anywhere in this tree,
as does the older `sample_files/<name>` form.
