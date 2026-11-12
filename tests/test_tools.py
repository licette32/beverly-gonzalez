import unittest
from unittest.mock import MagicMock, patch
import json

from sistema.tools import (
    ErrorInfo,
    HistorianRequest,
    HistorianResponse,
    CatalogoRequest,
    CatalogoResponse,
    StockItem,
    StockQuery,
    StockResponse,
    HistorialOrdenesRequest,
    HistorialOrdenesResponse,
    historian,
    catalogo,
    stock,
    tareas_catalogo,
    manuales_buscar,
    PLANTA_BASE_URL,
)


class TestToolsModels(unittest.TestCase):
    def test_error_info_extra_forbid(self):
        with self.assertRaises(ErrorInfo) as ctx:
            raise ErrorInfo(codigo="test", mensaje="test")
        self.assertEqual(ctx.exception.codigo, "test")
        self.assertEqual(ctx.exception.mensaje, "test")
        self.assertFalse(ctx.exception.reintentable)

    def test_historian_request_config(self):
        req = HistorianRequest(tag="B-101", variable="presion_descarga_local")
        self.assertEqual(req.tag, "B-101")
        self.assertEqual(req.variable, "presion_descarga_local")

    def test_stock_item_config(self):
        item = StockItem(tag="B-101", nombre="Bomba Uno", cantidad=100, unidad="unidades")
        self.assertEqual(item.tag, "B-101")

    def test_stock_response_vacio(self):
        resp = StockResponse(items=[], vacio=True)
        self.assertTrue(resp.vacio)

    def test_historial_ordenes_request(self):
        req = HistorialOrdenesRequest(tag="B-101", orden_id="T-001")
        self.assertEqual(req.tag, "B-101")
        self.assertEqual(req.orden_id, "T-001")


class TestToolsFunctions(unittest.TestCase):
    @patch("sistema.tools._fetch")
    def test_historian_success(self, mock_fetch):
        mock_fetch.return_value = [{"valor": 1.0}, {"valor": 2.0}, {"valor": 3.0}]
        with patch("sistema.tools.PLANTA_BASE_URL", "http://sim:8100"):
            result = historian("B-101", "presion_descarga_local")
        self.assertIsInstance(result, HistorianResponse)
        self.assertEqual(result.valores, [1.0, 2.0, 3.0])

    @patch("sistema.tools._fetch")
    def test_historian_retryable_error(self, mock_fetch):
        mock_fetch.side_effect = Exception("connection refused")
        with patch("sistema.tools.PLANTA_BASE_URL", "http://sim:8100"):
            with self.assertRaises(ErrorInfo) as ctx:
                historian("B-101", "presion_descarga_local")
        self.assertTrue(ctx.exception.reintentable)
        self.assertEqual(ctx.exception.codigo, "HISTORIAN_ERROR")

    @patch("sistema.tools._fetch")
    def test_catalogo_success(self, mock_fetch):
        mock_fetch.return_value = {"equipos": [{"tag": "B-101", "tipo": "bomba"}]}
        with patch("sistema.tools.PLANTA_BASE_URL", "http://sim:8100"):
            result = catalogo("B-101")
        self.assertIsInstance(result, CatalogoResponse)
        self.assertEqual(len(result.equipos), 1)
        self.assertEqual(result.equipos[0]["tag"], "B-101")

    @patch("sistema.tools._fetch")
    def test_catalogo_sin_tag(self, mock_fetch):
        mock_fetch.return_value = {"equipos": [{"tag": "B-101"}, {"tag": "B-102"}]}
        with patch("sistema.tools.PLANTA_BASE_URL", "http://sim:8100"):
            result = catalogo()
        self.assertEqual(len(result.equipos), 2)

    @patch("sistema.tools.os.path.exists")
    @patch("sistema.tools.yaml")
    def test_stock_desde_yaml(self, mock_yaml, mock_exists):
        mock_exists.return_value = True
        mock_yaml.safe_load.return_value = {
            "stock": [{"tag": "B-101", "nombre": "Bomba Uno", "cantidad": 100, "unidad": "unidades"}]
        }
        result = stock("B-101")
        self.assertIsInstance(result, StockResponse)
        self.assertFalse(result.vacio)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].tag, "B-101")

    @patch("sistema.tools.os.path.exists")
    def test_stock_vacio_sin_yaml(self, mock_exists):
        mock_exists.return_value = False
        result = stock()
        self.assertIsInstance(result, StockResponse)
        self.assertTrue(result.vacio)

    @patch("sistema.tools.os.path.exists")
    @patch("sistema.tools.yaml")
    def test_tareas_catalogo_con_yaml(self, mock_yaml, mock_exists):
        mock_exists.return_value = True
        mock_yaml.safe_load.return_value = {"tareas": [{"id": "T-001", "nombre": "Revisar presión"}]}
        result = tareas_catalogo()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "T-001")

    @patch("sistema.tools.os.path.exists")
    def test_tareas_catalogo_sin_yaml(self, mock_exists):
        mock_exists.return_value = False
        result = tareas_catalogo()
        self.assertEqual(result, [])

    def test_manuales_buscar_vacia(self):
        result = manuales_buscar("cualquier cosa")
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()