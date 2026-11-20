from __future__ import annotations

import hashlib
import time
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from planta_contrato import EstadoOrden, NotaCierre, OrdenSistema, Topicos

from sistema.causas import Causa, EvidenciaEquipo
from sistema.cierres import aplicar_cierre
from sistema.cli import main as cli_main
from sistema.coordinador import CoordinadorPartes
from sistema.flujo import ResultadoFlujo, procesar
from sistema.ordenes_worker import TrabajoOrden, WorkerOrdenes
from sistema.repositorio_decisiones import (
    MODELO_HUMANO,
    MODELO_REGLAS,
    RegistroDecisionesMemoria,
    RepositorioDecisionesPostgres,
    argumentos_manuales_buscar,
    registrar_manuales_buscar,
)
from sistema.tools import StockItem
from test_ordenes import evento_sensor

TS = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
DESDE = TS - timedelta(hours=1)
HASTA = TS
TAREAS = [
    {
        "codigo": "T-B-ACE",
        "nombre": "Cambio de aceite",
        "equipos": ["B-101"],
        "detiene": False,
        "horas": 1.0,
        "ejecutor": "propio",
        "repuestos": [{"codigo": "ACE-ISO220", "cantidad": 1.0}],
    }
]
STOCK = StockItem(
    codigo="ACE-ISO220",
    nombre="Aceite ISO 220",
    unidad="l",
    almacen="yacimiento",
    cantidad=10.0,
    costo_unitario=1.0,
)


def causa_orden() -> Causa:
    return Causa(
        codigo_falla="F04",
        descripcion="F04",
        evidencia=(),
        faltantes=(),
        tarea_codigo="T-B-ACE",
        equipo_orden="B-101",
        citas=(),
        accion="orden",
        genera_orden=True,
        ejecutor="propio",
    )


def orden(estado: EstadoOrden, evento_id: str = "E-1", ejecutor: str = "propio") -> OrdenSistema:
    return OrdenSistema(
        id="O-1",
        ts=TS,
        estado=estado,
        equipo="B-101",
        evento_ids=[evento_id],
        tareas=["T-B-ACE"],
        detiene_equipo=False,
        reduce_inyeccion=False,
        ejecutor=ejecutor,
    )


def nota_cierre(empresa: str = "Contratista") -> NotaCierre:
    return NotaCierre(
        id="CIERRE-1",
        ts=TS,
        orden_id="O-1",
        tecnico="T-1",
        empresa=empresa,
        audio_url=None,
        fotos=[],
    )


class CatalogoFalso:
    def tareas_catalogo(self):
        return TAREAS

    def tareas_no_estandar(self):
        return []

    def stock(self, equipo):
        return [STOCK]


class RepositorioOrdenesFalso:
    def __init__(
        self,
        orden_actual: OrdenSistema | None = None,
        pendientes=(),
    ) -> None:
        self.orden = orden_actual
        self.pendientes = list(pendientes)

    def obtener(self, orden_id):
        return self.orden if self.orden is not None and self.orden.id == orden_id else None

    def guardar(self, orden_actualizada) -> None:
        self.orden = orden_actualizada

    def guardar_si_estado(self, orden_actualizada, estado_esperado) -> bool:
        if self.orden is None or self.orden.estado is not estado_esperado:
            return False
        self.orden = orden_actualizada
        return True

    def cargar_pendientes(self):
        return list(self.pendientes)

    def ordenes_abiertas(self, equipo):
        return []


class ClienteFalso:
    def __init__(self) -> None:
        self.publicados = []

    def publicar(self, topico, modelo) -> None:
        self.publicados.append((topico, modelo))


class RegistroQueFalla:
    def registrar(self, **kwargs) -> None:
        raise RuntimeError("postgres caído")

    def listar(self, correlation_id):
        return []


class UndefinedTable(Exception):
    pass


class CursorFalso:
    def __init__(self) -> None:
        self.parametros = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.parametros.append(params)
        if len(self.parametros) == 1:
            raise UndefinedTable('relation "decisiones" does not exist')


class ConexionFalso:
    def __init__(self) -> None:
        self.cursor_falso = CursorFalso()

    def cursor(self):
        return self.cursor_falso

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


