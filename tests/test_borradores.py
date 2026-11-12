import unittest
from datetime import datetime, timezone

from planta_contrato import MensajeTablet, NotaRecorrida

from sistema.borradores import borrador, fila_desde_item, items_seguridad, pregunta
from sistema.parte import ItemParte


def nota() -> NotaRecorrida:
    return NotaRecorrida(
        id="NOTA-00010",
        ts=datetime(2026, 11, 5, 9, 40, tzinfo=timezone.utc),
        operador="operador-1",
        audio_url=None,
        fotos=[],
        recorrida_id="REC-1",
    )


class TestBorradores(unittest.TestCase):
    def test_borrador_con_ts_de_la_nota_y_filas(self):
        items = [ItemParte("B-102", "presion_descarga_local", 1610.0, "psi")]
        mensaje = borrador(nota(), items, 0)
        self.assertIsInstance(mensaje, MensajeTablet)
        self.assertEqual(mensaje.ts, nota().ts)
        self.assertEqual(mensaje.nota_ids, ["NOTA-00010"])
        self.assertTrue(mensaje.espera_respuesta)
        self.assertEqual(mensaje.pantalla.filas[0].tag, "B-102")
        self.assertEqual(mensaje.pantalla.opciones, [])

    def test_id_estable_por_nota_e_intento(self):
        items = [ItemParte("B-102", "presion_descarga_local", 1610.0, "psi")]
        self.assertEqual(borrador(nota(), items, 0).id, borrador(nota(), items, 0).id)
        self.assertNotEqual(borrador(nota(), items, 0).id, borrador(nota(), items, 1).id)

    def test_equipo_sin_resolver_usa_tag_explicito(self):
        fila = fila_desde_item(ItemParte(None, "estado", None, None, "parada"))
        self.assertEqual(fila.tag, "SIN-EQUIPO")

    def test_pregunta_lleva_borrador_y_opciones(self):
        items = [ItemParte(None, "estado", None, None, "parada, en reserva")]
        mensaje = pregunta(
            nota(),
            items,
            0,
            1,
            "¿A qué equipo te referís?",
            ["B-101 (la uno)", "B-103 (la tres)"],
        )
        self.assertEqual(mensaje.pantalla.filas[0].tag, "SIN-EQUIPO")
        self.assertEqual(
            mensaje.pantalla.opciones, ["B-101 (la uno)", "B-103 (la tres)"]
        )
        self.assertTrue(mensaje.espera_respuesta)

    def test_seguridad_no_inventa_valor(self):
        class Deteccion:
            categoria = "S1"
            evidencia = "agua a presion"

        items = items_seguridad([Deteccion()])
        self.assertEqual(items[0].variable, "condicion_insegura")
        self.assertIsNone(items[0].valor)
        self.assertIn("S1", items[0].observacion)


if __name__ == "__main__":
    unittest.main()
