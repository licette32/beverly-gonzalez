import copy
import unittest
from datetime import datetime, timedelta, timezone

from planta_contrato import Calidad, EventoSistema, LecturaSensor, TipoEvento, Topicos

from sistema.anomalias import ParametrosDeteccion
from sistema.catalogo import EstadoPlanta
from sistema.eventos_sensores import DetectorSensores, WorkerSensores
from sistema.sensores import VentanaSensores

BASE = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
CLAVE = ("B-101", "presion_descarga")
LIMITES = {CLAVE: {"alarma_alta": 125.0, "alarma_baja": 95.0}}
PARAMETROS = ParametrosDeteccion(ventana_min=30, minimo_fuera=6, span_min=10)
MUESTRA_ESTADO = {
    "ts": "2026-11-03T07:30:00-03:00",
    "bombas": [
        {"tag": "B-101", "estado": "marcha", "pd": 114.5},
        {"tag": "B-102", "estado": "marcha", "pd": 114.5},
        {"tag": "B-103", "estado": "parada", "pd": 1.5},
    ],
    "filtros": [
        {"tag": "F-201A", "en_cambio": False},
        {"tag": "F-201B", "en_cambio": False},
    ],
    "enlace_arriba": True,
}


def lectura(
    minutos: float,
    valor: float = 110.0,
    calidad: Calidad = Calidad.buena,
) -> LecturaSensor:
    return LecturaSensor(
        tag="B-101",
        variable="presion_descarga",
        valor=valor,
        unidad="kg/cm2",
        ts=BASE + timedelta(minutes=minutos),
        calidad=calidad,
    )


def ventana_de(lecturas: list[LecturaSensor]) -> VentanaSensores:
    ventana = VentanaSensores(6, 500)
    for item in lecturas:
        ventana.registrar(item)
    return ventana


class ClienteFalso:
    def __init__(self) -> None:
        self.publicados = []

    def publicar(self, topico, modelo) -> None:
        self.publicados.append((topico, modelo))


class EstadoPlantaFalso(EstadoPlanta):
    def __init__(self, respuestas) -> None:
        super().__init__()
        self.respuestas = list(respuestas)

    def _leer(self, url):
        respuesta = self.respuestas.pop(0)
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta


class TestEventosSensores(unittest.TestCase):
    def setUp(self):
        lecturas = [lectura(minutos) for minutos in range(0, 28, 3)]
        lecturas += [lectura(minutos, 130.0) for minutos in range(30, 48, 3)]
        self.ventana = ventana_de(lecturas)
        self.detector = DetectorSensores(self.ventana, LIMITES, PARAMETROS)

    def evaluar(self):
        return self.detector.evaluar("B-101", "presion_descarga")

    def test_idempotencia_y_contrato(self):
        evento = self.evaluar()

        self.assertIsNotNone(evento)
        EventoSistema.model_validate(evento.model_dump(mode="json"))
        self.assertEqual(evento.tipo, TipoEvento.escalado)
        self.assertEqual(evento.origen, "sensor")
        self.assertEqual(evento.equipo, "B-101")
        self.assertEqual(evento.nota_ids, [])
        self.assertIsNone(evento.parte_id)
        self.assertEqual(evento.ts, BASE + timedelta(minutes=45))
        self.assertIn("fuera de alarma_alta=125.0", evento.resumen)
        self.assertIn(
            "6 lecturas entre 2030-01-01T12:30:00+00:00 y "
            "2030-01-01T12:45:00+00:00",
            evento.resumen,
        )
        self.assertIn("valores 110–130 kg/cm2, última 130", evento.resumen)

        self.assertIsNone(self.evaluar())
        self.assertEqual(self.detector.activo("B-101", "presion_descarga"), evento)

    def test_reaparicion_genera_evento_nuevo(self):
        primero = self.evaluar()
        self.assertIsNotNone(primero)

        self.ventana.registrar(lectura(48))
        self.assertIsNone(self.evaluar())
        self.assertIsNone(self.detector.activo("B-101", "presion_descarga"))

        for minutos in range(51, 67, 3):
            self.ventana.registrar(lectura(minutos, 130.0))
        segundo = self.evaluar()

        self.assertIsNotNone(segundo)
        self.assertNotEqual(segundo.id, primero.id)
        self.assertEqual(segundo.ts, BASE + timedelta(minutes=66))
        self.assertIn("2030-01-01T12:51:00+00:00", segundo.resumen)

    def test_desvio_mayor_a_30_minutos_conserva_el_id(self):
        primero = self.evaluar()
        self.assertIsNotNone(primero)

        for minutos in range(48, 91, 3):
            self.ventana.registrar(lectura(minutos, 130.0))
        self.assertIsNone(self.evaluar())

        activo = self.detector.activo("B-101", "presion_descarga")
        self.assertIsNotNone(activo)
        self.assertEqual(activo.id, primero.id)
        self.assertEqual(activo.ts, primero.ts)


