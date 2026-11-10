import unittest
from datetime import datetime, timezone

from planta_contrato import EstadoSistema


class TestContrato(unittest.TestCase):
    def test_latido_valido(self) -> None:
        estado = EstadoSistema(
            ts=datetime.now(timezone.utc),
            sistema="test",
            enlace_ok=True,
            pendientes_sincronizar=0,
        )
        datos = estado.model_dump(mode="json")
        self.assertEqual(datos["sistema"], "test")
        self.assertTrue(datos["enlace_ok"])
        self.assertIn("ts", datos)


if __name__ == "__main__":
    unittest.main()
