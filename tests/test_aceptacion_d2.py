import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from planta_contrato import EstadoOrden
from test_ordenes import evento_sensor

from sistema.causas import Anomalia, EvidenciaEquipo
from sistema.flujo import CatalogoTools, procesar

TZ = timezone(timedelta(hours=-3))
DESDE = datetime(2026, 11, 4, 6, 0, tzinfo=TZ)
HASTA = datetime(2026, 11, 4, 7, 0, tzinfo=TZ)
TS = datetime(2026, 11, 4, 6, 30, tzinfo=TZ)

_patch_citas = patch("sistema.causas.verificar_cita", return_value=True)


def setUpModule():
    _patch_citas.start()


def tearDownModule():
    _patch_citas.stop()


def anomalia(equipo, variable, lado):
    return Anomalia(tag=equipo, variable=variable, ts=TS, lado=lado)


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


def detalle(resultado):
    return [
        (causa.codigo_falla, causa.accion, causa.tarea_codigo, causa.equipo_orden)
        for causa in resultado.causas
    ]


def mostrar(etiqueta, resultado):
    print(f"\n{etiqueta}")
    for fila in detalle(resultado):
        print(f"  {fila[0]} | {fila[1]} | {fila[2]} | {fila[3]}")
    print(f"  ORDEN: {resultado.orden}")


class TestAceptacionD2(unittest.TestCase):
    def _procesar(self, equipo, anomalias, historial=()):
        with patch(
            "urllib.request.urlopen", side_effect=AssertionError("sin red")
        ):
            return procesar(
                evento_sensor(equipo),
                evidencia(equipo, anomalias),
                historial,
                CatalogoTools(),
            )

    def test_b102_solo_vibracion(self):
        resultado = self._procesar(
            "B-102", [anomalia("B-102", "vibracion", "alta")]
        )
        mostrar("B-102 vibración alta", resultado)
        self.assertEqual(
            detalle(resultado),
            [
                ("F06", "I-VIB", "I-VIB", "B-102"),
                ("F02", "I-VIB", "I-VIB", "B-102"),
                ("F03", "I-VIB", "I-VIB", "B-102"),
                ("F09", "inspeccion", None, "TK-301"),
            ],
        )
        self.assertIsNotNone(resultado.orden)
        self.assertEqual(resultado.orden.equipo, "B-102")
        self.assertIn(resultado.orden.tareas[0], ("I-VIB", "T-B-VAL"))

    def test_b101_vibracion_temperatura_y_valvula_previa(self):
        resultado = self._procesar(
            "B-101",
            [
                anomalia("B-101", "vibracion", "alta"),
                anomalia("B-101", "temperatura_aceite", "alta"),
            ],
            [
                orden_historica(
                    "H-VAL",
                    "2026-09-08T09:00:00-03:00",
                    "B-101",
                    ["T-B-VAL"],
                )
            ],
        )
        mostrar("B-101 vib + temp + T-B-VAL previa", resultado)
        self.assertEqual(
            detalle(resultado),
            [
                ("F03", "orden", "T-B-ROD", "B-101"),
                ("F02", "orden", "T-B-VAL", "B-101"),
                ("F04", "orden", "T-B-ACE", "B-101"),
                ("F06", "orden", "T-B-ALI", "B-101"),
                ("F09", "inspeccion", None, "TK-301"),
            ],
        )
        self.assertIsNotNone(resultado.orden)
        self.assertEqual(resultado.orden.equipo, "B-101")
        self.assertEqual(resultado.orden.tareas, ["T-B-ROD"])
        self.assertNotIn("T-B-ALI", resultado.orden.tareas)

    def test_f201b_dp_alta(self):
        resultado = self._procesar(
            "F-201B", [anomalia("F-201B", "presion_diferencial", "alta")]
        )
        mostrar("F-201B dp alta", resultado)
        self.assertEqual(detalle(resultado), [("F07", "orden", "T-F-CAR", "F-201B")])
        self.assertIsNotNone(resultado.orden)
        self.assertEqual(resultado.orden.equipo, "F-201B")
        self.assertEqual(resultado.orden.tareas, ["T-F-CAR"])

    def test_f201a_solo_dp_alta_sin_f08_f09_por_historial(self):
        resultado = self._procesar(
            "F-201A",
            [anomalia("F-201A", "presion_diferencial", "alta")],
            [
                orden_historica(
                    "H-CART",
                    "2026-03-20T15:30:00-03:00",
                    "F-201A",
                    ["T-F-CAR"],
                    texto="cambio de cartucho con ruido de piedras",
                )
            ],
        )
        mostrar("F-201A dp alta + historial de cartucho/cavitación", resultado)
        self.assertEqual(detalle(resultado), [("F07", "orden", "T-F-CAR", "F-201A")])
        self.assertIsNotNone(resultado.orden)
        self.assertEqual(resultado.orden.equipo, "F-201A")


if __name__ == "__main__":
    unittest.main()