class TestWorkerSensores(unittest.TestCase):
    def test_encolar_no_duplica_clave_pendiente(self):
        ventana = ventana_de([])
        worker = WorkerSensores(ClienteFalso(), ventana, LIMITES, PARAMETROS)

        worker.encolar(lectura(0))
        worker.encolar(lectura(3))

        self.assertEqual(worker._cola.qsize(), 1)
        self.assertEqual(worker._pendientes, {CLAVE})


class TestEstadoPlanta(unittest.TestCase):
    def test_muestra_real_excluye_parada_y_filtro_en_cambio(self):
        self.assertEqual(
            EstadoPlanta.desde_datos(MUESTRA_ESTADO), frozenset({"B-103"})
        )

        muestra = copy.deepcopy(MUESTRA_ESTADO)
        muestra["filtros"][0]["en_cambio"] = True
        self.assertEqual(
            EstadoPlanta.desde_datos(muestra),
            frozenset({"B-103", "F-201A"}),
        )

    def test_falla_mantiene_el_ultimo_estado(self):
        estado = EstadoPlantaFalso(
            [
                {
                    "bombas": [
                        {"tag": "B-103", "estado": "parada"},
                        {"tag": "B-101", "estado": "marcha"},
                    ]
                },
                OSError("sin red"),
            ]
        )

        self.assertEqual(estado.excluidos(), frozenset({"B-103"}))
        with self.assertLogs("sistema.catalogo", level="WARNING") as logs:
            self.assertEqual(estado.excluidos(), frozenset({"B-103"}))
        self.assertIn("último estado", "\n".join(logs.output))

    def test_sin_estado_previo_devuelve_none(self):
        estado = EstadoPlantaFalso([OSError("sin red")])

        with self.assertLogs("sistema.catalogo", level="WARNING") as logs:
            self.assertIsNone(estado.excluidos())
        self.assertIn("no hay estado previo", "\n".join(logs.output))

    def test_worker_no_publica_sin_estado_previo(self):
        lecturas = [lectura(minutos) for minutos in range(0, 28, 3)]
        lecturas += [lectura(minutos, 130.0) for minutos in range(30, 48, 3)]
        ventana = ventana_de(lecturas)
        cliente = ClienteFalso()
        estado = EstadoPlantaFalso([OSError("sin red")])
        worker = WorkerSensores(
            cliente, ventana, LIMITES, PARAMETROS, estado=estado
        )

        with self.assertLogs("sistema.catalogo", level="WARNING"):
            worker._procesar(CLAVE)

        self.assertEqual(cliente.publicados, [])

    def test_worker_publica_evento_valido(self):
        lecturas = [lectura(minutos) for minutos in range(0, 28, 3)]
        lecturas += [lectura(minutos, 130.0) for minutos in range(30, 48, 3)]
        ventana = ventana_de(lecturas)
        cliente = ClienteFalso()
        estado = EstadoPlantaFalso(
            [{"bombas": [{"tag": "B-101", "estado": "marcha"}]}]
        )
        worker = WorkerSensores(
            cliente, ventana, LIMITES, PARAMETROS, estado=estado
        )

        worker._procesar(CLAVE)

        self.assertEqual(len(cliente.publicados), 1)
        topico, evento = cliente.publicados[0]
        self.assertEqual(topico, Topicos.EVENTOS)
        EventoSistema.model_validate(evento.model_dump(mode="json"))
        self.assertEqual(evento.origen, "sensor")


if __name__ == "__main__":
    unittest.main()
