"""Tool replies are sent as compact JSON without changing their content."""

import asyncio
import json
from types import SimpleNamespace

from energyplus_mcp_server.utils.output_guard import compact_reply, guard_tool

PRETTY = json.dumps(
    {"success": True, "units": "W/m²", "temperature": "21 °C", "values": [1.5, 2, None, 1e-12],
     "nested": {"name": "SPACE1-1", "list": [{"a": 1}, {"b": [True, False]}]}},
    indent=2,
)


def test_json_object_is_compacted_with_identical_content():
    compact = compact_reply(PRETTY)

    assert json.loads(compact) == json.loads(PRETTY)
    assert "\n" not in compact and ": " not in compact
    assert len(compact) < len(PRETTY) * 0.8
    # Non-ASCII text is sent as UTF-8, not as \\u escapes.
    assert "W/m²" in compact and "°C" in compact


def test_json_array_and_leading_whitespace_are_handled():
    assert compact_reply('\n  [1, 2,\n 3]') == "[1,2,3]"


def test_key_order_is_preserved():
    assert compact_reply('{"z": 1, "a": 2}') == '{"z":1,"a":2}'


def test_other_replies_are_left_alone():
    assert compact_reply("Missing required parameter: idf_path") == "Missing required parameter: idf_path"
    assert compact_reply("{not json") == "{not json"
    assert compact_reply('"just a string"') == '"just a string"'
    payload = {"already": "a dict"}
    assert compact_reply(payload) is payload
    assert compact_reply(None) is None


def test_compaction_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("MCP_COMPACT_JSON", "0")

    assert compact_reply(PRETTY) == PRETTY


def test_registered_tools_reply_compactly():
    config = SimpleNamespace(transport=SimpleNamespace(transport="stdio"))

    async def tool() -> str:
        return PRETTY

    reply = asyncio.run(guard_tool(tool, config)())

    assert reply == compact_reply(PRETTY)