class TestRepositorioDecisiones(unittest.TestCase):
    def test_listar_devuelve_filas_en_orden_temporal_e_ids_distintos(self):
        registro = RegistroDecisionesMemoria()
        registro.registrar(correlation_id="E-1", paso="causas_probables")
        registro.registrar(correlation_id="E-1", paso="evaluar")
        registro.registrar(correlation_id="E-2", paso="evaluar")

        filas = registro.listar("E-1")

        self.assertEqual([fila.paso for fila in filas], ["causas_probables", "evaluar"])
        self.assertEqual(len({fila.id for fila in filas}), 2)
        self.assertTrue(all(fila.correlation_id == "E-1" for fila in filas))

    def test_manuales_buscar_solo_registra_longitud_y_hash(self):
        registro = RegistroDecisionesMemoria()
        texto = "texto secreto del operador"

        encontrado = registrar_manuales_buscar(
            registro, "E-1", texto, lambda valor: valor
        )
        fila = registro.listar("E-1")[0]

        self.assertEqual(encontrado, texto)
        self.assertEqual(
            fila.argumentos,
            argumentos_manuales_buscar(texto),
        )
        self.assertNotIn("secreto", str(fila.argumentos))
        self.assertEqual(
            fila.argumentos["sha256"],
            hashlib.sha256(texto.encode("utf-8")).hexdigest()[:12],
        )

    def test_registrar_con_conexion_que_falla_es_fail_fast(self):
        repositorio = RepositorioDecisionesPostgres("dsn-invalido")

        def conectar_fallido(*args, **kwargs):
            raise OSError("sin base")

        modulo = SimpleNamespace(connect=conectar_fallido)
        with patch("sistema.repositorio_decisiones.time.sleep") as dormir:
            with patch.object(
                RepositorioDecisionesPostgres, "_psycopg", return_value=modulo
            ):
                with patch("sistema.repositorio_decisiones.log") as bitacora:
                    inicio = time.perf_counter()
                    repositorio.registrar(correlation_id="E-1", paso="evaluar")
                    transcurrido = time.perf_counter() - inicio

        dormir.assert_not_called()
        bitacora.exception.assert_called_once()
        self.assertLess(transcurrido, 1.0)

    def test_ids_distintos_entre_instancias_para_la_misma_terna(self):
        primer_ts = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
        segundo_ts = datetime(2026, 11, 20, 12, 0, 1, tzinfo=timezone.utc)

        with patch("sistema.repositorio_decisiones.datetime") as fecha:
            fecha.now.side_effect = [primer_ts, segundo_ts]
            primer_id = RepositorioDecisionesPostgres("dsn")._clave("E-1", "evaluar")[0]
            segundo_id = RepositorioDecisionesPostgres("dsn")._clave("E-1", "evaluar")[0]

        self.assertNotEqual(primer_id, segundo_id)

    def test_reintento_del_mismo_insert_conserva_el_id(self):
        repositorio = RepositorioDecisionesPostgres("dsn")
        conexion = ConexionFalso()

        with patch.object(
            RepositorioDecisionesPostgres, "_abrir_conexion", return_value=conexion
        ):
            with patch.object(RepositorioDecisionesPostgres, "_crear_tablas"):
                repositorio.registrar(correlation_id="E-1", paso="evaluar")

        parametros = conexion.cursor_falso.parametros
        self.assertEqual(len(parametros), 2)
        self.assertEqual(parametros[0][0], parametros[1][0])


class TestFlujoConRegistro(unittest.TestCase):
    def _procesar(self, registro):
        evento = evento_sensor(equipo="B-101", evento_id="E-1")
        evidencia = EvidenciaEquipo("B-101", DESDE, HASTA, ())
        with patch("sistema.flujo.causas_probables", return_value=[causa_orden()]):
            return procesar(
                evento,
                evidencia,
                [],
                CatalogoFalso(),
                {"B-101": "marcha"},
                registro=registro,
            )

    def test_registra_etapas_y_tools_con_modelo_reglas(self):
        registro = RegistroDecisionesMemoria()

        resultado = self._procesar(registro)
        filas = registro.listar("E-1")

        self.assertIsNotNone(resultado.orden)
        pasos = {fila.paso for fila in filas}
        self.assertTrue(
            {
                "causas_probables",
                "reordenar_con_historial",
                "construir_orden",
                "evaluar",
                "validar_orden_publicable",
            }.issubset(pasos)
        )
        herramientas = {fila.herramienta for fila in filas if fila.herramienta}
        self.assertTrue(
            {"tareas_catalogo", "materiales", "stock"}.issubset(herramientas)
        )
        self.assertTrue(
            all(
                fila.modelo == MODELO_REGLAS
                and fila.tokens == 0
                and fila.costo_usd == 0.0
                for fila in filas
            )
        )

    def test_registro_que_falla_no_cambia_resultado(self):
        sin_registro = self._procesar(None)
        con_registro_que_falla = self._procesar(RegistroQueFalla())

        self.assertEqual(con_registro_que_falla, sin_registro)


