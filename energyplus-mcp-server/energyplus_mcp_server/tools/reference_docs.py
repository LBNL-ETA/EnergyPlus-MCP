import json
from typing import Any, Literal, Optional

from energyplus_mcp_server.utils.reference_docs import (
    DEFAULT_MAX_CHARS,
    DOCUMENTS,
    KINDS,
    MAX_CHARS,
    ReferenceDocsError,
    get_reference_docs,
)


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    @mcp.tool()
    async def reference_docs(
        action: Literal["capabilities", "status", "search", "get_section", "get_field"],
        query: Optional[str] = None,
        doc: Optional[Literal[
            "input-output-reference", "engineering-reference",
            "output-details-and-examples", "plant-application-guide",
        ]] = None,
        kind: Optional[Literal["object", "field", "output", "section"]] = None,
        section_id: Optional[int] = None,
        label: Optional[str] = None,
        object_type: Optional[str] = None,
        field: Optional[str] = None,
        include_subsections: bool = True,
        max_chars: Optional[int] = None,
        offset: int = 0,
        limit: Optional[int] = None,
    ) -> str:
        """Read the EnergyPlus reference manuals for the installed release, one section at a time.

        Use it to learn what an object or field means, what an error or output
        file says, or how EnergyPlus models a physical process. Cite the
        document and section you relied on.

        Documents: input-output-reference (every object, field, and output
        variable), engineering-reference (models and equations),
        output-details-and-examples (eplusout.err/.bnd/.eio and other output
        files), plant-application-guide (plant and condenser loops).

        Actions:
        - status: Whether the index is installed, its EnergyPlus version, and section counts.
        - get_field: `object_type` + `field` -> the field's IDD constraints
          (required, type, units, limits, choices, default, notes) plus its
          Input Output Reference paragraph. Accepts IDD or eppy field names;
          repeated fields ("Speed 3 Flow Fraction") match their numbered pattern.
        - get_section: One of `object_type`, `label` (from a [link](#label)),
          or `section_id` (from search). Returns Markdown, paged by
          `max_chars`/`offset`; `include_subsections=False` returns only the
          heading's own text plus an outline of its subsections.
        - search: Keyword search over titles and text; filter by `doc` and
          `kind` (object, field, output, section). Exact titles rank first.

        Read-only. The text is generated from the EnergyPlus documentation source
        (LaTeX) for the installed version; figures are not included.
        """
        try:
            if action == "capabilities":
                return json.dumps(
                    {
                        "tool": "reference_docs",
                        "documents": list(DOCUMENTS),
                        "kinds": list(KINDS),
                        "actions": {
                            "status": {},
                            "search": {"required": ["query"], "optional": ["doc", "kind", "limit"]},
                            "get_section": {
                                "one_of": ["object_type", "label", "section_id"],
                                "optional": ["include_subsections", "max_chars", "offset"],
                            },
                            "get_field": {"required": ["object_type", "field"]},
                        },
                        "max_chars": {"default": DEFAULT_MAX_CHARS, "max": MAX_CHARS},
                    },
                    indent=2,
                )
            docs = get_reference_docs(config)
            if action == "status":
                result = docs.status()
            elif action == "search":
                result = docs.search(query or "", doc=doc, kind=kind, limit=limit or 10)
            elif action == "get_section":
                result = docs.get_section(
                    section_id=section_id,
                    label=label,
                    object_type=object_type,
                    include_subsections=include_subsections,
                    max_chars=max_chars,
                    offset=offset,
                )
            elif action == "get_field":
                result = docs.get_field(object_type or "", field or "")
            else:
                raise ReferenceDocsError(f"Unsupported action: {action}")
            return json.dumps(result, indent=2, ensure_ascii=False)
        except ReferenceDocsError as exc:
            return json.dumps({"error": str(exc), "action": action}, indent=2)
