# EnergyPlus error catalog

Every message below is real EnergyPlus 26.1.0 output, produced by breaking a
copy of `ExampleFiles/5ZoneAirCooled.idf` in one way (design-day runs) or by
running unmodified example files for a year with the Chicago TMY3 weather
file. Wording changes between versions: match on the stable part (routine
name, object type, key phrase), and confirm with
`reference_docs(action="search", query=...)` when a message is not listed.
The `category` column is the tag the parser assigns.

## Errors that stop the run

| Category | Real message (lead line, then context) | Meaning | Inspect | Usual fix |
|---|---|---|---|---|
| `input_schema` | `<root>[Lights][SPACE1-1 Lights 1][design_level_calculation_method] - "Watts/Areaa" - Failed to match against any enum values.` | A choice field holds a value the IDD does not allow. | `reference_docs(action="get_field", object_type="Lights", field="Design Level Calculation Method")` for the valid choices | Set a listed choice; keep the populated level field consistent with it. |
| `input_schema` | `<root>[Material][WD10][conductivity] - "-1.000000" - Expected number greater than 0.000000` | A number is outside the IDD limits. | `reference_docs(action="get_field", ...)` for minimum, maximum, units | Use a physical value with a source (project data, the target model, DataSets). |
| `duplicate_name` | `Duplicate name found for object of type "Schedule:Compact" named "OCCUPY-1". Overwriting existing object.` | Two objects of one type share a name; the later one replaces the first. | `idf_modification(action="find", object_type="Schedule:Compact", name_contains="OCCUPY-1")` lists both copies; compare their fields | Rename one and update its references, or delete the true duplicate after comparing contents. |
| `missing_reference` | `GetConstructData: Construction = NONEXISTENT MATERIAL` / context `Name = NONEXISTENT MATERIAL, item not found.` | A construction layer names a material that does not exist. The first line names the missing item, not the construction. | `idf_modification(action="find", references="NONEXISTENT MATERIAL")` (no `defines` result confirms it is missing); `envelope_manager(action="inspect", focus="constructions")` for candidates | Point the layer at an existing material, or add the material (DataSets via `example_library(action="search", library="datasets", ...)`). |
| `missing_reference` | `GetInternalHeatGains: Lights = SPACE1-1 LIGHTS 1` / context `Schedule Name = MISSING LIGHTS SCHEDULE, item not found.` | The object names a schedule that does not exist. In 26.1 this case crashed EnergyPlus right after the message (status `incomplete`). | `idf_modification(action="find", references="MISSING LIGHTS SCHEDULE")`; `schedule_manager(action="inspect")` for candidates | Point the field at an existing schedule, or create the schedule. |
| `node_connection` | `Potential Node Connection Error for object FAN:VARIABLEVOLUME, name=SUPPLY FAN 1` / context `Node Types are still UNDEFINED`, `Outlet Node: VAV SYS 1 OUTLET NODE`; followed by Warning `Air Nodes not on any Branch or Parent Object` listing `VAV SYS 1 OUTLET NODE TYPO` | A component's node name does not match the branch or parent object around it, usually a spelling difference. The Warning shows the name actually written on the component. | `idf_modification(action="find", references=...)` for each spelling of the node; `hvac_manager(action="topology", loop_name=...)` | Make the component, branch, and parent use the same node name. |
| `setpoint` | `HVACControllers: Missing temperature setpoint for controller type=Controller:WaterCoil Name="OA HC CONTROLLER 1"` / context `Node Referenced (by Controller)=OA HEATING COIL 1 AIR OUTLET NODE` | A water-coil controller senses a node that no setpoint manager sets. | `idf_modification(action="find", object_type="SetpointManager:*", references=<sensed node>)` (empty means no manager sets it); `hvac_manager(action="topology", loop_name=...)` | Add or repoint a `SetpointManager:*` to the sensed node (see `get_skill("learn-from-examples")`). |
| `setpoint` | `PlantManager: No Setpoint Manager Defined for Node=HW SUPPLY OUTLET NODE in PlantLoop=HOT WATER LOOP` | A plant loop's setpoint node has no setpoint manager. | `hvac_manager(action="discover")` lists each loop's supply outlet node; `idf_modification(action="find", object_type="SetpointManager:*", references=<node>)` | Add a temperature setpoint manager for the loop's setpoint node. |
| `sizing` | `CheckEnvironmentSpecifications: Sizing for Zones has been requested but there are no design environments specified.` (also for Systems and Equipment/Plants) | `SimulationControl` asks for sizing but the model has no `SizingPeriod:*` objects. | `model_preflight(action="info")` | Add design days for the site (from the weather file's `.ddy`), or turn off the sizing flags with `simulation_manager(action="update_settings", ...)` if the user agrees. |
| `weather` | `GetNextEnvironment: Weather Environment(s) requested, but no weather file found` | An annual (run period) simulation was started without a weather file. | `model_preflight(action="readiness", weather_file=...)` | Pass `weather_file` to `simulation_manager(action="run", ...)`, or run design days only. |
| `termination` | `Errors occurred on processing input file. Preceding condition(s) cause termination.`, `Program terminates due to preceding conditions.`, `Previous severe set point errors cause program termination` | Announces the stop. Never the cause. | Read the Severe messages above it. | None directly. |

Messages may cascade: removing all setpoint managers produced 6 Severe and 6
Warnings, all one cause.

## Warnings and Severe messages in runs that complete

| Category | Real message | Affects results? | Action |
|---|---|---|---|
| `version` | `Version: in IDF="9.2" not the same as expected="26.1"` | Not by itself; the run continued. Old content usually also produces field errors. | `model_upgrade(action="plan", idf_path=...)` and ask before upgrading a copy. |
| `weather` | `Weather file location will be used rather than entered (IDF) Location object.` with context giving latitude, longitude, time zone, and elevation differences | Small differences: no. Large ones (a Denver model with Chicago weather: 2.24° latitude, 1628 m elevation) mean the design days and weather describe different sites. | Ask the user which site is intended; do not change it silently. |
| (none) | `SetUpDesignDay: Entered DesignDay Barometric Pressure=81198 differs by more than 10% from Standard Barometric Pressure=98934.` | EnergyPlus substitutes the standard pressure; usually a consequence of the location mismatch above. | Fix the site mismatch first. |
| `geometry` | `GetVertices: Floor is upside down! Tilt angle=[0.0], should be near 180, Surface="C1-1P", in Zone="PLENUM-1".` / `Automatic fix is attempted.` | Usually corrected automatically, but signals vertex-order errors that may affect other surfaces. | `geometry_manager(action="extract_and_summary")`; fix vertex order if several surfaces are affected. |
| `setpoint` | `CheckForSensorAndSetpointNode: Coil:Heating:Water="OA HEATING COIL 1".` / `..Temperature setpoint not found on coil air outlet node.` | Yes if the controller then fails; often reported together with the Severe controller errors above. | `hvac_manager(action="topology", loop_name=...)` for the coil's air loop. |
| `setpoint` | `Missing temperature setpoint for LeavingSetpointModulated mode chiller named CENTRAL CHILLER` / `The overall loop setpoint will be assumed for chiller.` | Yes: the chiller runs to the loop setpoint, not its own. | Add a setpoint manager on the chiller outlet node if the design intends one. |
| `psychrometrics` | `Temperature out of range [-100. to 200.] (PsyPsatFnTemp)` with `Input Temperature=-3353.49`; `WetBulb not converged after 101 iterations(PsyTwbFnTdbWPb)` | A non-physical state occurred at that timestep. One occurrence is a numerical glitch; repeated ones point to an upstream input or control problem. | Note the timestep from the context line; check the equipment active then. |
| (none) | `SetBranchControlTypes: Caught unexpected equipment type of number` (Severe, run still "Completed Successfully" with 2 Severe) | Possibly: a Severe in a completed run means EnergyPlus fell back on a default somewhere. | `hvac_manager(action="topology", loop_name=...)` for the plant loops; search the documentation for the routine name. |
| (none) | Recurring: `CalcDoe2DXCoil: Coil:WaterHeating:AirToWaterHeatPump:Wrapped="HPWHPLANTDXCOIL" - Air volume flow rate per watt of rated total water heating capacity is out of range` (3,531,704 times) | Yes: the coil runs outside its rated range almost every timestep, so its performance curves are extrapolated. | `reference_docs(action="get_field", ...)` for the rated flow and capacity fields; correct the sizing. |
| (none) | Recurring: `"SINKS" - Target water temperature should be less than or equal to the hot water temperature` (1,147,903 times, Max=19.5, Min=0.000006) | Yes: the fixtures cannot reach their target temperature, so hot-water use is misstated. | Compare the use equipment's target temperature schedule with the water heater setpoint. |

That last run printed only 8 warnings in full but reported 5,059,591 in its
totals. Always read `summary.totals` and the `recurring` list.

## Reading the file structure

- `Program Version,EnergyPlus, Version 26.1.0-...` is the first line.
- `************* Beginning Zone Sizing Calculations` and similar lines mark
  phases; a Severe after one of them happened in that phase.
- `************* ===== Recurring Error Summary =====` lists repeated messages
  with `This error occurred N total times;`, warmup and sizing counts, and
  sometimes `Max=... Min=...`.
- `************* ===== Final Error Summary =====` names categories (for
  example `Node Connection Errors`) with EnergyPlus's own advice.
- `During Warmup: a Warning; b Severe Errors.` and `During Sizing: ...` are
  subsets of the final totals, not additions to them.
- `EnergyPlus Completed Successfully-- W Warning; S Severe Errors` or
  `EnergyPlus Terminated--Fatal Error Detected. W Warning; S Severe Errors`
  ends a finished run. If neither appears, the run crashed or is still running.
- Full description: `reference_docs(action="get_section", label="eplusout.err")`.
