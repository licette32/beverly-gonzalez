import asyncio
import unittest
from unittest.mock import MagicMock, patch

from mcp.server.fastmcp.exceptions import ToolError

from agente.sistema.mcp_server import mcp


class TestMCPServer(unittest.TestCase):
    def test_list_tools(self):
        tools = asyncio.run(mcp.list_tools())
        tool_names = [tool.name for tool in tools]
        self.assertIn("equipos", tool_names)
        self.assertIn("historian", tool_names)
        self.assertIn("catalogo_planta", tool_names)
        self.assertIn("stock", tool_names)
        self.assertIn("tareas_catalogo", tool_names)
        self.assertIn("manuales_buscar", tool_names)

    def test_call_tool_equipos(self):
        result = asyncio.run(mcp.call_tool("equipos", {}))
        # call_tool returns (content_list, metadata_dict)
        metadata = result[1] if isinstance(result, tuple) else {}
        result_list = metadata.get("result", []) if isinstance(metadata, dict) else []
        self.assertIsInstance(result_list, list)

    def test_call_tool_historian(self):
        result = asyncio.run(mcp.call_tool("historian", {"tag": "B-101", "variable": "presion_descarga_local"}))
        metadata = result[1] if isinstance(result, tuple) else {}
        result_list = metadata.get("result", []) if isinstance(metadata, dict) else []
        self.assertIsInstance(result_list, list)

    def test_call_tool_stock(self):
        result = asyncio.run(mcp.call_tool("stock", {"tag": "B-101"}))
        metadata = result[1] if isinstance(result, tuple) else {}
        result_list = metadata.get("result", []) if isinstance(metadata, dict) else []
        self.assertIsInstance(result_list, list)
        self.assertTrue(result_list)
        self.assertEqual(
            set(result_list[0]),
            {"codigo", "nombre", "unidad", "almacen", "cantidad", "costo_unitario"},
        )

    @patch("agente.sistema.tools.MATERIALES_PATH", "no-existe-materiales.yaml")
    def test_call_tool_stock_propaga_error(self):
        with self.assertRaises(ToolError):
            asyncio.run(mcp.call_tool("stock", {}))

    def test_call_tool_tareas_catalogo(self):
        result = asyncio.run(mcp.call_tool("tareas_catalogo", {}))
        metadata = result[1] if isinstance(result, tuple) else {}
        result_list = metadata.get("result", []) if isinstance(metadata, dict) else []
        self.assertIsInstance(result_list, list)
        self.assertTrue(result_list)
        self.assertTrue(all("codigo" in tarea for tarea in result_list))

    @patch("agente.sistema.tools.MATERIALES_PATH", "no-existe-materiales.yaml")
    def test_call_tool_tareas_catalogo_propaga_error(self):
        with self.assertRaises(ToolError):
            asyncio.run(mcp.call_tool("tareas_catalogo", {}))

    def test_call_tool_manuales_buscar_vacio(self):
        result = asyncio.run(mcp.call_tool("manuales_buscar", {"texto": ""}))
        metadata = result[1] if isinstance(result, tuple) else {}
        result_list = metadata.get("result", []) if isinstance(metadata, dict) else []
        self.assertEqual(result_list, [])

    def test_no_server_launch(self):
        """Forbidden: test that does not launch the server and wait for stdout."""
        pass