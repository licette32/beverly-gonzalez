import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

_patch_citas = patch("sistema.causas.verificar_cita", return_value=True)


def setUpModule():
    _patch_citas.start()


def tearDownModule():
    _patch_citas.stop()

from planta_contrato import EstadoOrden
from test_ordenes import evento_sensor

from sistema import flujo as modulo_flujo
from sistema.causas import Anomalia, Causa, EvidenciaEquipo, causas_probables
from sistema.control_flujo import ControlProceso
from sistema.flujo import CatalogoTools, procesar
from sistema.repositorio_decisiones import RegistroDecisionesMemoria
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
    citas=(),
):
    return Causa(
        codigo_falla=codigo_falla,
        descripcion=codigo_falla,
        evidencia=("historial_repetido",),
        faltantes=(),
        tarea_codigo=tarea_codigo,
        equipo_orden=equipo_orden,
        citas=tuple(citas),
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


class TestRevisionPublicacion(ConCitas):
    def _procesar(
        self,
        *,
        citas=(),
        repuestos=(),
        materiales=("ACE-ISO220",),
        verificar=True,
        fragmentos=None,
        ejecutor="propio",
        registro=None,
    ):
        tareas = [
            {
                "codigo": "T-B-ACE",
                "equipos": ["B-101"],
                "detiene": False,
                "repuestos": [
                    {"codigo": codigo, "cantidad": 1.0} for codigo in repuestos
                ],
            }
        ]
        catalogo = CatalogoFalso(
            tareas=tareas,
            stock={"B-101": tuple(item_stock(codigo) for codigo in repuestos)},
        )
        datos_materiales = {"lista_materiales": {"B-101": list(materiales)}}
        fragmentos = {} if fragmentos is None else fragmentos
        with patch(
            "sistema.flujo.causas_probables",
            return_value=[
                causa("F04", "T-B-ACE", "B-101", citas=citas, ejecutor=ejecutor)
            ],
        ), patch(
            "sistema.causas.verificar_cita", return_value=verificar
        ), patch(
            "sistema.tools._fragmentos_manuales", return_value=fragmentos
        ), patch(
            "sistema.flujo.tools._cargar_materiales", return_value=datos_materiales
        ):
            return procesar(
                evento_sensor("B-101"),
                evidencia("B-101"),
                [],
                catalogo,
                registro=registro,
            )

    def test_cita_valida_y_repuesto_en_lista_aprueba(self):
        resultado = self._procesar(
            citas=("TX350-D §3.2",),
            repuestos=("ACE-ISO220",),
        )

        self.assertEqual(resultado.orden.estado, EstadoOrden.aprobada)
        self.assertEqual(resultado.problemas, ())
        self.assertIn("cumple todas las reglas", resultado.orden.motivo)

    def test_cita_inexistente_pasa_a_pendiente(self):
        resultado = self._procesar(citas=("TX350-D §99",), verificar=False)

        self.assertEqual(resultado.orden.estado, EstadoOrden.pendiente)
        self.assertEqual(resultado.problemas, ("CITA_INEXISTENTE",))
        self.assertIn("CITA_INEXISTENTE", resultado.orden.motivo)

    def test_cita_vencida_pasa_a_pendiente(self):
        resultado = self._procesar(
            citas=("TX350-D §3.2",),
            verificar=False,
            fragmentos={"TX350-D §3.2": SimpleNamespace(vigente=False)},
        )

        self.assertEqual(resultado.orden.estado, EstadoOrden.pendiente)
        self.assertEqual(resultado.problemas, ("CITA_VENCIDA",))
        self.assertIn("CITA_VENCIDA", resultado.orden.motivo)

    def test_repuesto_fuera_de_lista_no_duplica_codigo(self):
        with patch(
            "sistema.flujo.evaluar",
            return_value=(EstadoOrden.pendiente, "REPUESTO_FUERA_DE_LISTA"),
        ):
            resultado = self._procesar(repuestos=("FC-CART-25",))

        self.assertEqual(resultado.orden.estado, EstadoOrden.pendiente)
        self.assertEqual(resultado.problemas, ("REPUESTO_FUERA_DE_LISTA",))
        self.assertEqual(
            resultado.orden.motivo.count("REPUESTO_FUERA_DE_LISTA"), 1
        )

    def test_pendiente_por_reglas_y_revisor_conserva_ambos_codigos(self):
        resultado = self._procesar(
            citas=("TX350-D §99",),
            verificar=False,
            ejecutor="contratista",
        )

        self.assertEqual(resultado.orden.estado, EstadoOrden.pendiente)
        self.assertEqual(resultado.problemas, ("CITA_INEXISTENTE",))
        self.assertIn("EJECUTOR_NO_PROPIO", resultado.orden.motivo)
        self.assertIn("CITA_INEXISTENTE", resultado.orden.motivo)


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

    def test_reten_resuelto_no_cambia_causas_y_sale_inspeccion(self):
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
        self.assertEqual(resultado.orden.equipo, "B-102")
        self.assertEqual(resultado.orden.tareas, ["I-VIB"])
        self.assertEqual(resultado.problemas, ())
        self.assertEqual(resultado.orden.estado, EstadoOrden.pendiente)

    def test_h_emb_no_se_inserta_y_sale_inspeccion_actual(self):
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

        self.assertFalse(any(c.codigo_falla == "H-EMB" for c in resultado.causas))
        self.assertIsNotNone(resultado.orden)
        self.assertEqual(resultado.orden.equipo, "B-103")
        self.assertEqual(resultado.orden.tareas, ["I-VIB"])
        self.assertEqual(resultado.problemas, ())
        self.assertEqual(resultado.orden.estado, EstadoOrden.pendiente)

    def test_inspeccion_sin_tarea_no_genera_orden(self):
        ev = evidencia("B-101")
        sintetica = causa("F06", None, "B-101", accion="inspeccion")
        with patch("sistema.flujo.causas_probables", return_value=[sintetica]):
            resultado = procesar(
                evento_sensor("B-101"), ev, [], CatalogoTools()
            )

        self.assertIsNone(resultado.orden)
        self.assertEqual(resultado.problemas, ("SIN_ORDEN",))

    def test_i_val_genera_orden_y_queda_pendiente(self):
        ev = evidencia("B-101")
        sintetica = causa(
            "F02", "I-VAL", "B-101", accion="I-VAL", ejecutor="propio"
        )
        with patch("sistema.flujo.causas_probables", return_value=[sintetica]):
            resultado = procesar(
                evento_sensor("B-101"),
                ev,
                [],
                CatalogoTools(),
                estado_bombas=BOMBAS_CON_RESERVA,
            )

        self.assertIsNotNone(resultado.orden)
        self.assertEqual(resultado.orden.equipo, "B-101")
        self.assertEqual(resultado.orden.tareas, ["I-VAL"])
        self.assertEqual(resultado.orden.estado, EstadoOrden.pendiente)
        self.assertIn("TAREA_NO_ESTANDAR", resultado.orden.motivo)
        self.assertEqual(resultado.problemas, ())

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


class TestControlFlujo(TestRevisionPublicacion):
    def test_deadline_antes_de_construir_devuelve_sin_orden(self):
        control = ControlProceso("EV-CTRL", None, limite_s=0)
        with patch("sistema.flujo.ControlProceso", return_value=control):
            resultado = self._procesar()

        self.assertIsNone(resultado.orden)
        self.assertEqual(resultado.problemas, ("LIMITE_TIEMPO",))

    def test_deadline_despues_de_construir_deja_pendiente_sin_publicar(self):
        estado = {"listo": False}
        real = modulo_flujo.construir_orden

        def construir(*args, **kwargs):
            estado["listo"] = True
            return real(*args, **kwargs)

        class ControlTemporizado(ControlProceso):
            def transcurrido_s(self):
                return 601 if estado["listo"] else 0

        control = ControlTemporizado("EV-CTRL", None, limite_s=600)
        with patch("sistema.flujo.ControlProceso", return_value=control), patch(
            "sistema.flujo.construir_orden", side_effect=construir
        ):
            resultado = self._procesar()

        self.assertIsNotNone(resultado.orden)
        self.assertIs(resultado.orden.estado, EstadoOrden.pendiente)
        self.assertIn("LIMITE_TIEMPO", resultado.orden.motivo)
        self.assertIn("LIMITE_TIEMPO", resultado.problemas)

    def test_loop_antes_de_construir_devuelve_sin_orden(self):
        correlation_id = evento_sensor("B-101").id
        registro = RegistroDecisionesMemoria()
        for _ in range(3):
            registro.registrar(
                correlation_id=correlation_id,
                paso="causas_probables",
                modelo="reglas",
            )
        control = ControlProceso(correlation_id, registro)
        with patch("sistema.flujo.ControlProceso", return_value=control):
            resultado = self._procesar(registro=registro)

        self.assertIsNone(resultado.orden)
        self.assertEqual(resultado.problemas, ("LOOP_DETECTADO",))
        self.assertTrue(
            any(fila.paso == "loop" for fila in registro.listar(correlation_id))
        )

    def test_loop_despues_de_construir_deja_pendiente(self):
        correlation_id = evento_sensor("B-101").id
        registro = RegistroDecisionesMemoria()
        for _ in range(3):
            registro.registrar(
                correlation_id=correlation_id,
                paso="construir_orden",
                modelo="reglas",
            )
        control = ControlProceso(correlation_id, registro)
        with patch("sistema.flujo.ControlProceso", return_value=control):
            resultado = self._procesar(registro=registro)

        self.assertIsNotNone(resultado.orden)
        self.assertIs(resultado.orden.estado, EstadoOrden.pendiente)
        self.assertIn("LOOP_DETECTADO", resultado.orden.motivo)
        self.assertIn("LOOP_DETECTADO", resultado.pendiente_por)

    def test_pasos_de_control_no_cuentan_como_loop(self):
        correlation_id = "EV-CTRL"
        registro = RegistroDecisionesMemoria()
        argumentos = {
            "limite_s": 600,
            "transcurrido_s": 600.0,
            "etapa": "inicio",
        }
        for paso in ("deadline", "loop", "tool_timeout"):
            for _ in range(3):
                registro.registrar(
                    correlation_id=correlation_id,
                    paso=paso,
                    modelo="control",
                    argumentos=argumentos,
                )
        control = ControlProceso(correlation_id, registro)
        for paso in ("deadline", "loop", "tool_timeout"):
            self.assertFalse(control.detectar_loop(paso, None, argumentos))
        self.assertEqual(len(registro.listar(correlation_id)), 9)

    def test_argumentos_distingue_las_dos_llamadas_de_materiales(self):
        correlation_id = evento_sensor("B-101").id
        registro = RegistroDecisionesMemoria()
        self._procesar(registro=registro)

        filas = [
            fila
            for fila in registro.listar(correlation_id)
            if fila.paso == "materiales"
        ]
        self.assertEqual(
            {(fila.herramienta, fila.argumentos["fuente"]) for fila in filas},
            {
                ("materiales", "tareas_no_estandar"),
                ("materiales", "_cargar_materiales"),
            },
        )
