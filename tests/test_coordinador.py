import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from planta_contrato import (
    EstadoOrden,
    NotaRecorrida,
    OrdenSistema,
    Repuesto,
    RespuestaOperador,
    Topicos,
)

from sistema.catalogo import CatalogoPlanta
from sistema.coordinador import CoordinadorPartes
from sistema.repositorio import RepositorioMemoria

from test_catalogo import DATOS


class ClienteFalso:
    def __init__(self):
        self.publicados = []

    def publicar(self, topico, modelo):
        self.publicados.append((topico, modelo))


class RepositorioOrdenesFalso:
    def __init__(self, pendientes=(), error=None):
        self.pendientes = list(pendientes)
        self.error = error
        self.llamadas = 0

    def guardar(self, orden):
        return None

    def guardar_si_estado(self, orden, estado_esperado):
        return True

    def obtener(self, orden_id):
        return None

    def cargar_pendientes(self):
        self.llamadas += 1
        if self.error is not None:
            raise self.error
        return list(self.pendientes)

    def ordenes_abiertas(self, equipo):
        return []


def orden_para_reanudar(orden_id, estado) -> OrdenSistema:
    return OrdenSistema(
        id=orden_id,
        ts=datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc),
        estado=estado,
        equipo="B-101",
        evento_ids=[f"evt-{orden_id}"],
        tareas=["T-B-ACE"],
        detiene_equipo=False,
        reduce_inyeccion=False,
        ejecutor="propio",
        repuestos=[Repuesto(codigo="ACE-ISO220", cantidad=1)],
    )


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


class TestCoordinadorReanudacion(unittest.TestCase):
    def setUp(self):
        self.cliente = ClienteFalso()
        self.catalogo = CatalogoPlanta.desde_datos(DATOS)

    def _coordinador(self, repositorio_ordenes=None, cliente=None):
        return CoordinadorPartes(
            ClienteFalso() if cliente is None else cliente,
            RepositorioMemoria(),
            self.catalogo,
            repositorio_ordenes=repositorio_ordenes,
        )

    def test_coordinador_sin_repo_no_toca_postgres(self):
        with patch("sistema.coordinador.log.info") as info:
            coordinador = self._coordinador()
            coordinador.iniciar()
        try:
            self.assertIsNone(coordinador._repositorio_ordenes)
            self.assertEqual(self.cliente.publicados, [])
            self.assertFalse(
                any("reanudación" in str(llamada) for llamada in info.call_args_list)
            )
        finally:
            coordinador.detener()

    def test_coordinador_con_repo_fake_loguea_dos(self):
        borrador = orden_para_reanudar("ORD-BORRADOR", EstadoOrden.borrador)
        pendiente = orden_para_reanudar("ORD-PENDIENTE", EstadoOrden.pendiente)
        repositorio = RepositorioOrdenesFalso([borrador, pendiente])

        with self.assertLogs("sistema.coordinador", level="INFO") as logs:
            coordinador = self._coordinador(
                repositorio_ordenes=repositorio, cliente=self.cliente
            )
        try:
            texto = "\n".join(logs.output)
            self.assertIn("orden borrador reanudada sin publicar", texto)
            self.assertIn(borrador.id, texto)
            self.assertIn("orden pendiente reanudada", texto)
            self.assertIn(pendiente.id, texto)
            self.assertIn("total=2 pendientes=1 borradores=1", texto)
            self.assertEqual(self.cliente.publicados, [])
            self.assertEqual(repositorio.llamadas, 1)
            self.assertEqual(
                [orden.estado for orden in repositorio.pendientes],
                [EstadoOrden.borrador, EstadoOrden.pendiente],
            )
        finally:
            coordinador.detener()

    def test_coordinador_con_repo_que_falla_arranca(self):
        repositorio = RepositorioOrdenesFalso(error=RuntimeError("api caida"))

        with self.assertLogs("sistema.coordinador", level="ERROR") as logs:
            coordinador = self._coordinador(
                repositorio_ordenes=repositorio, cliente=self.cliente
            )
        try:
            self.assertIn(
                "no se pudieron reanudar órdenes pendientes: api caida",
                "\n".join(logs.output),
            )
            coordinador.iniciar()
            self.assertEqual(self.cliente.publicados, [])
        finally:
            coordinador.detener()


if __name__ == "__main__":
    unittest.main()
