import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from planta_contrato import (
    EstadoOrden,
    EventoSistema,
    NotaRecorrida,
    OrdenSistema,
    TipoEvento,
    Topicos,
)

from sistema.anomalias_recientes import AlmacenAnomalias
from sistema.causas import Anomalia, EvidenciaEquipo
from sistema.config import POSTGRES_DSN
from sistema.coordinador import CoordinadorPartes
from sistema.flujo import ResultadoFlujo
from sistema.ordenes import ErrorEstadoEsperado
from sistema.ordenes_worker import WorkerOrdenes
from sistema.parte import ItemParte
from sistema.repositorio_ordenes import (
    ESTADOS_ABIERTOS,
    ErrorPersistenciaOrden,
    RepositorioOrdenesPostgres,
)
from sistema.tools import ErrorInfo, stock, tareas_catalogo

from test_catalogo import DATOS
from sistema.catalogo import CatalogoPlanta
from test_coordinador import ClienteFalso, RepositorioMemoria

TS = datetime(2026, 11, 20, 14, 0, tzinfo=timezone.utc)
BOMBAS_CON_RESERVA = {"B-101": "marcha", "B-102": "parada", "B-103": "marcha"}
SUFIJO = uuid.uuid4().hex[:10]


def _id(nombre: str) -> str:
    return f"test-worker-ordenes-{SUFIJO}-{nombre}"


def _contar(repositorio, orden_id: str) -> int:
    conexion = repositorio._abrir_conexion()
    try:
        with conexion.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM ordenes WHERE id = %s", (orden_id,))
            fila = cursor.fetchone()
        conexion.commit()
        return int(fila[0])
    finally:
        conexion.close()


class RepositorioOrdenesFalso:
    def __init__(self, abiertas=()):
        self.abiertas = list(abiertas)
        self.guardadas = []

    def guardar(self, orden):
        self.guardadas.append(orden)
        self.abiertas.append(orden)

    def guardar_si_estado(self, orden, estado_esperado):
        self.guardadas.append(orden)
        self.abiertas.append(orden)
        return True

    def obtener(self, orden_id):
        return next((orden for orden in self.abiertas if orden.id == orden_id), None)

    def cargar_pendientes(self):
        return []

    def ordenes_abiertas(self, equipo):
        return [
            orden
            for orden in self.abiertas
            if orden.equipo == equipo and orden.estado in ESTADOS_ABIERTOS
        ]


class RepositorioConError(RepositorioOrdenesFalso):
    def __init__(self, error, fallos=1):
        super().__init__()
        self.error = error
        self.fallos = fallos
        self.intentos = 0

    def guardar(self, orden):
        self.intentos += 1
        if self.intentos <= self.fallos:
            raise self.error
        super().guardar(orden)


class PublicadorFalso:
    def __init__(self):
        self.publicados = []

    def __call__(self, topico, modelo):
        self.publicados.append((topico, modelo))

    def ordenes(self):
        return [modelo for topico, modelo in self.publicados if topico == Topicos.ORDENES]


class CatalogoFalso:
    def tareas_catalogo(self):
        return tareas_catalogo()

    def tareas_no_estandar(self):
        return []

    def stock(self, equipo):
        return stock(equipo).items


def evento_nota(evento_id="EV-NOTA"):
    return EventoSistema(
        id=evento_id,
        ts=TS,
        tipo=TipoEvento.escalado,
        equipo="B-101",
        origen="parte",
        nota_ids=["NOTA-1"],
        resumen="Anomalía informada en la recorrida",
    )


def evento_sensor(evento_id="EV-SENSOR"):
    return EventoSistema(
        id=evento_id,
        ts=TS,
        tipo=TipoEvento.escalado,
        equipo="B-101",
        origen="sensor",
        resumen="desvío de temperatura de aceite",
    )


def evidencia_nota():
    return EvidenciaEquipo(
        equipo="B-101",
        desde=TS - timedelta(minutes=30),
        hasta=TS,
        partes=(
            ItemParte(
                "B-101",
                "goteo_empaquetadura",
                None,
                "gotas/min",
                "goteo por empaquetadura",
            ),
        ),
    )


def evidencia_sensor():
    return EvidenciaEquipo(
        equipo="B-101",
        desde=TS - timedelta(minutes=30),
        hasta=TS,
        anomalias=(Anomalia("B-101", "temperatura_aceite", TS, "alta"),),
    )


def orden_abierta(orden_id, estado=EstadoOrden.aprobada, tareas=("T-B-EMP",)):
    return OrdenSistema(
        id=orden_id,
        ts=TS,
        estado=estado,
        equipo="B-101",
        evento_ids=[f"evt-{orden_id}"],
        tareas=list(tareas),
        detiene_equipo=True,
        reduce_inyeccion=False,
        ejecutor="propio",
        repuestos=[],
    )


