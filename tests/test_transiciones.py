from __future__ import annotations

import unittest
from datetime import datetime, timezone

from planta_contrato import EstadoOrden, NotaCierre, OrdenSistema

from sistema.transiciones import (
    Accion,
    ErrorTransicion,
    transicionar,
    validar_cambio,
)

TS = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def orden(estado: EstadoOrden, ejecutor: str = "propio", **campos) -> OrdenSistema:
    datos = dict(
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
    datos.update(campos)
    return OrdenSistema(**datos)


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


class TestTablaDeTransiciones(unittest.TestCase):
    def test_validar_cambio_de_borrador_a_aprobada(self):
        self.assertIs(
            validar_cambio(orden(EstadoOrden.borrador), EstadoOrden.aprobada),
            Accion.evaluar,
        )

    def test_validar_cambio_de_borrador_a_pendiente(self):
        self.assertIs(
            validar_cambio(orden(EstadoOrden.borrador), EstadoOrden.pendiente),
            Accion.evaluar,
        )

    def test_validar_cambio_rechaza_salto_de_rechazada_a_aprobada(self):
        with self.assertRaises(ErrorTransicion):
            validar_cambio(orden(EstadoOrden.rechazada), EstadoOrden.aprobada)


class TestTransicionesValidas(unittest.TestCase):
    def test_aprobar_pendiente(self):
        resultado = transicionar(orden(EstadoOrden.pendiente), Accion.aprobar)

        self.assertIs(resultado.estado, EstadoOrden.aprobada)

    def test_rechazar_pendiente_con_motivo(self):
        resultado = transicionar(
            orden(EstadoOrden.pendiente), Accion.rechazar, "fuera de lista"
        )

        self.assertIs(resultado.estado, EstadoOrden.rechazada)
        self.assertEqual(resultado.motivo, "fuera de lista")

    def test_registrar_cierre_de_aprobada_propia(self):
        resultado = transicionar(
            orden(EstadoOrden.aprobada), Accion.registrar_cierre, nota=nota()
        )

        self.assertIs(resultado.estado, EstadoOrden.ejecutada)

    def test_registrar_cierre_de_contratista_por_categoria(self):
        contratista = orden(
            EstadoOrden.aprobada, ejecutor="contratista (Servipat)"
        )

        resultado = transicionar(
            contratista, Accion.registrar_cierre, nota=nota(empresa="Servipat")
        )

        self.assertIs(resultado.estado, EstadoOrden.ejecutada)

    def test_cerrar_ejecutada_propia(self):
        resultado = transicionar(orden(EstadoOrden.ejecutada), Accion.cerrar)

        self.assertIs(resultado.estado, EstadoOrden.cerrada)

    def test_certificar_ejecutada_de_contratista(self):
        contratista = orden(EstadoOrden.ejecutada, ejecutor="contratista")

        resultado = transicionar(
            contratista,
            Accion.certificar,
            habilita="HAB-2026-0001",
            monto_habilita_usd=3800,
        )

        self.assertIs(resultado.estado, EstadoOrden.certificada)
        self.assertEqual(resultado.habilita, "HAB-2026-0001")
        self.assertEqual(resultado.monto_habilita_usd, 3800)

    def test_observar_ejecutada_de_contratista_con_motivo(self):
        contratista = orden(EstadoOrden.ejecutada, ejecutor="contratista")

        resultado = transicionar(
            contratista, Accion.observar, "declara un repuesto de más"
        )

        self.assertIs(resultado.estado, EstadoOrden.observada)
        self.assertEqual(resultado.motivo, "declara un repuesto de más")


class TestTransicionesInvalidas(unittest.TestCase):
    def test_aprobar_rechazada(self):
        with self.assertRaises(ErrorTransicion):
            transicionar(orden(EstadoOrden.rechazada), Accion.aprobar)

    def test_rechazar_aprobada(self):
        with self.assertRaises(ErrorTransicion):
            transicionar(orden(EstadoOrden.aprobada), Accion.rechazar, "no")

    def test_cerrar_no_ejecutada(self):
        with self.assertRaises(ErrorTransicion):
            transicionar(orden(EstadoOrden.aprobada), Accion.cerrar)

    def test_cerrar_contratista(self):
        with self.assertRaises(ErrorTransicion):
            transicionar(
                orden(EstadoOrden.ejecutada, ejecutor="contratista"),
                Accion.cerrar,
            )

    def test_cerrar_certificada(self):
        with self.assertRaises(ErrorTransicion):
            transicionar(orden(EstadoOrden.certificada), Accion.cerrar)

    def test_cerrar_observada(self):
        with self.assertRaises(ErrorTransicion):
            transicionar(orden(EstadoOrden.observada), Accion.cerrar)

    def test_certificar_propio(self):
        with self.assertRaises(ErrorTransicion):
            transicionar(
                orden(EstadoOrden.ejecutada),
                Accion.certificar,
                habilita="HAB-2026-0001",
                monto_habilita_usd=3800,
            )

    def test_certificar_sin_habilita(self):
        with self.assertRaises(ErrorTransicion):
            transicionar(
                orden(EstadoOrden.ejecutada, ejecutor="contratista"),
                Accion.certificar,
                monto_habilita_usd=3800,
            )

    def test_certificar_sin_monto(self):
        with self.assertRaises(ErrorTransicion):
            transicionar(
                orden(EstadoOrden.ejecutada, ejecutor="contratista"),
                Accion.certificar,
                habilita="HAB-2026-0001",
            )

    def test_observar_propio(self):
        with self.assertRaises(ErrorTransicion):
            transicionar(
                orden(EstadoOrden.ejecutada), Accion.observar, "motivo"
            )

    def test_observar_sin_motivo(self):
        with self.assertRaises(ErrorTransicion):
            transicionar(
                orden(EstadoOrden.ejecutada, ejecutor="contratista"),
                Accion.observar,
            )

    def test_registrar_cierre_sobre_pendiente(self):
        with self.assertRaises(ErrorTransicion):
            transicionar(
                orden(EstadoOrden.pendiente),
                Accion.registrar_cierre,
                nota=nota(),
            )

    def test_registrar_cierre_con_empresa_distinta(self):
        with self.assertRaises(ErrorTransicion):
            transicionar(
                orden(EstadoOrden.aprobada),
                Accion.registrar_cierre,
                nota=nota(empresa="Servipat"),
            )

    def test_registrar_cierre_sobre_ejecutada_es_no_op(self):
        ejecutada = orden(EstadoOrden.ejecutada)

        resultado = transicionar(
            ejecutada, Accion.registrar_cierre, nota=nota()
        )

        self.assertIs(resultado, ejecutada)


if __name__ == "__main__":
    unittest.main()
