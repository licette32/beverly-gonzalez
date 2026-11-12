import unittest
from datetime import datetime, timezone

from planta_contrato import EventoSistema, NotaRecorrida, TipoEvento

from sistema.eventos import eventos_parte
from sistema.parte import ItemParte, extraer_items, fuera_de_limite, numero


def nota(nota_id: str = "NOTA-00004") -> NotaRecorrida:
    return NotaRecorrida(
        id=nota_id,
        ts=datetime(2026, 11, 5, 9, 40, tzinfo=timezone.utc),
        operador="operador-1",
        audio_url=None,
        fotos=[],
        recorrida_id="REC-1",
    )


class TestNumeros(unittest.TestCase):
    def test_numeros_hablados(self):
        casos = {
            "ciento catorce": 114.0,
            "mil seiscientos diez": 1610.0,
            "sesenta y cuatro": 64.0,
            "noventa y cinco": 95.0,
            "ciento veinticinco": 125.0,
            "cinco": 5.0,
            "uno ocho": 1.8,
            "uno coma ocho": 1.8,
            "uno con ocho": 1.8,
            "cero coma cero tres": 0.03,
            "uno y medio": 1.5,
            "dieciocho": 18.0,
            "1,8": 1.8,
            "1.610": 1610.0,
            "medio 0.9": 0.9,
            "medio 1,3": 1.3,
            "0 9": 0.9,
            "1-3": 1.3,
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertAlmostEqual(numero(texto), esperado)


class TestExtraccion(unittest.TestCase):
    def test_presion_y_temperatura(self):
        items = extraer_items(
            "La uno está en ciento catorce kilos de descarga, el rodamiento me dio sesenta y cuatro grados con la pistola."
        )
        self.assertIn(ItemParte("B-101", "presion_descarga_local", 114.0, "kg/cm2"), items)
        self.assertIn(ItemParte("B-101", "temperatura_rodamiento_ir", 64.0, "degC"), items)

    def test_presion_en_psi(self):
        items = extraer_items("La dos está en mil seiscientos diez libras de descarga.")
        self.assertIn(ItemParte("B-102", "presion_descarga_local", 1610.0, "psi"), items)

    def test_unidad_omitida_usa_manometro_del_equipo(self):
        items = extraer_items("La dos está en mil seiscientos diez de descarga.")
        self.assertIn(ItemParte("B-102", "presion_descarga_local", 1610.0, "psi"), items)

    def test_nivel_del_pulmon(self):
        items = extraer_items("El pulmón está en cinco metros.")
        self.assertIn(ItemParte("TK-301", "nivel", 5.0, "m"), items)

    def test_decimal_con_punto_no_parte_la_oracion(self):
        items = extraer_items("El filtro B medio 0.9 de diferencial.")
        self.assertIn(ItemParte("F-201B", "presion_diferencial", 0.9, "kg/cm2"), items)

    def test_decimal_transcrito_con_espacio_o_guion(self):
        items = extraer_items(
            "El filtro B medio, 0 9 de diferencial. El filtro A medio 1-3 de diferencial."
        )
        self.assertIn(ItemParte("F-201B", "presion_diferencial", 0.9, "kg/cm2"), items)
        self.assertIn(ItemParte("F-201A", "presion_diferencial", 1.3, "kg/cm2"), items)

    def test_psi_transcrito_como_pc(self):
        items = extraer_items("La dos está en mil seiscientos p.c. y descarga.")
        self.assertIn(ItemParte("B-102", "presion_descarga_local", 1600.0, "psi"), items)

    def test_equipo_ambiguo(self):
        items = extraer_items("Listo, la bomba está parada, en reserva.")
        self.assertEqual(
            items, [ItemParte(None, "estado", None, None, "parada, en reserva")]
        )

    def test_parada_por_mantenimiento(self):
        items = extraer_items("La tres está parada por mantenimiento.")
        self.assertEqual(
            items, [ItemParte("B-103", "estado", None, None, "parada por mantenimiento")]
        )

    def test_goteo(self):
        items = extraer_items("La tres sigue goteando por la empaquetadura, le saqué foto.")
        self.assertIn(
            ItemParte(
                "B-103",
                "goteo_empaquetadura",
                None,
                "gotas/min",
                "goteo por empaquetadura",
            ),
            items,
        )

    def test_perdida_importante(self):
        items = extraer_items("La uno chorrea por la empaquetadura.")
        self.assertIn(
            ItemParte(
                "B-101",
                "goteo_empaquetadura",
                None,
                "gotas/min",
                "perdida importante por empaquetadura",
            ),
            items,
        )

    def test_diferencial_ambiguo(self):
        items = extraer_items("El filtro A me dio uno ocho de diferencial.")
        self.assertIn(
            ItemParte(
                "F-201A",
                "presion_diferencial",
                1.8,
                "kg/cm2",
                "diferencial alto",
            ),
            items,
        )

    def test_aceite_correas_y_ruido(self):
        items = extraer_items(
            "La dos casi no tiene aceite en el visor. Las correas están flojas, chillan. "
            "La dos suena como si tuviera piedras adentro."
        )
        self.assertIn(
            ItemParte("B-102", "nivel_aceite_visor", None, None, "nivel de aceite bajo"),
            items,
        )
        self.assertIn(
            ItemParte("B-102", "estado_correas", None, None, "correas flojas"), items
        )
        self.assertIn(ItemParte("B-102", "ruido", None, None, "cavitacion"), items)

    def test_nota_sin_items(self):
        self.assertEqual(extraer_items("Recorrida sin novedad, todo normal."), [])


class TestLimites(unittest.TestCase):
    def test_presion_dentro_de_limites(self):
        self.assertFalse(
            fuera_de_limite(
                ItemParte("B-101", "presion_descarga_local", 114.0, "kg/cm2")
            )
        )
        self.assertFalse(
            fuera_de_limite(
                ItemParte("B-102", "presion_descarga_local", 1610.0, "psi")
            )
        )
        self.assertFalse(
            fuera_de_limite(
                ItemParte("B-103", "presion_descarga_local", 95.0, "bar")
            )
        )

    def test_presion_fuera_de_limites(self):
        self.assertTrue(
            fuera_de_limite(
                ItemParte("B-101", "presion_descarga_local", 130.0, "kg/cm2")
            )
        )
        self.assertTrue(
            fuera_de_limite(
                ItemParte("B-101", "presion_descarga_local", 90.0, "kg/cm2")
            )
        )

    def test_diferencial_fuera_de_limites(self):
        self.assertTrue(
            fuera_de_limite(
                ItemParte("F-201A", "presion_diferencial", 1.8, "kg/cm2")
            )
        )
        self.assertTrue(
            fuera_de_limite(
                ItemParte("F-201B", "presion_diferencial", 0.1, "kg/cm2")
            )
        )


class TestEventosParte(unittest.TestCase):
    def tipos(self, eventos):
        return {(evento.equipo, evento.tipo.value) for evento in eventos}

    def test_fuga_nota_00004(self):
        items = extraer_items(
            "La dos está en mil seiscientos diez libras de descarga. El pulmón está en cinco metros."
        )
        eventos = eventos_parte(nota("NOTA-00004"), items)
        self.assertEqual(
            self.tipos(eventos),
            {("B-102", "SinNovedad"), ("TK-301", "SinNovedad")},
        )

    def test_fuga_nota_00005(self):
        items = extraer_items(
            "La uno está en ciento catorce kilos de descarga, el rodamiento me dio sesenta y cuatro grados con la pistola."
        )
        eventos = eventos_parte(nota("NOTA-00005"), items)
        self.assertEqual(self.tipos(eventos), {("B-101", "SinNovedad")})

    def test_fuga_nota_00006_ambigua(self):
        items = extraer_items("Listo, la bomba está parada, en reserva.")
        eventos = eventos_parte(nota("NOTA-00006"), items)
        self.assertEqual(self.tipos(eventos), {(None, "SinNovedad")})

    def test_nota_sin_items(self):
        eventos = eventos_parte(nota("NOTA-00007"), [])
        self.assertEqual(self.tipos(eventos), {(None, "SinNovedad")})

    def test_anomalia_escala(self):
        items = extraer_items("La tres pierde bastante por la empaquetadura.")
        eventos = eventos_parte(nota("NOTA-00008"), items)
        self.assertEqual(self.tipos(eventos), {("B-103", "Escalado")})

    def test_mezcla_normal_y_anomalia(self):
        items = extraer_items(
            "La uno está en ciento catorce kilos de descarga. La dos chorrea por la empaquetadura."
        )
        eventos = eventos_parte(nota("NOTA-00009"), items)
        self.assertEqual(
            self.tipos(eventos),
            {("B-101", "SinNovedad"), ("B-102", "Escalado")},
        )

    def test_eventos_validan_contra_contrato(self):
        items = extraer_items("La dos está en mil seiscientos diez libras de descarga.")
        for evento in eventos_parte(nota(), items):
            self.assertIsInstance(evento, EventoSistema)
            EventoSistema.model_validate(evento.model_dump(mode="json"))
            self.assertEqual(evento.origen, "parte")
            self.assertEqual(evento.nota_ids, ["NOTA-00004"])
            self.assertEqual(evento.ts, nota().ts)

    def test_ids_estables(self):
        items = extraer_items("La dos está en mil seiscientos diez libras de descarga.")
        primera = [evento.id for evento in eventos_parte(nota(), items)]
        segunda = [evento.id for evento in eventos_parte(nota(), items)]
        self.assertEqual(primera, segunda)


if __name__ == "__main__":
    unittest.main()