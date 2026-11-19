import unittest

from sistema.catalogo import CatalogoPlanta, EstadoPlanta


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


class EstadoPlantaFalso(EstadoPlanta):
    def __init__(self, respuestas) -> None:
        super().__init__()
        self.respuestas = list(respuestas)
        self.leidas = 0

    def _leer(self, url):
        self.leidas += 1
        respuesta = self.respuestas.pop(0)
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta


MUESTRA_BOMBAS = {
    "ts": "2026-11-20T14:15:53-03:00",
    "bombas": [
        {"tag": "B-101", "estado": "marcha", "pd": 113.3},
        {"tag": "B-102", "estado": "parada", "pd": 1.7},
        {"tag": "B-103", "estado": "mantenimiento", "pd": 0.0},
        {"tag": "B-104", "estado": "disparo", "pd": 0.0},
    ],
}


class TestEstadoBombas(unittest.TestCase):
    def test_pass_through_de_los_cuatro_estados(self):
        estado = EstadoPlantaFalso([MUESTRA_BOMBAS])
        self.assertEqual(
            estado.estado_bombas(),
            {
                "B-101": "marcha",
                "B-102": "parada",
                "B-103": "mantenimiento",
                "B-104": "disparo",
            },
        )

    def test_lee_fresco_en_cada_llamada(self):
        primera = {"bombas": [{"tag": "B-101", "estado": "marcha"}]}
        segunda = {"bombas": [{"tag": "B-101", "estado": "parada"}]}
        estado = EstadoPlantaFalso([primera, segunda])
        self.assertEqual(estado.estado_bombas(), {"B-101": "marcha"})
        self.assertEqual(estado.estado_bombas(), {"B-101": "parada"})
        self.assertEqual(estado.leidas, 2)

    def test_fallo_de_lectura_devuelve_none(self):
        estado = EstadoPlantaFalso([RuntimeError("sin enlace")])
        self.assertIsNone(estado.estado_bombas())

    def test_json_invalido_devuelve_none(self):
        estado = EstadoPlantaFalso([ValueError("JSON inválido")])
        self.assertIsNone(estado.estado_bombas())

    def test_formato_invalido_devuelve_none(self):
        invalidos = [
            [],
            {"bombas": "B-101"},
            {"bombas": [{"tag": "B-101"}]},
            {"bombas": [{"estado": "marcha"}]},
            {"bombas": [{"tag": "", "estado": "marcha"}]},
            {"bombas": [{"tag": "B-101", "estado": 3}]},
            {"bombas": ["B-101"]},
        ]
        estado = EstadoPlantaFalso(invalidos)
        for datos in invalidos:
            with self.subTest(datos=datos):
                self.assertIsNone(estado.estado_bombas())


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

    def test_limites_de_sensores(self):
        catalogo = CatalogoPlanta.desde_datos(
            {
                "sensores": [
                    {
                        "tag": "B-101",
                        "variable": "presion_descarga",
                        "alarma_alta": 125,
                        "alarma_baja": 95,
                        "disparo": 90,
                    },
                    {
                        "tag": "B-102",
                        "variable": "vibracion",
                        "alarma_alta": 7.1,
                        "disparo": 11.2,
                    },
                    {
                        "tag": "B-103",
                        "variable": "presion_succion",
                    },
                ]
            }
        )

        self.assertEqual(
            catalogo.limites,
            {
                ("B-101", "presion_descarga"): {
                    "alarma_alta": 125.0,
                    "alarma_baja": 95.0,
                },
                ("B-102", "vibracion"): {"alarma_alta": 7.1},
            },
        )


if __name__ == "__main__":
    unittest.main()
