import unittest
from datetime import datetime, timezone

from planta_contrato import NotaRecorrida

from sistema.borradores import borrador
from sistema.catalogo import CatalogoPlanta
from sistema.interpretacion import interpretar
from sistema.parte import ItemParte
from sistema.repositorio import EstadoNota

from test_catalogo import DATOS


def nota() -> NotaRecorrida:
    return NotaRecorrida(
        id="NOTA-00010",
        ts=datetime(2026, 11, 5, 9, 40, tzinfo=timezone.utc),
        operador="operador-1",
        audio_url=None,
        fotos=[],
        recorrida_id="REC-1",
    )


def estado(items, texto="", tipo="BORRADOR") -> EstadoNota:
    mensaje = borrador(nota(), items, 0)
    return EstadoNota(
        nota_id=nota().id,
        mensaje=mensaje,
        nota=nota(),
        borrador=mensaje.pantalla.filas,
        items=items,
        texto=texto,
        estado=tipo,
    )


class TestInterpretacion(unittest.TestCase):
    def setUp(self):
        self.catalogo = CatalogoPlanta.desde_datos(DATOS)

    def test_confirmacion(self):
        resultado = interpretar("Sí, confirmo.", estado([]), self.catalogo)
        self.assertEqual(resultado.tipo, "confirmacion")

    def test_no_entiendo_no_es_confirmacion(self):
        resultado = interpretar("No te entendí.", estado([]), self.catalogo)
        self.assertEqual(resultado.tipo, "sin_entender")

    def test_correccion_de_valor(self):
        items = [ItemParte("B-102", "presion_descarga_local", 1600.0, "psi")]
        resultado = interpretar(
            "No. La dos estaba en mil seiscientos diez libras de descarga, "
            "no en mil seiscientos.",
            estado(items),
            self.catalogo,
        )
        self.assertEqual(resultado.tipo, "correccion")
        self.assertEqual(resultado.items[0].valor, 1610.0)
        self.assertEqual(resultado.items[0].unidad, "psi")

    def test_correccion_de_equipo(self):
        items = [
            ItemParte("B-101", "presion_descarga_local", 112.0, "kg/cm2"),
            ItemParte(None, "presion_descarga_local", 1600.0, "psi"),
        ]
        resultado = interpretar(
            "No. Eso de mil seiscientos era de la dos, no de SIN-EQUIPO.",
            estado(items),
            self.catalogo,
        )
        self.assertEqual(resultado.tipo, "correccion")
        self.assertIn(
            ItemParte("B-102", "presion_descarga_local", 1600.0, "psi"),
            resultado.items,
        )

    def test_correccion_de_unidad(self):
        items = [ItemParte("B-102", "presion_descarga_local", 1610.0, "kg/cm2")]
        resultado = interpretar(
            "No. Lo de la dos es en psi, no en kilos.",
            estado(items),
            self.catalogo,
        )
        self.assertEqual(resultado.tipo, "correccion")
        self.assertEqual(resultado.items[0].unidad, "psi")
        self.assertEqual(resultado.items[0].valor, 1610.0)

    def test_faltante(self):
        items = [ItemParte("B-102", "presion_descarga_local", 1610.0, "psi")]
        resultado = interpretar(
            "No. Te faltó el filtro A, que estaba en uno coma tres de diferencial.",
            estado(items),
            self.catalogo,
        )
        self.assertEqual(resultado.tipo, "correccion")
        self.assertIn(
            ItemParte("F-201A", "presion_diferencial", 1.3, "kg/cm2"),
            resultado.items,
        )

    def test_faltante_no_toma_numeros_de_la_oracion_siguiente(self):
        items = [ItemParte("B-101", "presion_descarga_local", 112.0, "kg/cm2")]
        resultado = interpretar(
            "No. Te faltó el filtro A, que estaba en uno coma tres kilos. "
            "Lo de la uno no lo dije.",
            estado(items),
            self.catalogo,
        )
        self.assertEqual(resultado.tipo, "correccion")
        self.assertIn(
            ItemParte("F-201A", "presion_diferencial", 1.3, "kg/cm2"),
            resultado.items,
        )
        self.assertNotIn(
            ItemParte("B-101", "presion_descarga_local", 112.0, "kg/cm2"),
            resultado.items,
        )

    def test_correccion_de_valor_agrega_equipo_ausente(self):
        items = [ItemParte("B-101", "presion_descarga_local", 112.0, "kg/cm2")]
        resultado = interpretar(
            "No. El filtro A estaba en uno coma tres kilos, no en cero.",
            estado(items),
            self.catalogo,
        )
        self.assertEqual(resultado.tipo, "correccion")
        self.assertIn(
            ItemParte("F-201A", "presion_diferencial", 1.3, "kg/cm2"),
            resultado.items,
        )

    def test_correccion_de_valor_quita_observacion_vieja(self):
        items = [
            ItemParte(
                "F-201A",
                "presion_diferencial",
                9.0,
                "kg/cm2",
                "diferencial alto",
            )
        ]
        resultado = interpretar(
            "No. El filtro A estaba en cero coma nueve kilos, no en nueve.",
            estado(items),
            self.catalogo,
        )
        self.assertEqual(resultado.tipo, "correccion")
        self.assertEqual(
            resultado.items,
            [ItemParte("F-201A", "presion_diferencial", 0.9, "kg/cm2")],
        )

    def test_correccion_de_equipo_con_era_del(self):
        items = [
            ItemParte("B-101", "presion_descarga_local", 112.0, "kg/cm2"),
            ItemParte("B-102", "presion_descarga_local", 1.3, "kg/cm2"),
        ]
        resultado = interpretar(
            "No. Eso de uno coma tres era del filtro A, no de la dos.",
            estado(items),
            self.catalogo,
        )
        self.assertEqual(resultado.tipo, "correccion")
        self.assertIn(
            ItemParte("F-201A", "presion_diferencial", 1.3, "kg/cm2"),
            resultado.items,
        )
        self.assertNotIn(
            ItemParte("B-102", "presion_descarga_local", 1.3, "kg/cm2"),
            resultado.items,
        )

    def test_sobrante(self):
        items = [
            ItemParte("B-101", "presion_descarga_local", 112.0, "kg/cm2"),
            ItemParte("F-201A", "presion_diferencial", 1.4, "kg/cm2"),
        ]
        resultado = interpretar(
            "No. Lo de el filtro A no lo dije.",
            estado(items),
            self.catalogo,
        )
        self.assertEqual(resultado.tipo, "correccion")
        self.assertEqual(resultado.items, [items[0]])

    def test_responde_pregunta_de_equipo(self):
        items = [ItemParte(None, "estado", None, None, "parada, en reserva")]
        resultado = interpretar(
            "Era la dos.",
            estado(items, "La bomba está parada, en reserva.", "PREGUNTA"),
            self.catalogo,
        )
        self.assertEqual(resultado.tipo, "correccion")
        self.assertEqual(resultado.items[0].tag, "B-102")

    def test_responde_pregunta_de_valor(self):
        items = [ItemParte("F-201A", "presion_diferencial", 18.0, "kg/cm2")]
        texto = "El filtro A me dio dieciocho de diferencial."
        uno_ocho = interpretar(
            "Uno ocho.", estado(items, texto, "PREGUNTA"), self.catalogo
        )
        dieciocho = interpretar(
            "Dieciocho.", estado(items, texto, "PREGUNTA"), self.catalogo
        )
        self.assertEqual(uno_ocho.items[0].valor, 1.8)
        self.assertEqual(dieciocho.items[0].valor, 18.0)


if __name__ == "__main__":
    unittest.main()
