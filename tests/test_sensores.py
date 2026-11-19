import threading
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from planta_contrato import Calidad, LecturaSensor

from sistema.mqtt import ClienteMQTT
from sistema.sensores import VentanaSensores

BASE = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)


def lectura(
    minutos: int = 0,
    tag: str = "B-102",
    variable: str = "presion_descarga",
    valor: float | None = 1.0,
    calidad: Calidad = Calidad.buena,
) -> LecturaSensor:
    return LecturaSensor(
        tag=tag,
        variable=variable,
        valor=valor,
        unidad="kg/cm2",
        ts=BASE + timedelta(minutes=minutos),
        calidad=calidad,
    )


class TestVentanaSensores(unittest.TestCase):
    def test_llenado_por_clave(self):
        ventana = VentanaSensores(horizonte_horas=6, max_lecturas=500)
        l0 = lectura(0)
        l1 = lectura(1, valor=None, calidad=Calidad.sin_dato)
        l2 = lectura(2)
        for item in (l0, l1, l2):
            ventana.registrar(item)
        ventana.registrar(lectura(0, tag="T-350", variable="temperatura"))

        self.assertEqual(ventana.ventana("B-102", "presion_descarga"), (l0, l1, l2))
        self.assertEqual(
            ventana.ventana("T-350", "temperatura"),
            (lectura(0, tag="T-350", variable="temperatura"),),
        )
        self.assertEqual(
            ventana.claves(),
            [("B-102", "presion_descarga"), ("T-350", "temperatura")],
        )
        self.assertEqual(ventana.ventana("NO-EXISTE", "variable"), ())

    def test_desborde_por_cantidad(self):
        ventana = VentanaSensores(horizonte_horas=100, max_lecturas=3)
        for minutos in range(5):
            ventana.registrar(lectura(minutos))

        self.assertEqual(
            ventana.ventana("B-102", "presion_descarga"),
            (lectura(2), lectura(3), lectura(4)),
        )

    def test_poda_por_tiempo_con_ts_distintos(self):
        ventana = VentanaSensores(horizonte_horas=1, max_lecturas=100)
        for minutos in (0, 30, 60, 120):
            ventana.registrar(lectura(minutos))

        self.assertEqual(
            ventana.ventana("B-102", "presion_descarga"),
            (lectura(60), lectura(120)),
        )

    def test_lectura_fuera_de_orden_se_descarta(self):
        ventana = VentanaSensores(horizonte_horas=6, max_lecturas=100)
        ventana.registrar(lectura(10))
        ventana.registrar(lectura(20))
        with self.assertLogs("sistema.sensores", level="DEBUG"):
            ventana.registrar(lectura(15))

        self.assertEqual(
            ventana.ventana("B-102", "presion_descarga"),
            (lectura(10), lectura(20)),
        )

    def test_ts_duplicado_se_descarta(self):
        ventana = VentanaSensores(horizonte_horas=6, max_lecturas=100)
        primera = lectura(0, valor=1.0)
        duplicada = lectura(0, valor=2.0)
        ventana.registrar(primera)
        ventana.registrar(duplicada)

        self.assertEqual(
            ventana.ventana("B-102", "presion_descarga"), (primera,)
        )

    def test_concurrencia_basica(self):
        ventana = VentanaSensores(horizonte_horas=24, max_lecturas=1000)
        errores = []
        barrera = threading.Barrier(8)

        def trabajar(indice: int) -> None:
            try:
                barrera.wait()
                for minutos in range(50):
                    ventana.registrar(lectura(minutos, tag=f"EQ-{indice}"))
            except Exception as exc:
                errores.append(exc)

        hilos = [threading.Thread(target=trabajar, args=(indice,)) for indice in range(8)]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join()

        self.assertEqual(errores, [])
        self.assertEqual(len(ventana.claves()), 8)
        for indice in range(8):
            datos = ventana.ventana(f"EQ-{indice}", "presion_descarga")
            self.assertEqual(len(datos), 50)
            self.assertEqual(list(datos), sorted(datos, key=lambda item: item.ts))


class TestClienteMQTTSensores(unittest.TestCase):
    def setUp(self):
        self.cliente = ClienteMQTT("localhost", 1883, "test")
        self.recibidas: list[LecturaSensor] = []
        self.cliente.al_recibir_sensor = self.recibidas.append

    def test_callback_invocado(self):
        esperada = lectura(0)
        msg = SimpleNamespace(
            topic="planta/sensores/B-102/presion_descarga",
            payload=esperada.model_dump_json().encode(),
        )
        self.cliente._on_message(None, None, msg)

        self.assertEqual(self.recibidas, [esperada])

    def test_lectura_invalida_se_ignora(self):
        msg = SimpleNamespace(
            topic="planta/sensores/B-102/presion_descarga",
            payload=b'{"tag": "B-102"}',
        )
        with self.assertLogs("sistema.mqtt", level="ERROR"):
            self.cliente._on_message(None, None, msg)

        self.assertEqual(self.recibidas, [])


if __name__ == "__main__":
    unittest.main()
