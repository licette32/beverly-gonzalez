import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from sistema import indexar
from sistema.config import PLANTA_BASE_URL


class TestIndexarDesdeApi(unittest.TestCase):
    def test_main_carga_desde_api_y_muestra_conteo_real(self):
        fragmentos = [MagicMock(), MagicMock()]
        modelo = MagicMock()
        salida = io.StringIO()
        with (
            patch.object(indexar, "INDEXAR_PG_AL_ARRANCAR", "1"),
            patch.object(
                indexar, "cargar_desde_api", return_value=fragmentos
            ) as cargar,
            patch.object(indexar, "obtener_modelo", return_value=modelo),
            patch.object(indexar, "crear_tabla") as crear,
            patch.object(indexar, "indexar", return_value=2) as insertar,
            redirect_stdout(salida),
        ):
            indexar.main()

        cargar.assert_called_once_with(PLANTA_BASE_URL)
        crear.assert_called_once_with()
        insertar.assert_called_once_with(fragmentos, modelo)
        self.assertIn("Fragmentos cargados: 2", salida.getvalue())
        self.assertIn("Fragmentos con embedding: 2", salida.getvalue())

        fuente = Path(indexar.__file__).read_text(encoding="utf-8")
        self.assertNotIn("novit-curso", fuente)
        self.assertNotIn("documentos", fuente)

    def test_main_respeta_flag_de_arranque(self):
        salida = io.StringIO()
        with (
            patch.object(indexar, "INDEXAR_PG_AL_ARRANCAR", "0"),
            patch.object(indexar, "cargar_desde_api") as cargar,
            redirect_stdout(salida),
        ):
            indexar.main()

        cargar.assert_not_called()
        self.assertIn("Indexado desactivado", salida.getvalue())


if __name__ == "__main__":
    unittest.main()