def esperar(funcion, limite=2.0):
    fin = time.time() + limite
    while time.time() < fin:
        if funcion():
            return
        time.sleep(0.01)
    raise AssertionError("la condición no se cumplió a tiempo")


class TestWorkerOrdenes(unittest.TestCase):
    def setUp(self):
        self.parche = patch("sistema.causas.verificar_cita", return_value=True)
        self.parche.start()
        self.addCleanup(self.parche.stop)
        self.publicador = PublicadorFalso()
        self.catalogo = CatalogoFalso()
        self.workers = []

    def tearDown(self):
        for worker in self.workers:
            worker.detener()
            worker.join(timeout=2)

    def _worker(self, repositorio, estado=None, historial=None, procesar=None):
        worker = WorkerOrdenes(
            self.publicador,
            repositorio,
            catalogo=self.catalogo,
            estado_bombas=estado or (lambda: BOMBAS_CON_RESERVA),
            historial=historial or (lambda equipo: []),
            procesar=procesar,
        )
        worker.start()
        self.workers.append(worker)
        return worker

    def test_nota_con_evidencia_publica_una_orden(self):
        repositorio = RepositorioOrdenesFalso()
        worker = self._worker(repositorio)

        worker.encolar(evento_nota(), evidencia_nota(), False)

        esperar(lambda: len(self.publicador.ordenes()) == 1)
        orden = self.publicador.ordenes()[0]
        self.assertEqual(orden.tareas, ["T-B-EMP"])
        self.assertEqual(orden.estado, EstadoOrden.aprobada)
        self.assertEqual(len(repositorio.guardadas), 1)

    def test_repetir_mismo_evento_no_duplica(self):
        repositorio = RepositorioOrdenesFalso()
        worker = self._worker(repositorio)

        worker.encolar(evento_nota(), evidencia_nota(), False)
        esperar(lambda: len(self.publicador.ordenes()) == 1)
        worker.encolar(evento_nota(), evidencia_nota(), False)
        time.sleep(0.1)

        self.assertEqual(len(self.publicador.ordenes()), 1)
        self.assertEqual(len(repositorio.guardadas), 1)

    def test_desvio_de_sensor_publica_una_orden(self):
        repositorio = RepositorioOrdenesFalso()
        worker = self._worker(repositorio)

        worker.encolar(evento_sensor(), evidencia_sensor(), False)

        esperar(lambda: len(self.publicador.ordenes()) == 1)
        orden = self.publicador.ordenes()[0]
        self.assertEqual(orden.tareas, ["T-B-ACE"])
        self.assertEqual(orden.estado, EstadoOrden.aprobada)

    def test_orden_abierta_mismo_equipo_y_tareas_no_crea_otra(self):
        repositorio = RepositorioOrdenesFalso([orden_abierta("ORD-ABIERTA")])
        worker = self._worker(repositorio)

        worker.encolar(evento_nota("EV-OTRO"), evidencia_nota(), False)
        time.sleep(0.1)

        self.assertEqual(self.publicador.ordenes(), [])
        self.assertEqual(len(repositorio.guardadas), 0)

    def test_caida_del_estado_de_bombas_queda_pendiente(self):
        repositorio = RepositorioOrdenesFalso()
        worker = self._worker(repositorio, estado=lambda: None)

        worker.encolar(evento_nota(), evidencia_nota(), False)

        esperar(lambda: len(self.publicador.ordenes()) == 1)
        orden = self.publicador.ordenes()[0]
        self.assertEqual(orden.estado, EstadoOrden.pendiente)
        self.assertIn("REDUCE_INYECCION", orden.motivo)

    def test_nota_con_fotos_queda_pendiente(self):
        repositorio = RepositorioOrdenesFalso()
        worker = self._worker(repositorio)

        worker.encolar(evento_nota(), evidencia_nota(), True)

        esperar(lambda: len(self.publicador.ordenes()) == 1)
        orden = self.publicador.ordenes()[0]
        self.assertEqual(orden.estado, EstadoOrden.pendiente)
        self.assertIn("FOTOS_PENDIENTES", orden.motivo)

    def test_worker_ordenes_reintenta_si_publicar_falla(self):
        error = ErrorPersistenciaOrden("guardar orden", RuntimeError("postgres caído"))
        repositorio = RepositorioConError(error, fallos=2)
        worker = self._worker(repositorio)

        with patch("sistema.ordenes_worker.time") as tiempo:
            worker.encolar(evento_nota(), evidencia_nota(), False)
            esperar(
                lambda: repositorio.intentos == 3
                and len(self.publicador.ordenes()) == 1
            )

        self.assertEqual(repositorio.intentos, 3)
        self.assertEqual(tiempo.sleep.call_count, 2)
        self.assertEqual(len(self.publicador.ordenes()), 1)

    def test_worker_ordenes_no_reintenta_estado_esperado(self):
        error = ErrorEstadoEsperado("ORD-1", EstadoOrden.pendiente)
        repositorio = RepositorioConError(error)
        worker = self._worker(repositorio)

        with patch("sistema.ordenes_worker.time") as tiempo:
            worker.encolar(evento_nota(), evidencia_nota(), False)
            esperar(lambda: repositorio.intentos == 1)
            time.sleep(0.05)

        self.assertEqual(repositorio.intentos, 1)
        tiempo.sleep.assert_not_called()
        self.assertEqual(self.publicador.ordenes(), [])

    def test_timeout_de_herramienta_avisa_tablet_y_no_reprocesa(self):
        repositorio = RepositorioOrdenesFalso()
        procesar = MagicMock(
            side_effect=ErrorInfo("API_TIMEOUT", "historian lento", False)
        )
        worker = self._worker(repositorio, procesar=procesar)

        worker.encolar(evento_nota(), evidencia_nota(), False)
        esperar(lambda: len(self.publicador.publicados) == 1)
        time.sleep(0.05)

        self.assertEqual(self.publicador.ordenes(), [])
        self.assertEqual(self.publicador.publicados[0][0], Topicos.TABLET)
        self.assertEqual(procesar.call_count, 1)
        self.assertEqual(repositorio.guardadas, [])

    def test_deadline_guarda_orden_pendiente_sin_publicarla(self):
        repositorio = RepositorioOrdenesFalso()
        orden = orden_abierta(_id("deadline"), estado=EstadoOrden.pendiente)
        procesar = MagicMock(
            return_value=ResultadoFlujo(
                [], orden, None, ("LIMITE_TIEMPO",), ("LIMITE_TIEMPO",)
            )
        )
        worker = self._worker(repositorio, procesar=procesar)

        worker.encolar(evento_nota(), evidencia_nota(), False)
        esperar(lambda: len(self.publicador.publicados) == 1)
        time.sleep(0.05)

        self.assertEqual(repositorio.guardadas, [orden])
        self.assertEqual(self.publicador.ordenes(), [])
        self.assertEqual(self.publicador.publicados[0][0], Topicos.TABLET)
        self.assertEqual(orden.estado, EstadoOrden.pendiente)


