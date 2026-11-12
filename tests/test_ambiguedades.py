import unittest

from sistema.ambiguedades import (
    detectar,
    items_para_b1,
    items_para_pantalla,
)
from sistema.borradores import fila_desde_item
from sistema.catalogo import CatalogoPlanta
from sistema.parte import extraer_items

from test_catalogo import DATOS


class TestAmbiguedades(unittest.TestCase):
    def setUp(self):
        self.catalogo = CatalogoPlanta.desde_datos(DATOS)

    def test_equipo_generico(self):
        items = extraer_items("La bomba está parada, en reserva.")
        ambiguedades = detectar(items, "La bomba está parada, en reserva.", self.catalogo)
        self.assertEqual(len(ambiguedades), 1)
        self.assertEqual(ambiguedades[0].tipo, "equipo")
        self.assertIn("B-101 (la uno)", ambiguedades[0].opciones)
        self.assertIn("B-102 (la dos)", ambiguedades[0].opciones)

        visibles = items_para_pantalla(items, ambiguedades)
        self.assertIsNone(visibles[0].tag)
        self.assertIn("equipo ambiguo", visibles[0].observacion)
        self.assertEqual(fila_desde_item(visibles[0]).tag, "SIN-EQUIPO")

    def test_diferencial_dicho_como_entero(self):
        texto = "El filtro A me dio dieciocho de diferencial."
        items = extraer_items(texto)
        self.assertEqual(items[0].valor, 18.0)
        ambiguedades = detectar(items, texto, self.catalogo)
        self.assertEqual(len(ambiguedades), 1)
        self.assertEqual(ambiguedades[0].tipo, "valor")
        self.assertEqual(ambiguedades[0].opciones, ("1,8 kg/cm2", "18 kg/cm2"))

        visibles = items_para_pantalla(items, ambiguedades)
        self.assertIsNone(visibles[0].valor)
        self.assertIn("valor ambiguo", visibles[0].observacion)

        para_b1 = items_para_b1(items, ambiguedades)
        self.assertIsNone(para_b1[0].valor)
        self.assertIsNone(para_b1[0].observacion)

    def test_no_pregunta_por_uno_ocho(self):
        texto = "El filtro A me dio uno ocho de diferencial."
        items = extraer_items(texto)
        self.assertEqual(items[0].valor, 1.8)
        self.assertEqual(detectar(items, texto, self.catalogo), [])

    def test_no_pregunta_nota_clara(self):
        texto = "La dos está en mil seiscientos diez libras de descarga."
        items = extraer_items(texto, self.catalogo.unidades_manometro())
        self.assertEqual(detectar(items, texto, self.catalogo), [])


if __name__ == "__main__":
    unittest.main()
