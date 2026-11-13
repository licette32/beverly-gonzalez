import time
import unittest
from unittest.mock import MagicMock, patch
import json

from pydantic import ValidationError

from sistema.config import MANUALES_TEXTO_MAX
from sistema.indexado import Fragmento
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
    ManualEncontrado,
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

class _RetrieverFalso:
    def __init__(self, fragmentos):
        self.por_id = {f.id: f for f in fragmentos}


def _frag(
    cita,
    doc="TX350-D",
    tipo="manual_fabricante",
    vigente=True,
    numero="1",
    texto="texto de prueba",
):
    return Fragmento(
        id=cita,
        doc=doc,
        numero=numero,
        titulo="Titulo",
        texto=texto,
        vigente=vigente,
        pagina=None,
        tipo=tipo,
        archivo=None,
    )


class TestManualesBuscar(unittest.TestCase):
    def _patch_rag(self, citas, fragmentos):
        return (
            patch("sistema.rag.buscar", return_value=citas),
            patch(
                "sistema.rag._obtener_retriever",
                return_value=_RetrieverFalso(fragmentos),
            ),
        )

    def test_devuelve_campos_esperados(self):
        frags = [_frag("TX350-D §3.2", numero="3.2", texto="vibracion alta")]
        p_buscar, p_frags = self._patch_rag(["TX350-D §3.2"], frags)
        with p_buscar, p_frags:
            resultado = manuales_buscar("vibracion")
        self.assertEqual(len(resultado), 1)
        item = resultado[0]
        self.assertIsInstance(item, ManualEncontrado)
        self.assertEqual(
            set(item.model_dump()),
            {"cita", "documento", "seccion", "texto", "vigente"},
        )
        self.assertEqual(item.cita, "TX350-D §3.2")
        self.assertEqual(item.documento, "TX350-D")
        self.assertEqual(item.seccion, "3.2")
        self.assertEqual(item.texto, "vibracion alta")
        self.assertTrue(item.vigente)

    def test_filtra_por_tipo_doc_vigente_y_secciones_excluidas(self):
        frags = [
            _frag("TX350-D §3.2"),
            _frag("TX350-C §3.2", doc="TX350-C", vigente=False),
            _frag("historial OT-25-0026", doc="historial", tipo="historial"),
            _frag("CT-SVP-2025 §1.1", doc="CT-SVP-2025", tipo="contrato"),
            _frag("TX350-D §3.3"),
            _frag("MBP-4 §17.3", doc="MBP-4", tipo="manual_operadora"),
            _frag("MBP-4 §18", doc="MBP-4", tipo="manual_operadora"),
        ]
        citas = [f.id for f in frags]
        p_buscar, p_frags = self._patch_rag(citas, frags)
        with p_buscar, p_frags:
            resultado = manuales_buscar("limites")
        self.assertEqual(
            [item.cita for item in resultado], ["TX350-D §3.2", "MBP-4 §18"]
        )

    def test_texto_recortado(self):
        frags = [_frag("TX350-D §3.2", texto="a" * (MANUALES_TEXTO_MAX + 50))]
        p_buscar, p_frags = self._patch_rag(["TX350-D §3.2"], frags)
        with p_buscar, p_frags:
            resultado = manuales_buscar("texto largo")
        self.assertEqual(len(resultado[0].texto), MANUALES_TEXTO_MAX)

    def test_consulta_vacia_devuelve_lista_sin_buscar(self):
        with patch("sistema.rag.buscar") as buscar:
            self.assertEqual(manuales_buscar(""), [])
            self.assertEqual(manuales_buscar("   "), [])
        buscar.assert_not_called()

    def test_sin_resultados_devuelve_lista(self):
        p_buscar, p_frags = self._patch_rag([], [])
        with p_buscar, p_frags:
            self.assertEqual(manuales_buscar("sin coincidencias"), [])

    def test_timeout_es_reintentable_y_reintenta_una_vez(self):
        def lento(*args, **kwargs):
            time.sleep(1.0)
            return []

        with patch("sistema.tools.MANUALES_TIMEOUT_S", 0.2), patch(
            "sistema.rag.buscar", side_effect=lento
        ) as buscar:
            with self.assertRaises(ErrorInfo) as ctx:
                manuales_buscar("vibracion")
        self.assertEqual(ctx.exception.codigo, "MANUALES_TIMEOUT")
        self.assertTrue(ctx.exception.reintentable)
        self.assertEqual(buscar.call_count, 2)

    def test_error_de_busqueda_es_reintentable(self):
        with patch(
            "sistema.rag.buscar", side_effect=RuntimeError("fallo")
        ) as buscar:
            with self.assertRaises(ErrorInfo) as ctx:
                manuales_buscar("vibracion")
        self.assertEqual(ctx.exception.codigo, "MANUALES_ERROR")
        self.assertTrue(ctx.exception.reintentable)
        self.assertEqual(buscar.call_count, 2)

    def test_esquema_rechaza_campos_extra(self):
        with self.assertRaises(ValidationError):
            ManualEncontrado(
                cita="TX350-D §3.2",
                documento="TX350-D",
                seccion="3.2",
                texto="x",
                vigente=True,
                extra="no permitido",
            )


if __name__ == "__main__":
    unittest.main()