import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from planta_contrato import EstadoOrden
from test_ordenes import evento_sensor

from sistema.causas import Anomalia, Causa, EvidenciaEquipo, causas_probables
from sistema.flujo import CatalogoTools, procesar
from sistema.tools import StockItem, tareas_catalogo

TZ = timezone(timedelta(hours=-3))
DESDE = datetime(2026, 11, 4, 6, 0, tzinfo=TZ)
HASTA = datetime(2026, 11, 4, 7, 0, tzinfo=TZ)
TS = datetime(2026, 11, 4, 6, 30, tzinfo=TZ)
BOMBAS_EN_MARCHA = {"B-101": "marcha", "B-102": "marcha", "B-103": "marcha"}
BOMBAS_CON_RESERVA = {"B-101": "marcha", "B-102": "parada", "B-103": "marcha"}


def anomalia(tag, variable, lado):
    return Anomalia(tag, variable, TS, lado)


def evidencia(equipo, anomalias=()):
    return EvidenciaEquipo(equipo, DESDE, HASTA, tuple(anomalias))


def orden_historica(orden_id, fecha, equipo, tareas, texto=""):
    return {
        "id": orden_id,
        "fecha": fecha,
        "equipo": equipo,
        "tareas": list(tareas),
        "estado": "Cerrada",
        "ejecutor": "propio",
        "trabajo_realizado": texto,
    }


def causa(
    codigo_falla,
    tarea_codigo,
    equipo_orden,
    *,
    accion="orden",
    ejecutor="propio",
    genera_orden=True,
):
    return Causa(
        codigo_falla=codigo_falla,
        descripcion=codigo_falla,
        evidencia=("historial_repetido",),
        faltantes=(),
        tarea_codigo=tarea_codigo,
        equipo_orden=equipo_orden,
        citas=(),
        accion=accion,
        genera_orden=genera_orden,
        ejecutor=ejecutor,
    )


def item_stock(codigo, cantidad=100.0):
    return StockItem(
        codigo=codigo,
        nombre=codigo,
        unidad="unidad",
        almacen="yacimiento",
        cantidad=cantidad,
        costo_unitario=1.0,
    )


class CatalogoFalso:
    def __init__(self, tareas=None, stock=None):
        self._tareas = list(tareas_catalogo()) if tareas is None else list(tareas)
        self._stock = stock or {}

    def tareas_catalogo(self):
        return self._tareas

    def tareas_no_estandar(self):
        return []

    def stock(self, equipo):
        return self._stock.get(equipo, ())


class ConCitas(unittest.TestCase):
    def setUp(self):
        parche = patch("sistema.causas.verificar_cita", return_value=True)
        parche.start()
        self.addCleanup(parche.stop)


