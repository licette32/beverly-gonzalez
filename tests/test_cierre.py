from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from planta_contrato import EstadoOrden, NotaCierre, OrdenSistema, Topicos

from sistema.cierres import ManejadorCierres
from sistema.mqtt import ClienteMQTT

TS = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def orden(estado: EstadoOrden, orden_id: str = "O-1") -> OrdenSistema:
    return OrdenSistema(
        id=orden_id,
        ts=TS,
        estado=estado,
        equipo="B-101",
        evento_ids=["E-1"],
        tareas=["T-B-ACE"],
        detiene_equipo=False,
        reduce_inyeccion=False,
        ejecutor="propio",
    )


def nota(orden_id: str = "O-1", empresa: str = "propio") -> NotaCierre:
    return NotaCierre(
        id=f"CIERRE-{orden_id}",
        ts=TS,
        orden_id=orden_id,
        tecnico="T-1",
        empresa=empresa,
        audio_url=None,
        fotos=[],
    )


class RepositorioCierresFalso:
    def __init__(self, ordenes: dict[str, OrdenSistema] | None = None) -> None:
        self.ordenes = {} if ordenes is None else ordenes
        self.guardadas = []

    def obtener(self, orden_id: str) -> OrdenSistema | None:
        return self.ordenes.get(orden_id)

    def guardar(self, orden_actualizada: OrdenSistema) -> None:
        self.guardadas.append(orden_actualizada)
        self.ordenes[orden_actualizada.id] = orden_actualizada

    def guardar_si_estado(self, orden_actualizada, estado_esperado) -> bool:
        actual = self.ordenes.get(orden_actualizada.id)
        if actual is None or actual.estado is not estado_esperado:
            return False
        self.guardar(orden_actualizada)
        return True

    def cargar_pendientes(self) -> list[OrdenSistema]:
        return []


class PublicadorFalso:
    def __init__(self) -> None:
        self.publicados = []

    def __call__(self, topico, modelo) -> None:
        self.publicados.append((topico, modelo))


class TestManejadorCierres(unittest.TestCase):
    def test_cierre_de_aprobada_guarda_y_publica_ejecutada(self):
        repositorio = RepositorioCierresFalso(
            {"O-1": orden(EstadoOrden.aprobada)}
        )
        publicador = PublicadorFalso()
        manejador = ManejadorCierres(repositorio, publicador)

        resultado = manejador(nota())

        self.assertIsNotNone(resultado)
        self.assertIs(resultado.estado, EstadoOrden.ejecutada)
        self.assertEqual(repositorio.guardadas, [resultado])
        self.assertEqual(len(publicador.publicados), 1)
        self.assertEqual(publicador.publicados[0][0], Topicos.ORDENES)
        self.assertIs(publicador.publicados[0][1], resultado)

    def test_cierre_sobre_ejecutada_es_no_op(self):
        repositorio = RepositorioCierresFalso(
            {"O-1": orden(EstadoOrden.ejecutada)}
        )
        publicador = PublicadorFalso()

        resultado = ManejadorCierres(repositorio, publicador)(nota())

        self.assertIsNone(resultado)
        self.assertEqual(repositorio.guardadas, [])
        self.assertEqual(publicador.publicados, [])

    def test_cierre_sobre_pendiente_es_anomalia(self):
        repositorio = RepositorioCierresFalso(
            {"O-1": orden(EstadoOrden.pendiente)}
        )
        publicador = PublicadorFalso()

        with self.assertLogs("sistema.cierres", level="ERROR") as registros:
            resultado = ManejadorCierres(repositorio, publicador)(nota())

        self.assertIsNone(resultado)
        self.assertEqual(repositorio.guardadas, [])
        self.assertEqual(publicador.publicados, [])
        self.assertIn("anomalía en cierre", registros.output[0])

    def test_orden_no_encontrada_es_anomalia(self):
        repositorio = RepositorioCierresFalso()
        publicador = PublicadorFalso()

        with self.assertLogs("sistema.cierres", level="ERROR"):
            resultado = ManejadorCierres(repositorio, publicador)(nota())

        self.assertIsNone(resultado)
        self.assertEqual(repositorio.guardadas, [])
        self.assertEqual(publicador.publicados, [])


class TestCallbackDeCierre(unittest.TestCase):
    def test_cliente_mqtt_despacha_nota_de_cierre(self):
        cliente = ClienteMQTT("broker", 1883, "agente-cli-test")
        recibidas = []
        cliente.al_recibir_cierre = recibidas.append
        cierre = nota()

        cliente._on_message(
            None,
            None,
            SimpleNamespace(
                topic=Topicos.CIERRES,
                payload=json.dumps(cierre.model_dump(mode="json")),
            ),
        )

        self.assertEqual(len(recibidas), 1)
        self.assertEqual(recibidas[0].id, cierre.id)
        self.assertEqual(recibidas[0].orden_id, cierre.orden_id)


if __name__ == "__main__":
    unittest.main()
