import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

from energyplus_mcp_server.energyplus_tools import EnergyPlusManager
from energyplus_mcp_server.tools.preflight import register


class EppySequence(list):
    def __add__(self, other):
        raise TypeError("Idf_MSequence cannot be concatenated")


def test_validate_idf_accepts_window_materials_without_concatenating_eppy_sequences():
    objects = {
        "Building": [SimpleNamespace(Name="Building")],
        "Zone": [SimpleNamespace(Name="Zone")],
        "SimulationControl": [SimpleNamespace()],
        "BuildingSurface:Detailed": [SimpleNamespace(Zone_Name="Zone")],
        "Construction": [SimpleNamespace(Name="Window", Outside_Layer="Simple Glazing")],
        "Material": EppySequence([SimpleNamespace(Name="Opaque")]),
        "Material:NoMass": EppySequence(),
        "WindowMaterial:SimpleGlazingSystem": EppySequence([SimpleNamespace(Name="Simple Glazing")]),
    }
    manager = EnergyPlusManager.__new__(EnergyPlusManager)
    manager._resolve_idf_path = lambda path: path
    with patch("energyplus_mcp_server.energyplus_tools.IDF", return_value=SimpleNamespace(idfobjects=objects)):
        result = json.loads(manager.validate_idf("/tmp/model.idf"))
    assert result["is_valid"]
    assert result["summary"]["material_count"] == 2


def test_readiness_rejects_reported_validation_errors(tmp_path):
    model = tmp_path / "model.idf"
    model.write_text("Version,26.1;\n")
    idd = tmp_path / "Energy+.idd"
    idd.write_text("test")
    manager = SimpleNamespace(
        _resolve_idf_path=lambda path: path,
        validate_idf=lambda path: json.dumps({"summary": {"total_errors": 2}, "errors": ["a", "b"]}),
    )
    config = SimpleNamespace(energyplus=SimpleNamespace(idd_path=str(idd)))

    class MCP:
        def tool(self):
            def capture(function):
                self.model_preflight = function
                return function
            return capture

    mcp = MCP()
    register(mcp, manager, config)
    result = json.loads(asyncio.run(mcp.model_preflight("readiness", idf_path=str(model))))
    assert result["verdict"] is False
    assert "Validation errors: 2" in result["issues"]
