import unittest

from sistema.seguridad import detectar


def categorias(texto):
    return {d.categoria for d in detectar(texto)}


class TestSeguridad(unittest.TestCase):
    def comprobar(self, frases, esperado):
        for frase in frases:
            with self.subTest(frase=frase):
                self.assertEqual(categorias(frase), esperado)

    def test_s1_agua_a_presion(self):
        self.comprobar([
            "¡Atención! Se rompió algo en la descarga de la uno, sale agua a presión para todos lados, me alejé. Saqué foto desde lejos.",
            "Se rompió un niple en la descarga de la dos y sale un chorro de agua a presión.",
            "Hay una pérdida grande en la descarga de la bomba, el agua sale con fuerza para todos lados.",
        ], {"S1"})

    def test_s1_no_confundir_con_goteo_ni_lecturas(self):
        self.comprobar([
            "La dos pierde bastante por la empaquetadura.",
            "La tres sigue goteando por la empaquetadura, le saqué foto.",
            "La bomba tiene una pérdida por la empaquetadura, pero no hay chorro ni proyección.",
            "Probé a ciento diez kilos, sin pérdida.",
            "La presión de descarga de la uno está normal, sin pérdidas.",
            "La uno está en ciento catorce kilos de descarga, el rodamiento me dio sesenta y cuatro grados con la pistola.",
        ], set())

    def test_s2_olor_a_gas(self):
        self.comprobar([
            "Hay olor a gas fuerte del lado del portón, viene del lado del separador.",
            "Se siente olor a gas cerca del separador.",
            "Hay una pérdida de gas en el portón, se siente fuerte.",
        ], {"S2"})

    def test_s2_negaciones(self):
        self.comprobar([
            "No hay olor a gas en el sector del separador.",
            "No se siente olor a gas, todo normal.",
            "Hay olor a solvente, no a gas.",
        ], set())

    def test_s3_humo_o_quemado(self):
        self.comprobar([
            "Sale humo del motor de la uno, hay olor a quemado.",
            "El motor de la dos está humeando y huele a quemado.",
            "Hay olor a quemado en el motor de la tres.",
            "Se prendió fuego en el motor.",
        ], {"S3"})

    def test_s3_negaciones_y_parecidas(self):
        self.comprobar([
            "No hay humo ni olor a quemado en el motor.",
            "El motor está caliente, pero no hay humo ni olor a quemado.",
            "Sale vapor del motor, no es humo.",
            "La humedad en el piso de la sala es normal.",
            "Sin humo ni pérdidas en la uno.",
        ], set())

    def test_s4_persona_lesionada(self):
        self.comprobar([
            "Mi compañero se golpeó la mano con la llave en el skid de filtros, está sangrando bastante.",
            "Un operario se cayó de la escalera y no puede mover la pierna.",
            "Se lastimó un dedo con la llave y está sangrando.",
        ], {"S4"})

    def test_s4_negaciones_y_parecidas(self):
        self.comprobar([
            "No hay nadie lesionado, todos estamos bien.",
            "Me golpeé el casco, pero estoy bien.",
            "No hubo accidentes en la recorrida.",
            "Se cayó la presión de succión en la tres.",
        ], set())

    def test_nota_normal(self):
        self.assertEqual(categorias("Recorrida sin novedad, todo normal."), set())

    def test_varias_categorias_juntas(self):
        self.assertEqual(
            categorias("Sale humo del motor y hay olor a gas."), {"S2", "S3"}
        )

    def test_sin_tildes_y_en_mayusculas(self):
        self.assertEqual(
            categorias("SE ROMPIO UN NIPLE, SALE AGUA A PRESION PARA TODOS LADOS"),
            {"S1"},
        )

    def test_una_sola_deteccion_por_categoria(self):
        self.assertEqual(len(detectar("Humo, humo, mucho humo en el motor.")), 1)

    def test_s1_transcripcion_real_de_whisper(self):
        self.comprobar([
            "Atención, se rompió algo en la descarga del A1, sale agua a presión para todos lados, me alejé, saqué foto desde lejos.",
            "atención se rompió algo en la descarga de la uno sale agua a presión para todos lados me alejé saqué foto desde lejos",
        ], {"S1"})        

        
    def test_negacion_no_cruza_de_una_frase_a_otra(self):
        self.assertEqual(
            categorias("Sin novedad en la uno. Sale agua a presión por la descarga."), {"S1"}
        )
        self.assertEqual(
            categorias("No hubo accidentes. Un compañero se lastimó."), {"S4"}
        )

    def test_agua_suelta_no_es_s1(self):
        self.assertEqual(categorias("Hay agua en el piso de la sala de bombas."), set())
        self.assertEqual(
            categorias("Sale humo del motor y hay agua en el piso."), {"S3"}
        )

    def test_s1_mas_formas_de_proyeccion(self):
        self.comprobar([
            "sale agua con mucha presión por la descarga de la bomba",
            "sale agua a mucha presión",
            "sale agua apresión por el niple",
        ], {"S1"})

    def test_s1_negaciones_y_presion_normal(self):
        self.comprobar([
            "no hay pérdida de agua a presión en la descarga",
            "no hay ninguna fuga de agua a presión",
            "la descarga tiene agua a presión normal",
        ], set())

    def test_s2_mas_formas(self):
        self.comprobar([
            "hay una fuga en la línea de gas",
            "escape de gas en el separador",
            "me parece que hay gas en el sector",
        ], {"S2"})

    def test_s2_negaciones_ampliadas(self):
        self.comprobar([
            "tampoco hay olor a gas",
            "nunca hubo olor a gas en el sector",
        ], set())

    def test_s3_mas_formas(self):
        self.comprobar([
            "está saliendo humito del motor",
            "el motor está incendiándose",
        ], {"S3"})

    def test_s3_quemado_suelto_no_alcanza(self):
        self.assertEqual(categorias("hay un cable quemado en el tablero"), set())

    def test_s3_negaciones_ampliadas(self):
        self.comprobar([
            "no hay humo en el motor, tampoco olor a quemado",
            "tampoco hay humo en el motor",
        ], set())

    def test_s4_mas_formas_de_lesion(self):
        self.comprobar([
            "un operario se golpeó la cabeza con la viga y está mareado",
            "se cortó la mano, le salió sangre",
            "se desmayó el operario",
            "el compañero se torció el tobillo",
            "se electrocutó un técnico",
            "una compañera se cayó de la escalera",
        ], {"S4"})

    def test_s4_sangrado_de_linea_no_es_accidente(self):
        self.comprobar([
            "estoy sangrando la línea de descarga para purgar el aire",
            "el técnico está sangrando el manómetro",
        ], set())

    def test_casos_dudosos_decididos(self):
        self.comprobar([
            "hay humo en el tablero eléctrico",
            "olor a quemado en el tablero de control",
        ], {"S3"})
        self.comprobar([
            "se cayó un compañero pero está bien",
        ], {"S4"})
        self.comprobar([
            "sale vapor del motor, no es humo",
            "el motor está caliente, pero no quemado",
            "hay olor a gasoil",
        ], set())