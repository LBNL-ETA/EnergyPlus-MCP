import json
from typing import Any, List, Literal, Optional

from energyplus_mcp_server.utils.example_library import (
    ExampleLibraryError,
    get_example_library,
)


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    @mcp.tool()
    async def example_library(
        action: Literal["capabilities", "status", "object_types", "search", "describe", "get_objects"],
        object_types: Optional[List[str]] = None,
        keywords: Optional[List[str]] = None,
        features: Optional[List[str]] = None,
        pattern: Optional[str] = None,
        library: Literal["examples", "datasets", "all"] = "all",
        max_zones: Optional[int] = None,
        file: Optional[str] = None,
        object_type: Optional[str] = None,
        names: Optional[List[str]] = None,
        name_contains: Optional[str] = None,
        include_references: bool = True,
        reference_depth: int = 1,
        format: Literal["fields", "idf", "both"] = "fields",
        limit: Optional[int] = None,
    ) -> str:
        """Read-only search of the EnergyPlus example models and DataSets installed with the engine.

        Use it to learn how an unfamiliar object is modelled before adding it
        with idf_modification, and to find realistic component data. Follow
        get_skill("learn-from-examples") for the full procedure.

        Libraries:
        - examples: ~760 runnable ExampleFiles models showing how objects connect.
        - datasets: DataSets fragments (materials, window constructions,
          chiller/DX/boiler curves, schedules, holidays, report sets).

        Actions:
        - status: Installed EnergyPlus version and library sizes.
        - object_types: Valid object type names matching `pattern`
          (substring or wildcard, e.g. "Coil:Cooling:DX*") and how many files use each.
        - search: Files containing ALL `object_types`; narrow with `keywords`
          (file name/description), `features` (ExampleFiles.html flags such as
          "Daylighting", "Chillers"), and `max_zones`. Smallest files rank first.
        - describe: A file's description header, catalog metadata, and object counts.
        - get_objects: Objects of `object_type` from `file` with eppy field names
          (the names idf_modification accepts), plus the schedules, curves,
          constructions, and zones they reference (`reference_depth` 0-3).
          Filter with `names` or `name_contains`; `format` "idf" returns IDF text.

        The inventory is built from the installed files on first use and rebuilt
        when the installation changes. Library files are never modified.
        """
        library_arg = None if library == "all" else library
        try:
            if action == "capabilities":
                return json.dumps(
                    {
                        "tool": "example_library",
                        "actions": {
                            "status": {},
                            "object_types": {"optional": ["pattern", "library", "limit"]},
                            "search": {
                                "one_of": ["object_types", "keywords", "features"],
                                "optional": ["library", "max_zones", "limit"],
                            },
                            "describe": {"required": ["file"], "optional": ["library"]},
                            "get_objects": {
                                "required": ["file", "object_type"],
                                "optional": [
                                    "library", "names", "name_contains", "limit",
                                    "include_references", "reference_depth", "format",
                                ],
                            },
                        },
                        "skill": "learn-from-examples",
                    },
                    indent=2,
                )
            lib = get_example_library(config)
            if action == "status":
                result = lib.status()
            elif action == "object_types":
                result = lib.object_types(pattern or "", library_arg, limit or 50)
            elif action == "search":
                result = lib.search(
                    object_types=object_types,
                    keywords=keywords,
                    features=features,
                    library=library_arg,
                    max_zones=max_zones,
                    limit=limit or 8,
                )
            elif action == "describe":
                result = lib.describe(file or "", library_arg)
            elif action == "get_objects":
                if not object_type:
                    raise ExampleLibraryError("object_type is required for get_objects")
                result = lib.get_objects(
                    file or "",
                    object_type,
                    library=library_arg,
                    names=names,
                    name_contains=name_contains,
                    limit=limit or 3,
                    include_references=include_references,
                    reference_depth=reference_depth,
                    output_format=format,
                )
            else:
                raise ExampleLibraryError(f"Unsupported action: {action}")
            return json.dumps(result, indent=2, default=str)
        except ExampleLibraryError as exc:
            return json.dumps({"error": str(exc), "action": action}, indent=2)
