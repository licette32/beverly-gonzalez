import unittest

from sistema.catalogo import CatalogoPlanta


DATOS = {
    "equipos": [
        {
            "tag": "B-101",
            "tipo": "bomba",
            "nombres": ["la uno", "la de la punta"],
            "manometro_local": {"unidad": "kg/cm2"},
        },
        {
            "tag": "B-102",
            "tipo": "bomba",
            "nombres": ["la dos", "la del medio"],
            "manometro_local": {"unidad": "psi"},
        },
        {
            "tag": "F-201A",
            "tipo": "filtro",
            "nombres": ["el filtro A", "el primario"],
        },
    ]
}


class TestCatalogo(unittest.TestCase):
    def setUp(self):
        self.catalogo = CatalogoPlanta.desde_datos(DATOS)

    def test_busca_tag_y_alias(self):
        self.assertEqual(self.catalogo.buscar_tag("La de la punta está en 114."), "B-101")
        self.assertEqual(self.catalogo.buscar_tag("Era la dos."), "B-102")
        self.assertEqual(self.catalogo.buscar_tag("El primario me dio 1,3."), "F-201A")
        self.assertIsNone(self.catalogo.buscar_tag("La bomba está parada."))

    def test_opciones_por_tipo(self):
        self.assertEqual(
            self.catalogo.opciones_equipo("bomba"),
            ["B-101 (la uno)", "B-102 (la dos)"],
        )
        self.assertEqual(
            self.catalogo.opciones_equipo("filtro"),
            ["F-201A (el filtro A)"],
        )

    def test_unidad_manometro(self):
        self.assertEqual(self.catalogo.unidad_manometro("B-102"), "psi")
        self.assertEqual(
            self.catalogo.unidades_manometro(),
            {"B-101": "kg/cm2", "B-102": "psi"},
        )
        self.assertIsNone(self.catalogo.unidad_manometro(None))


if __name__ == "__main__":
    unittest.main()
