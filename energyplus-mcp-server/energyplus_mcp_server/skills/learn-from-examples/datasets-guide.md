# DataSets guide

`DataSets/` holds IDF fragments of reusable component data, not runnable
models. Query them through `example_library` with `library="datasets"`, for
example
`example_library(action="search", object_types=["WindowMaterial:Glazing"], library="datasets")`
then
`example_library(action="get_objects", file="WindowGlassMaterials.idf", object_type="WindowMaterial:Glazing", name_contains="LoE")`.
Object counts below are for EnergyPlus 26.1; use `action="status"` or
`action="search"` for the installed release.

| Need | File | Main objects |
|---|---|---|
| Opaque materials | `ASHRAE_2005_HOF_Materials.idf` | ~200 `Material`, ~60 `Material:NoMass`, a few `Construction` |
| Assembled walls | `CompositeWallConstructions.idf` | `Material` + `Construction` pairs |
| Moisture (HAMT/EMPD) properties | `MoistureMaterials.idf` | `MaterialProperty:*` |
| Window constructions | `WindowConstructs.idf` | ~200 `Construction` (reference the glazing/gas files) |
| Glazing, gases, shades | `WindowGlassMaterials.idf`, `WindowGasMaterials.idf`, `WindowBlindMaterials.idf`, `WindowShadeMaterials.idf`, `WindowScreenMaterials.idf` | `WindowMaterial:*` |
| Electric EIR chillers | `Chillers.idf`, `AirCooledChiller.idf` | `Chiller:Electric:EIR` with biquadratic/quadratic curves |
| DX cooling coils, packaged units | `DXCoolingCoil.idf`, `RooftopPackagedHeatPump.idf`, `ResidentialACsAndHPsPerfCurves.idf` | DX coils and performance curves |
| Code-minimum equipment curves | `CodeCompliantEquipment.idf` | Curves for code-compliant equipment |
| Boilers, water-to-air heat pumps | `Boilers.idf`, `WaterToAirHeatPumps.idf` | Curves |
| Economizer, desiccant, cooling tower performance | `ElectronicEnthalpyEconomizerCurves.idf`, `PerfCurves.idf` | Curves, `HeatExchanger:Desiccant:BalancedFlow:PerformanceDataType1`, `CoolingTowerPerformance:*` |
| Standard schedules | `Schedules.idf`, `California_Title_24-2008.idf` | `Schedule:Compact` |
| Holidays and daylight saving | `USHolidays-DST.idf` | `RunPeriodControl:SpecialDays`, `RunPeriodControl:DaylightSavingTime` |
| Predefined monthly reports | `StandardReports.idf` | `Output:Table:Monthly` |
| Emissions factors | `ElectricityUSAEnvironmentalImpactFactors.idf`, `FossilFuelEnvironmentalImpactFactors.idf` | `FuelFactors`, `EnvironmentalImpactFactors`, `Output:EnvironmentalImpactFactors` |
| Refrigeration, PV, solar thermal, generators, ground loops, fluids, life-cycle cost escalation | `Refrigeration*.idf`, `SandiaPVdata.idf`, `SolarCollectors.idf`, `ElectricGenerators.idf`, `GLHERefData.idf`, `*PropertiesRefData.idf`, `LCCusePriceEscalationDataSet*.idf` | Specialized component data |

Cautions:

- A dataset object often references others by name. `WindowConstructs.idf`
  constructions name glazing and gas layers defined in the separate
  `Window*Materials.idf` files, so `get_objects` there reports unresolved
  references: fetch each layer from its own file.
- A chiller or coil entry names its curves; copy the curves with it and keep
  their names consistent with the equipment object's curve fields.
- Datasets describe products or code baselines, not the building you are
  modelling. Record which entry you used and why.
- Large reference files (`PrecipitationSchedulesUSA.idf`,
  `FluidPropertiesRefData.idf`) are best filtered with `names` or `name_contains`.
