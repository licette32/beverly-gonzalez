import unittest
from dataclasses import replace

from sistema.catalogo import CatalogoPlanta
from sistema.interpretacion import _resolver_pregunta
from sistema.coordinador import CoordinadorPartes
from sistema.parte import ItemParte, extraer_items
from sistema.repositorio import RepositorioMemoria

from test_coordinador import ClienteFalso, nota, respuesta

DATOS = {
    "equipos": [
        {"tag": "B-101", "tipo": "bomba", "nombres": ["la uno"],
         "manometro_local": {"unidad": "kg/cm2"}},
        {"tag": "B-102", "tipo": "bomba", "nombres": ["la dos"],
         "manometro_local": {"unidad": "psi"}},
        {"tag": "B-103", "tipo": "bomba", "nombres": ["la tres"],
         "manometro_local": {"unidad": "bar"}},
    ]
}


class EstadoFalso:
    def __init__(self, items, texto):
        self.items = items
        self.texto = texto
        self.estado = "PREGUNTA"


class UnidadInferidaTest(unittest.TestCase):
    def setUp(self):
        self.catalogo = CatalogoPlanta.desde_datos(DATOS)

    def test_unidad_no_dicha_queda_marcada_como_inferida(self):
        items = extraer_items("la uno esta en ciento doce de descarga")
        item = [i for i in items if i.variable == "presion_descarga_local"][0]
        self.assertTrue(item.unidad_inferida)

    def test_unidad_dicha_no_es_inferida(self):
        items = extraer_items("la uno esta en ciento doce kilos de descarga")
        item = [i for i in items if i.variable == "presion_descarga_local"][0]
        self.assertFalse(item.unidad_inferida)

    def test_no_se_pierde_la_observacion_de_los_demas_items(self):
        items = extraer_items("el filtro A me dio dos de diferencial")
        item = [i for i in items if i.variable == "presion_diferencial"][0]
        self.assertEqual(item.observacion, "diferencial alto")

    def test_al_resolver_el_equipo_toma_la_unidad_de_su_manometro(self):
        item = ItemParte(None, "presion_descarga_local", 1600.0, "kg/cm2",
                         unidad_inferida=True)
        estado = EstadoFalso([item], "tambien la bomba esta en mil seiscientos de descarga")
        resultado = _resolver_pregunta("la dos", estado, self.catalogo)
        self.assertEqual(resultado.items[0].tag, "B-102")
        self.assertEqual(resultado.items[0].unidad, "psi")

    def test_si_la_unidad_se_dijo_no_se_cambia(self):
        item = ItemParte(None, "presion_descarga_local", 1600.0, "kg/cm2",
                         unidad_inferida=False)
        estado = EstadoFalso([item], "tambien la bomba esta en mil seiscientos kilos de descarga")
        resultado = _resolver_pregunta("la dos", estado, self.catalogo)
        self.assertEqual(resultado.items[0].unidad, "kg/cm2")


class FlujoNota11Test(unittest.TestCase):
    def test_al_resolver_la_bomba_la_unidad_sale_en_psi_sin_ronda_extra(self):
        cliente = ClienteFalso()
        coordinador = CoordinadorPartes(
            cliente, RepositorioMemoria(), CatalogoPlanta.desde_datos(DATOS)
        )
        coordinador.procesar_nota(
            nota("NOTA-00011"),
            "la uno esta en ciento doce kilogramos de descarga, "
            "tambien la bomba esta en mil seiscientos de descarga",
            [],
        )
        pregunta = cliente.publicados[-1][1]
        coordinador._procesar_respuesta(
            respuesta(
                pregunta.id,
                "No. Te faltó la dos, que estaba en mil seiscientos psi. "
                "Lo de SIN-EQUIPO no lo dije. Corregilo y te confirmo.",
            )
        )
        filas = cliente.publicados[-1][1].pantalla.filas
        b102 = [f for f in filas if f.tag == "B-102"]
        self.assertEqual(len(b102), 1)
        self.assertEqual(b102[0].unidad, "psi")
        self.assertEqual([f for f in filas if f.tag == "SIN-EQUIPO"], [])


if __name__ == "__main__":
    unittest.main()
