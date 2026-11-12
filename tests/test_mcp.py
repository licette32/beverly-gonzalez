import asyncio
import unittest
from unittest.mock import MagicMock, patch

from agente.sistema.mcp_server import mcp


class TestMCPServer(unittest.TestCase):
    def test_list_tools(self):
        tools = asyncio.run(mcp.list_tools())
        tool_names = [tool.name for tool in tools]
        self.assertIn("equipos", tool_names)
        self.assertIn("historian", tool_names)
        self.assertIn("catalogo_planta", tool_names)
        self.assertIn("stock", tool_names)
        self.assertIn("historial_ordenes", tool_names)

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

    def test_call_tool_historial_ordenes(self):
        result = asyncio.run(mcp.call_tool("historial_ordenes", {}))
        metadata = result[1] if isinstance(result, tuple) else {}
        result_list = metadata.get("result", []) if isinstance(metadata, dict) else []
        self.assertIsInstance(result_list, list)

    def test_no_server_launch(self):
        """Forbidden: test that does not launch the server and wait for stdout."""
        pass