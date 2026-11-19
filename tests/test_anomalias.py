import unittest
from datetime import datetime, timedelta, timezone

from planta_contrato import Calidad, LecturaSensor

from sistema.anomalias import ParametrosDeteccion, detectar_anomalia

BASE = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
LIMITES = {"alarma_alta": 125.0, "alarma_baja": 95.0}
PARAMETROS = ParametrosDeteccion(ventana_min=30, minimo_fuera=6, span_min=10)


def lectura(
    minutos: float,
    valor: float | None = 110.0,
    tag: str = "B-101",
    variable: str = "presion_descarga",
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


class TestDeteccionAnomalias(unittest.TestCase):
    def test_pico_aislado_no_es_anomalia(self):
        lecturas = [lectura(minutos) for minutos in range(0, 28, 3)]
        lecturas[4] = lectura(12, valor=130.0)

        resultado = detectar_anomalia(lecturas, LIMITES, PARAMETROS)

        self.assertFalse(resultado.anomalia)
        self.assertEqual(resultado.motivo, "pico_aislado")
        self.assertEqual(resultado.variable, "presion_descarga")
        self.assertEqual(resultado.cantidad_fuera, 1)
        self.assertEqual(resultado.ultima_lectura, lecturas[-1])
        self.assertEqual(resultado.limite_violado, "alarma_alta=125.0")

    def test_desvio_sostenido_es_anomalia(self):
        lecturas = [lectura(minutos) for minutos in range(0, 28, 3)]
        for indice in range(4, 10):
            lecturas[indice] = lectura(indice * 3, valor=130.0)

        resultado = detectar_anomalia(lecturas, LIMITES, PARAMETROS)

        self.assertTrue(resultado.anomalia)
        self.assertEqual(resultado.motivo, "sostenido")
        self.assertEqual(resultado.cantidad_fuera, 6)
        self.assertEqual(resultado.ultima_lectura, lecturas[-1])
        self.assertEqual(resultado.limite_violado, "alarma_alta=125.0")
        self.assertEqual(resultado.lecturas_consideradas, 10)

    def test_equipo_excluido_no_es_anomalia(self):
        lecturas = [lectura(minutos, valor=130.0) for minutos in range(0, 28, 3)]
        parametros = ParametrosDeteccion(
            ventana_min=30,
            minimo_fuera=6,
            span_min=10,
            equipos_excluidos=frozenset({"B-101"}),
        )

        resultado = detectar_anomalia(lecturas, LIMITES, parametros)

        self.assertFalse(resultado.anomalia)
        self.assertEqual(resultado.motivo, "equipo_excluido")
        self.assertEqual(resultado.cantidad_fuera, 0)
        self.assertIsNone(resultado.ultima_lectura)
        self.assertIsNone(resultado.limite_violado)

    def test_valor_exacto_en_limite_cuenta_como_fuera(self):
        casos = ((125.0, "alarma_alta=125.0"), (95.0, "alarma_baja=95.0"))
        for valor, limite in casos:
            with self.subTest(valor=valor):
                lecturas = [lectura(minutos, valor=valor) for minutos in range(0, 18, 3)]

                resultado = detectar_anomalia(lecturas, LIMITES, PARAMETROS)

                self.assertTrue(resultado.anomalia)
                self.assertEqual(resultado.cantidad_fuera, 6)
                self.assertEqual(resultado.limite_violado, limite)

    def test_none_y_sin_dato_se_ignoran(self):
        lecturas = [lectura(minutos, valor=130.0) for minutos in range(0, 18, 3)]
        lecturas.extend(
            [
                lectura(18, valor=None),
                lectura(21, valor=130.0, calidad=Calidad.sin_dato),
                lectura(24, valor=None, calidad=Calidad.sin_dato),
                lectura(27, valor=130.0, calidad=Calidad.sin_dato),
            ]
        )

        resultado = detectar_anomalia(lecturas, LIMITES, PARAMETROS)

        self.assertTrue(resultado.anomalia)
        self.assertEqual(resultado.cantidad_fuera, 6)
        self.assertEqual(resultado.lecturas_consideradas, 6)
        self.assertEqual(resultado.ultima_lectura, lecturas[5])

    def test_ventana_es_por_tiempo_simulado(self):
        lecturas = [lectura(minutos, valor=130.0) for minutos in range(-60, 1, 12)]

        resultado = detectar_anomalia(lecturas, LIMITES, PARAMETROS)

        self.assertFalse(resultado.anomalia)
        self.assertEqual(resultado.motivo, "pico_aislado")
        self.assertEqual(resultado.cantidad_fuera, 3)

    def test_span_insuficiente_no_es_anomalia(self):
        lecturas = [lectura(minutos, valor=130.0) for minutos in (0, 0.5, 1, 1.5, 2, 2.5)]

        resultado = detectar_anomalia(lecturas, LIMITES, PARAMETROS)

        self.assertFalse(resultado.anomalia)
        self.assertEqual(resultado.motivo, "span_insuficiente")
        self.assertEqual(resultado.cantidad_fuera, 6)

    def test_mismos_datos_mismo_resultado(self):
        lecturas = [lectura(minutos) for minutos in range(0, 28, 3)]
        for indice in range(4, 10):
            lecturas[indice] = lectura(indice * 3, valor=130.0)

        primero = detectar_anomalia(lecturas, LIMITES, PARAMETROS)
        segundo = detectar_anomalia(list(lecturas), dict(LIMITES), PARAMETROS)
        invertido = detectar_anomalia(list(reversed(lecturas)), LIMITES, PARAMETROS)

        self.assertEqual(primero, segundo)
        self.assertEqual(primero, invertido)


if __name__ == "__main__":
    unittest.main()
