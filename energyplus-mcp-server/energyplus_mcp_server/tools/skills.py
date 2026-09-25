import json
from typing import Any, Optional

from energyplus_mcp_server.utils.skill_catalog import SkillCatalog, SkillError


def register(mcp: Any, ep_manager: Any, config: Any) -> None:
    catalog = SkillCatalog()

    @mcp.tool()
    async def list_skills() -> str:
        """List EnergyPlus-MCP agent skills: step-by-step guides for native-IDF work.

        Call this before a multi-step task you have not done with this server,
        such as adding an object type you have not modelled before. Returns
        each skill's name and when to use it; load one with get_skill(name).
        """
        try:
            return json.dumps(catalog.list(), indent=2)
        except SkillError as exc:
            return json.dumps({"error": str(exc)}, indent=2)

    @mcp.tool()
    async def get_skill(name: str, file: Optional[str] = None) -> str:
        """Load an EnergyPlus-MCP skill's instructions, or one of its supporting files.

        Args:
            name: Skill name from list_skills (e.g. "learn-from-examples").
            file: Optional supporting file listed in the skill's "files"
                (e.g. "datasets-guide.md"). Omit to get the main instructions.
        """
        try:
            return json.dumps(catalog.get(name, file), indent=2)
        except SkillError as exc:
            return json.dumps({"error": str(exc)}, indent=2)