class TestPublicacionYCierreConRegistro(unittest.TestCase):
    def test_worker_registra_publicar_orden_con_correlation_del_evento(self):
        registro = RegistroDecisionesMemoria()
        evento = evento_sensor(equipo="B-101", evento_id="E-W")
        orden_publicada = orden(EstadoOrden.aprobada, evento_id="E-W")
        repositorio = RepositorioOrdenesFalso()
        cliente = ClienteFalso()

        def procesar_falso(*args, **kwargs):
            return ResultadoFlujo([], orden_publicada, None, (), ())

        worker = WorkerOrdenes(
            cliente.publicar,
            repositorio,
            catalogo=CatalogoFalso(),
            historial=lambda equipo: [],
            estado_bombas=lambda: {},
            procesar=procesar_falso,
            registro=registro,
        )
        worker._procesar_trabajo(
            TrabajoOrden(evento, EvidenciaEquipo("B-101", DESDE, HASTA, ()))
        )

        filas = registro.listar("E-W")
        self.assertEqual([fila.paso for fila in filas], ["publicar_orden"])
        self.assertEqual(len(cliente.publicados), 1)

    def test_coordinador_registra_publicar_orden_al_reanudar(self):
        registro = RegistroDecisionesMemoria()
        pendiente = orden(EstadoOrden.pendiente, evento_id="E-C")
        repositorio = RepositorioOrdenesFalso(pendientes=[pendiente])
        cliente = ClienteFalso()

        coordinador = CoordinadorPartes(
            cliente,
            None,
            None,
            repositorio_ordenes=repositorio,
            registro=registro,
        )
        coordinador.reanudar_pendientes()

        filas = registro.listar("E-C")
        self.assertEqual([fila.paso for fila in filas], ["publicar_orden"])

    def test_cierre_y_certificacion_comparten_correlation(self):
        registro = RegistroDecisionesMemoria()
        repositorio = RepositorioOrdenesFalso(
            orden(EstadoOrden.aprobada, ejecutor="contratista")
        )
        cliente = ClienteFalso()

        aplicar_cierre(
            nota_cierre(), repositorio, cliente.publicar, registro=registro
        )
        codigo = cli_main(
            [
                "certificar",
                "O-1",
                "--por",
                "LICETTE",
                "--habilita",
                "HAB-2026-0001",
                "--monto",
                "100",
            ],
            repositorio=repositorio,
            cliente=cliente,
            registro=registro,
        )

        self.assertEqual(codigo, 0)
        filas = registro.listar("E-1")
        self.assertEqual([fila.paso for fila in filas], ["aplicar_cierre", "certificar"])

    def test_cli_registra_decision_humana_sin_texto_libre(self):
        casos = (
            ("aprobar", EstadoOrden.pendiente, ["--por", "LICETTE"]),
            (
                "rechazar",
                EstadoOrden.pendiente,
                ["--por", "LICETTE", "--motivo", "motivo confidencial"],
            ),
            (
                "certificar",
                EstadoOrden.ejecutada,
                [
                    "--por",
                    "LICETTE",
                    "--habilita",
                    "HAB-2026-0001",
                    "--monto",
                    "100",
                ],
            ),
            (
                "observar",
                EstadoOrden.ejecutada,
                ["--por", "LICETTE", "--motivo", "motivo confidencial"],
            ),
        )
        for comando, estado, opciones in casos:
            with self.subTest(comando=comando):
                registro = RegistroDecisionesMemoria()
                repositorio = RepositorioOrdenesFalso(
                    orden(estado, ejecutor="contratista")
                )
                codigo = cli_main(
                    [comando, "O-1", *opciones],
                    repositorio=repositorio,
                    cliente=ClienteFalso(),
                    registro=registro,
                )

                filas = registro.listar("E-1")
                self.assertEqual(codigo, 0)
                self.assertEqual(len(filas), 1)
                self.assertEqual(filas[0].modelo, MODELO_HUMANO)
                self.assertEqual(filas[0].paso, comando)
                self.assertEqual(filas[0].tokens, 0)
                self.assertEqual(filas[0].costo_usd, 0.0)
                self.assertNotIn("confidencial", str(filas[0].argumentos))
                self.assertNotIn("LICETTE", str(filas[0].argumentos))
