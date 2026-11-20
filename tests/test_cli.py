from __future__ import annotations

import unittest
from contextlib import redirect_stderr
from datetime import datetime, timezone
from io import StringIO
from unittest.mock import patch

from planta_contrato import EstadoOrden, OrdenSistema, Topicos

from sistema import cli


TS = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def orden(estado: EstadoOrden, ejecutor: str = "propio") -> OrdenSistema:
    return OrdenSistema(
        id="O-1",
        ts=TS,
        estado=estado,
        equipo="B-101",
        evento_ids=["E-1"],
        tareas=["T-B-ACE"],
        detiene_equipo=False,
        reduce_inyeccion=False,
        ejecutor=ejecutor,
    )


class RepositorioOrdenesFalso:
    def __init__(self, orden_actual: OrdenSistema | None = None) -> None:
        self.orden = orden_actual
        self.guardados = []
        self.llamadas = []

    def obtener(self, orden_id):
        if self.orden is None or self.orden.id != orden_id:
            return None
        return self.orden

    def guardar_si_estado(self, orden_actualizada, estado_esperado) -> bool:
        self.llamadas.append((orden_actualizada, estado_esperado))
        if self.orden is None or self.orden.estado is not estado_esperado:
            return False
        self.orden = orden_actualizada
        self.guardados.append(orden_actualizada)
        return True

    def guardar(self, orden_actualizada) -> None:
        self.guardados.append(orden_actualizada)
        self.orden = orden_actualizada

    def cargar_pendientes(self):
        return []

    def ordenes_abiertas(self, equipo):
        return []


class ClienteFalso:
    def __init__(self) -> None:
        self.publicados = []

    def publicar(self, topico, modelo) -> None:
        self.publicados.append((topico, modelo))


class TestCli(unittest.TestCase):
    def test_aprobar_pendiente_cambia_estado_y_publica(self):
        repositorio = RepositorioOrdenesFalso(orden(EstadoOrden.pendiente))
        cliente = ClienteFalso()

        with self.assertLogs("sistema.cli", level="INFO") as registros:
            codigo = cli.main(
                ["aprobar", "O-1", "--por", "LICETTE"],
                repositorio=repositorio,
                cliente=cliente,
            )

        self.assertEqual(codigo, 0)
        self.assertIs(repositorio.orden.estado, EstadoOrden.aprobada)
        self.assertEqual(len(repositorio.guardados), 1)
        self.assertEqual(len(cliente.publicados), 1)
        self.assertEqual(cliente.publicados[0][0], Topicos.ORDENES)
        self.assertIn("por=LICETTE", registros.output[0])

    def test_aprobar_pendiente_no_pasa_por_el_revisor(self):
        repositorio = RepositorioOrdenesFalso(orden(EstadoOrden.pendiente))
        cliente = ClienteFalso()

        with patch(
            "sistema.flujo.validar_orden_publicable",
            side_effect=AssertionError("el revisor no debe intervenir"),
        ):
            codigo = cli.main(
                ["aprobar", "O-1", "--por", "LICETTE"],
                repositorio=repositorio,
                cliente=cliente,
            )

        self.assertEqual(codigo, 0)
        self.assertIs(repositorio.orden.estado, EstadoOrden.aprobada)
        self.assertEqual(len(cliente.publicados), 1)

    def test_aprobar_rechazada_devuelve_error_sin_cambiar_estado(self):
        repositorio = RepositorioOrdenesFalso(orden(EstadoOrden.rechazada))
        cliente = ClienteFalso()
        stderr = StringIO()

        with redirect_stderr(stderr):
            codigo = cli.main(
                ["aprobar", "O-1", "--por", "LICETTE"],
                repositorio=repositorio,
                cliente=cliente,
            )

        self.assertEqual(codigo, 1)
        self.assertIn("transición inválida", stderr.getvalue())
        self.assertIs(repositorio.orden.estado, EstadoOrden.rechazada)
        self.assertEqual(repositorio.guardados, [])
        self.assertEqual(repositorio.llamadas, [])
        self.assertEqual(cliente.publicados, [])

    def test_orden_no_encontrada(self):
        repositorio = RepositorioOrdenesFalso()
        cliente = ClienteFalso()
        stderr = StringIO()

        with redirect_stderr(stderr):
            codigo = cli.main(
                ["aprobar", "O-1", "--por", "LICETTE"],
                repositorio=repositorio,
                cliente=cliente,
            )

        self.assertEqual(codigo, 1)
        self.assertIn("orden O-1 no encontrada", stderr.getvalue())
        self.assertEqual(cliente.publicados, [])

    def test_por_es_obligatorio(self):
        repositorio = RepositorioOrdenesFalso(orden(EstadoOrden.pendiente))

        with self.assertRaises(SystemExit):
            cli.main(
                ["aprobar", "O-1"],
                repositorio=repositorio,
                cliente=ClienteFalso(),
            )

    def test_certificar_con_habilita_y_monto(self):
        repositorio = RepositorioOrdenesFalso(
            orden(EstadoOrden.ejecutada, ejecutor="contratista")
        )
        cliente = ClienteFalso()

        codigo = cli.main(
            [
                "certificar",
                "O-1",
                "--por",
                "LICETTE",
                "--habilita",
                "HAB-2026-0001",
                "--monto",
                "3800",
            ],
            repositorio=repositorio,
            cliente=cliente,
        )

        self.assertEqual(codigo, 0)
        self.assertIs(repositorio.orden.estado, EstadoOrden.certificada)
        self.assertEqual(repositorio.orden.habilita, "HAB-2026-0001")
        self.assertEqual(repositorio.orden.monto_habilita_usd, 3800)

    def test_cliente_mqtt_propio_usa_sufijo_cli(self):
        repositorio = RepositorioOrdenesFalso(orden(EstadoOrden.ejecutada))

        with patch.object(cli, "ClienteMQTT") as clase_cliente:
            codigo = cli.main(
                ["cerrar", "O-1", "--por", "LICETTE"],
                repositorio=repositorio,
            )

        self.assertEqual(codigo, 0)
        clase_cliente.assert_called_once_with(
            cli.MQTT_HOST, cli.MQTT_PORT, f"{cli.SISTEMA}-cli"
        )
        clase_cliente.return_value.conectar.assert_called_once_with()
        clase_cliente.return_value.publicar.assert_called_once()
        clase_cliente.return_value.cerrar.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
