import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from planta_contrato import EstadoOrden, OrdenSistema, Repuesto

from sistema.validacion import Problema, validar_orden_publicable


def _orden(repuestos=()):
    return OrdenSistema(
        id="O-1",
        ts=datetime(2026, 1, 1, tzinfo=timezone.utc),
        estado=EstadoOrden.borrador,
        equipo="B-101",
        evento_ids=[],
        tareas=["T-B-ACE"],
        detiene_equipo=False,
        reduce_inyeccion=False,
        ejecutor="propio",
        repuestos=list(repuestos),
    )


def _materiales(*codigos):
    return {"lista_materiales": {"B-101": list(codigos)}}


class TestValidarOrdenPublicable(unittest.TestCase):
    def test_cita_inventada(self):
        with (
            patch("sistema.causas.verificar_cita", return_value=False),
            patch("sistema.tools._fragmentos_manuales", return_value={}),
        ):
            problemas = validar_orden_publicable(
                _orden(), ["MBP-4 §99.99"], _materiales("ACE-ISO220")
            )

        self.assertEqual(
            problemas, (Problema("CITA_INEXISTENTE", "MBP-4 §99.99"),)
        )

    def test_cita_vencida(self):
        fragmento = SimpleNamespace(vigente=False, doc="TX350-D", tipo="procedimiento")
        with (
            patch("sistema.causas.verificar_cita", return_value=False),
            patch(
                "sistema.tools._fragmentos_manuales",
                return_value={"TX350-D §3.2": fragmento},
            ),
        ):
            problemas = validar_orden_publicable(
                _orden(), ["TX350-D §3.2"], _materiales("ACE-ISO220")
            )

        self.assertEqual(len(problemas), 1)
        self.assertEqual(problemas[0].codigo, "CITA_VENCIDA")
        self.assertEqual(problemas[0].detalle, "TX350-D §3.2")

    def test_cita_no_verificable(self):
        with patch(
            "sistema.causas.verificar_cita", side_effect=RuntimeError("api caida")
        ):
            problemas = validar_orden_publicable(
                _orden(), ["MBP-4 §13.2"], _materiales("ACE-ISO220")
            )

        self.assertEqual(
            problemas, (Problema("CITA_NO_VERIFICABLE", "MBP-4 §13.2"),)
        )

    def test_repuesto_fuera_de_lista(self):
        orden = _orden([Repuesto(codigo="FC-CART-25", cantidad=1)])
        with patch("sistema.causas.verificar_cita", return_value=True):
            problemas = validar_orden_publicable(
                orden, ["MBP-4 §13.2"], _materiales("ACE-ISO220")
            )

        self.assertEqual(len(problemas), 1)
        self.assertEqual(problemas[0].codigo, "REPUESTO_FUERA_DE_LISTA")
        self.assertEqual(problemas[0].detalle, "FC-CART-25")

    def test_orden_sin_problemas_devuelve_vacio(self):
        orden = _orden([Repuesto(codigo="ACE-ISO220", cantidad=2)])
        with patch("sistema.causas.verificar_cita", return_value=True):
            problemas = validar_orden_publicable(
                orden, ["MBP-4 §13.2"], _materiales("ACE-ISO220")
            )

        self.assertEqual(problemas, ())

    def test_cita_vigente_simulada(self):
        orden = _orden([Repuesto(codigo="ACE-ISO220", cantidad=2)])
        with patch("sistema.causas.verificar_cita", return_value=True):
            problemas = validar_orden_publicable(
                orden, ["MBP-4 §13.2"], _materiales("ACE-ISO220")
            )

        self.assertEqual(problemas, ())


if __name__ == "__main__":
    unittest.main()
