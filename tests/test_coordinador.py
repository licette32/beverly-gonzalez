import time
import unittest
from datetime import datetime, timezone

from planta_contrato import NotaRecorrida, RespuestaOperador, Topicos

from sistema.catalogo import CatalogoPlanta
from sistema.coordinador import CoordinadorPartes
from sistema.repositorio import RepositorioMemoria

from test_catalogo import DATOS


class ClienteFalso:
    def __init__(self):
        self.publicados = []

    def publicar(self, topico, modelo):
        self.publicados.append((topico, modelo))


def nota(nota_id="NOTA-00010") -> NotaRecorrida:
    return NotaRecorrida(
        id=nota_id,
        ts=datetime(2026, 11, 5, 9, 40, tzinfo=timezone.utc),
        operador="operador-1",
        audio_url=None,
        fotos=[],
        recorrida_id="REC-1",
    )


def respuesta(mensaje_id: str, texto: str) -> RespuestaOperador:
    return RespuestaOperador(
        id=f"RESP-{mensaje_id}",
        ts=datetime(2026, 11, 5, 9, 41, tzinfo=timezone.utc),
        mensaje_id=mensaje_id,
        operador="operador-1",
        texto=texto,
        audio_url=None,
    )


class TestCoordinador(unittest.TestCase):
    def setUp(self):
        self.cliente = ClienteFalso()
        self.repo = RepositorioMemoria()
        self.catalogo = CatalogoPlanta.desde_datos(DATOS)
        self.coordinador = CoordinadorPartes(
            self.cliente, self.repo, self.catalogo, timeout_pregunta_s=0.05
        )
        self.coordinador.iniciar()

    def tearDown(self):
        self.coordinador.detener()

    def tablet(self):
        return [
            modelo
            for topico, modelo in self.cliente.publicados
            if topico == Topicos.TABLET
        ]

    def eventos(self):
        return [
            modelo
            for topico, modelo in self.cliente.publicados
            if topico == Topicos.EVENTOS
        ]

    def esperar_estado(self, nota_id, esperado, limite=1.0):
        fin = time.time() + limite
        while time.time() < fin:
            estado = self.repo.obtener_nota(nota_id)
            if estado is not None and estado.estado == esperado:
                return estado
            time.sleep(0.01)
        self.fail(f"no llegó al estado {esperado}")

    def test_nota_clara_publica_b1_y_borrador(self):
        self.coordinador.procesar_nota(
            nota(),
            "La dos está en mil seiscientos diez libras de descarga.",
            [],
        )
        estado = self.repo.obtener_nota("NOTA-00010")
        self.assertIsNotNone(estado)
        self.assertEqual(estado.estado, "BORRADOR")
        self.assertEqual(len(self.eventos()), 1)
        tablet = self.tablet()
        self.assertEqual(len(tablet), 1)
        self.assertEqual(tablet[0].pantalla.filas[0].valor, 1610.0)
        self.assertEqual(tablet[0].pantalla.opciones, [])

        self.coordinador.encolar_respuesta(respuesta(tablet[0].id, "Sí, confirmo."))
        self.esperar_estado("NOTA-00010", "CONFIRMADO")

    def test_pregunta_de_equipo_y_respuesta(self):
        texto = "La bomba está parada, en reserva."
        self.coordinador.procesar_nota(nota(), texto, [])
        estado = self.repo.obtener_nota("NOTA-00010")
        self.assertEqual(estado.estado, "PREGUNTA")
        pregunta = self.tablet()[0]
        self.assertIn("B-102 (la dos)", pregunta.pantalla.opciones)

        self.coordinador.encolar_respuesta(respuesta(pregunta.id, "Era la dos."))
        estado = self.esperar_estado("NOTA-00010", "BORRADOR")
        self.assertEqual(estado.items[0].tag, "B-102")
        self.assertTrue(any(evento.equipo == "B-102" for evento in self.eventos()))

    def test_timeout_publica_borrador_marcado_y_b1(self):
        texto = "La bomba está parada, en reserva."
        self.coordinador.procesar_nota(nota(), texto, [])
        estado = self.esperar_estado("NOTA-00010", "BORRADOR", limite=1.0)
        self.assertIsNone(estado.pregunta)
        self.assertIn("sin respuesta del operador", estado.borrador[0].observacion)
        self.assertTrue(any(evento.equipo is None for evento in self.eventos()))


if __name__ == "__main__":
    unittest.main()
