import unittest
from datetime import datetime, timezone

from planta_contrato import NotaRecorrida, RespuestaOperador

from sistema.borradores import borrador
from sistema.parte import ItemParte
from sistema.repositorio import (
    EstadoNota,
    RepositorioMemoria,
    RepositorioSincronizado,
    crear_repositorio,
)


def nota() -> NotaRecorrida:
    return NotaRecorrida(
        id="NOTA-00010",
        ts=datetime(2026, 11, 5, 9, 40, tzinfo=timezone.utc),
        operador="operador-1",
        audio_url=None,
        fotos=[],
        recorrida_id="REC-1",
    )


def estado() -> EstadoNota:
    items = [ItemParte("B-102", "presion_descarga_local", 1610.0, "psi")]
    mensaje = borrador(nota(), items, 0)
    return EstadoNota(
        nota_id=nota().id,
        mensaje=mensaje,
        nota=nota(),
        borrador=mensaje.pantalla.filas,
        items=items,
        texto="La dos está en mil seiscientos diez libras.",
    )


class TestRepositorioMemoria(unittest.TestCase):
    def test_guarda_y_busca_por_nota_y_mensaje(self):
        repo = RepositorioMemoria()
        actual = estado()
        repo.guardar_estado(actual)
        self.assertIs(repo.obtener_nota("NOTA-00010"), actual)
        self.assertIs(repo.obtener_por_mensaje(actual.mensaje.id), actual)
        self.assertIsNone(repo.obtener_por_mensaje("otro"))

    def test_guarda_respuesta(self):
        repo = RepositorioMemoria()
        actual = estado()
        repo.guardar_estado(actual)
        respuesta = RespuestaOperador(
            id="RESP-1",
            ts=datetime(2026, 11, 5, 9, 41, tzinfo=timezone.utc),
            mensaje_id=actual.mensaje.id,
            operador="operador-1",
            texto="Sí, confirmo.",
            audio_url=None,
        )
        repo.guardar_respuesta(respuesta)
        self.assertEqual(repo.respuestas(), [respuesta])
        self.assertEqual(repo.pendientes_sincronizar(), 0)


class TestRepositorioSincronizado(unittest.TestCase):
    def test_sin_dsn_usa_memoria(self):
        repo = crear_repositorio("")
        self.assertIsInstance(repo, RepositorioMemoria)
        self.assertNotIsInstance(repo, RepositorioSincronizado)

    def test_sin_conexion_no_bloquea_y_deja_pendientes(self):
        repo = crear_repositorio("postgresql://u:p@127.0.0.1:1/nada")
        actual = estado()
        repo.guardar_estado(actual)
        self.assertEqual(repo.pendientes_sincronizar(), 1)
        self.assertIs(repo.obtener_nota("NOTA-00010"), actual)


if __name__ == "__main__":
    unittest.main()