class TestFlujo(ConCitas):
    def test_acople_b101_f06_t_b_ali(self):
        historial = [
            orden_historica(
                "H1", "2026-09-08T09:00:00-03:00", "B-101", ["T-B-VAL"]
            ),
            orden_historica(
                "H2",
                "2026-08-12T09:00:00-03:00",
                "B-101",
                ["I-VIB"],
                texto="b1 axial en 1x subiendo, vigilar acople",
            ),
        ]
        ev = evidencia("B-101", [anomalia("B-101", "vibracion", "alta")])
        resultado = procesar(
            evento_sensor("B-101"),
            ev,
            historial,
            CatalogoTools(),
            estado_bombas=BOMBAS_CON_RESERVA,
        )

        self.assertEqual(resultado.causas[0].codigo_falla, "F06")
        self.assertIsNotNone(resultado.orden)
        self.assertEqual(resultado.orden.equipo, "B-101")
        self.assertEqual(resultado.orden.tareas, ["T-B-ALI"])
        self.assertEqual(resultado.problemas, ())
        self.assertNotIn("REDUCE_INYECCION", resultado.pendiente_por)
        self.assertIn("TAREA_NO_ESTANDAR", resultado.pendiente_por)
        self.assertIn("EJECUTOR_NO_PROPIO", resultado.pendiente_por)
        self.assertEqual(resultado.orden.estado, EstadoOrden.pendiente)

    def test_acople_sin_reserva_reduce_inyeccion(self):
        """Sin reserva disponible, alinear el acople reduce la inyección."""
        historial = [
            orden_historica(
                "H1", "2026-09-08T09:00:00-03:00", "B-101", ["T-B-VAL"]
            ),
            orden_historica(
                "H2",
                "2026-08-12T09:00:00-03:00",
                "B-101",
                ["I-VIB"],
                texto="b1 axial en 1x subiendo, vigilar acople",
            ),
        ]
        ev = evidencia("B-101", [anomalia("B-101", "vibracion", "alta")])
        resultado = procesar(
            evento_sensor("B-101"),
            ev,
            historial,
            CatalogoTools(),
            estado_bombas=BOMBAS_EN_MARCHA,
        )

        self.assertEqual(resultado.orden.tareas, ["T-B-ALI"])
        self.assertIn("REDUCE_INYECCION", resultado.pendiente_por)
        self.assertEqual(resultado.orden.estado, EstadoOrden.pendiente)

    def test_cavitacion_b102_raiz_filtro_nunca_en_bomba(self):
        historial = [
            orden_historica(
                "V1",
                "2026-04-15T14:30:00-03:00",
                "F-201A",
                ["T-F-CAR"],
                texto="b2 cavita ruido piedras succion",
            )
        ]
        ev = evidencia(
            "B-102",
            [
                anomalia("B-102", "presion_succion", "baja"),
                anomalia("B-102", "vibracion", "alta"),
                anomalia("F-201A", "presion_diferencial", "alta"),
            ],
        )
        resultado = procesar(evento_sensor("B-102"), ev, historial, CatalogoTools())

        self.assertEqual(resultado.causas[0].codigo_falla, "F09")
        self.assertIsNotNone(resultado.orden)
        self.assertEqual(resultado.orden.equipo, "F-201A")
        self.assertEqual(resultado.orden.tareas, ["T-F-CAR"])
        self.assertFalse(
            any(tarea.startswith("T-B-") for tarea in resultado.orden.tareas)
        )
        self.assertNotIn(resultado.orden.equipo, ("B-101", "B-102", "B-103"))

    def test_reten_resuelto_no_cambia_causas_y_da_sin_orden(self):
        ev = evidencia("B-102", [anomalia("B-102", "vibracion", "alta")])
        base = causas_probables(ev)
        historial = [
            orden_historica(
                "A1",
                "2025-10-28T09:00:00-03:00",
                "B-102",
                ["T-B-ACE"],
                texto="aceite bajo otra vez",
            ),
            orden_historica(
                "A2",
                "2025-11-18T09:00:00-03:00",
                "B-102",
                ["T-B-ACE"],
                texto="otra vez, pedir reten",
            ),
            orden_historica(
                "A3",
                "2025-12-16T09:00:00-03:00",
                "B-102",
                ["NO-ESTANDAR"],
                texto="cambio de reten, se cambio reten del eje",
            ),
        ]
        resultado = procesar(evento_sensor("B-102"), ev, historial, CatalogoTools())

        self.assertEqual(
            [causa.codigo_falla for causa in resultado.causas],
            [causa.codigo_falla for causa in base],
        )
        self.assertIsNone(resultado.orden)
        self.assertIsNone(resultado.reglas)
        self.assertEqual(resultado.problemas, ("SIN_ORDEN",))

    def test_h_emb_real_es_inspeccion_y_da_sin_orden(self):
        ev = evidencia("B-103", [anomalia("B-103", "vibracion", "alta")])
        historial = [
            orden_historica(
                "E1",
                "2026-08-04T15:50:00-03:00",
                "B-103",
                ["T-B-EMP"],
                texto="embolo 3 rayado, pedir tx-emb-57c",
            )
        ]
        resultado = procesar(evento_sensor("B-103"), ev, historial, CatalogoTools())

        h_emb = [c for c in resultado.causas if c.codigo_falla == "H-EMB"]
        self.assertEqual(len(h_emb), 1)
        self.assertIsNone(h_emb[0].tarea_codigo)
        self.assertEqual(h_emb[0].accion, "inspeccion")
        self.assertIsNone(resultado.orden)
        self.assertEqual(resultado.problemas, ("SIN_ORDEN",))

    def test_tarea_no_estandar_generica_queda_pendiente(self):
        ev = evidencia("B-101")
        sintetica = causa("NO-ESTANDAR", "NO-ESTANDAR", "B-101")
        tareas = [
            {
                "codigo": "NO-ESTANDAR",
                "equipos": ["B-101"],
                "detiene": False,
                "repuestos": [],
            }
        ]
        catalogo = CatalogoFalso(
            tareas=tareas, stock={"B-101": (item_stock("TX-EMP-KIT"),)}
        )
        with patch("sistema.flujo.causas_probables", return_value=[sintetica]), patch(
            "sistema.flujo.evaluar",
            return_value=(EstadoOrden.pendiente, "TAREA_NO_ESTANDAR"),
        ):
            resultado = procesar(evento_sensor("B-101"), ev, [], catalogo)

        self.assertIsNotNone(resultado.orden)
        self.assertEqual(resultado.orden.tareas, ["NO-ESTANDAR"])
        self.assertIn("TAREA_NO_ESTANDAR", resultado.pendiente_por)
        self.assertEqual(resultado.orden.estado, EstadoOrden.pendiente)
        self.assertEqual(resultado.problemas, ())

    def test_repuesto_faltante_no_anula_orden(self):
        ev = evidencia("B-101")
        tareas = [
            {
                "codigo": "T-B-ACE",
                "equipos": ["B-101"],
                "detiene": False,
                "repuestos": [{"codigo": "NO-STOCK", "cantidad": 1}],
            }
        ]
        catalogo = CatalogoFalso(
            tareas=tareas, stock={"B-101": (item_stock("OTRO"),)}
        )
        with patch(
            "sistema.flujo.causas_probables",
            return_value=[causa("F04", "T-B-ACE", "B-101")],
        ):
            resultado = procesar(evento_sensor("B-101"), ev, [], catalogo)

        self.assertIsNotNone(resultado.orden)
        self.assertEqual(resultado.orden.repuestos, [])
        self.assertIn("REPUESTO_FALTANTE", resultado.pendiente_por)
        self.assertEqual(resultado.orden.estado, EstadoOrden.pendiente)
        self.assertIn("REPUESTO_FALTANTE", resultado.orden.motivo)

    def test_tarea_valida_con_stock_vacio_no_es_sin_catalogo(self):
        ev = evidencia("B-101")
        tareas = [
            {
                "codigo": "T-B-ACE",
                "equipos": ["B-101"],
                "detiene": False,
                "repuestos": [],
            }
        ]
        catalogo = CatalogoFalso(tareas=tareas, stock={"B-101": ()})
        with patch(
            "sistema.flujo.causas_probables",
            return_value=[causa("F04", "T-B-ACE", "B-101")],
        ):
            resultado = procesar(evento_sensor("B-101"), ev, [], catalogo)

        self.assertIsNotNone(resultado.orden)
        self.assertEqual(resultado.problemas, ())
        self.assertEqual(resultado.pendiente_por, ())
        self.assertEqual(resultado.orden.repuestos, [])

    def test_equipo_sin_catalogo(self):
        ev = evidencia("B-101")
        with patch(
            "sistema.flujo.causas_probables",
            return_value=[causa("F99", "T-F-CAR", "F-999")],
        ):
            resultado = procesar(evento_sensor("B-101"), ev, [], CatalogoFalso())

        self.assertIsNone(resultado.orden)
        self.assertIsNone(resultado.reglas)
        self.assertEqual(resultado.problemas, ("EQUIPO_SIN_CATALOGO",))

    def test_determinismo(self):
        ev = evidencia(
            "B-101",
            [
                anomalia("B-101", "presion_succion", "baja"),
                anomalia("B-101", "vibracion", "alta"),
                anomalia("F-201A", "presion_diferencial", "alta"),
            ],
        )
        primero = procesar(evento_sensor("B-101"), ev, [], CatalogoTools())
        segundo = procesar(evento_sensor("B-101"), ev, [], CatalogoTools())

        self.assertIsNotNone(primero.orden)
        self.assertEqual(primero.orden.id, segundo.orden.id)