@unittest.skipUnless(POSTGRES_DSN, "POSTGRES_DSN no configurado")
class TestReinicioOrdenesPostgres(unittest.TestCase):
    def test_orden_sobrevive_reinicio_sin_duplicar(self):
        repositorio = RepositorioOrdenesPostgres(POSTGRES_DSN)
        orden = orden_abierta(_id("reinicio"), estado=EstadoOrden.pendiente)
        try:
            repositorio.guardar(orden)

            nuevo_worker = WorkerOrdenes(
                PublicadorFalso(),
                repositorio,
                catalogo=CatalogoFalso(),
                estado_bombas=lambda: BOMBAS_CON_RESERVA,
                historial=lambda equipo: [],
            )

            pendientes = repositorio.cargar_pendientes()
            recuperada = next((item for item in pendientes if item.id == orden.id), None)
            self.assertIs(nuevo_worker._repositorio, repositorio)
            self.assertIsNotNone(recuperada)
            self.assertEqual(recuperada.id, orden.id)
            self.assertIs(recuperada.estado, EstadoOrden.pendiente)
            self.assertEqual(_contar(repositorio, orden.id), 1)
        finally:
            repositorio._ejecutar(
                "limpiar prueba de reinicio",
                "DELETE FROM ordenes WHERE id = %s",
                (orden.id,),
            )
            repositorio.cerrar()


class TestCoordinadorConWorker(unittest.TestCase):
    def test_nota_con_evidencia_encola_una_orden(self):
        cliente = ClienteFalso()
        repositorio = RepositorioOrdenesFalso()
        almacen = AlmacenAnomalias()
        encolados = []
        coordinador = CoordinadorPartes(
            cliente,
            RepositorioMemoria(),
            CatalogoPlanta.desde_datos(DATOS),
            almacen_anomalias=almacen,
            encolar_orden=lambda evento, evidencia, fotos: encolados.append(
                (evento, evidencia, fotos)
            ),
        )

        nota = NotaRecorrida(
            id="NOTA-1",
            ts=TS,
            operador="operador-1",
            audio_url=None,
            fotos=[],
            recorrida_id="REC-1",
        )
        coordinador.procesar_nota(
            nota,
            "La uno gotea por la empaquetadura.",
            [],
        )
        self.assertEqual(len(encolados), 1)
        evento, evidencia, fotos = encolados[0]
        self.assertEqual(evento.equipo, "B-101")
        self.assertEqual(evidencia.equipo, "B-101")
        self.assertFalse(fotos)


if __name__ == "__main__":
    unittest.main()
