from __future__ import annotations

import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

from sistema import main


class TestMainRepositorioOrdenes(unittest.TestCase):
    def _ejecutar(self, dsn):
        repositorio_notas = MagicMock()
        repositorio_ordenes = MagicMock()
        cliente = MagicMock()
        cliente.publicar = MagicMock()
        tiempo = MagicMock()
        tiempo.sleep.side_effect = KeyboardInterrupt

        with ExitStack() as pila:
            repositorio_ordenes_cls = pila.enter_context(
                patch.object(
                    main,
                    "RepositorioOrdenesPostgres",
                    return_value=repositorio_ordenes,
                )
            )
            worker_ordenes = pila.enter_context(
                patch.object(main, "WorkerOrdenes")
            )
            coordinador = pila.enter_context(
                patch.object(main, "CoordinadorPartes")
            )
            worker_sensores = pila.enter_context(
                patch.object(main, "WorkerSensores")
            )
            pila.enter_context(patch.object(main, "POSTGRES_DSN", dsn))
            pila.enter_context(patch.object(main, "Transcriptor"))
            pila.enter_context(
                patch.object(main, "ClienteMQTT", return_value=cliente)
            )
            pila.enter_context(
                patch.object(
                    main, "crear_repositorio", return_value=repositorio_notas
                )
            )
            pila.enter_context(patch.object(main, "CatalogoPlanta"))
            pila.enter_context(patch.object(main, "WorkerNotas"))
            pila.enter_context(patch.object(main, "ManejadorCierres"))
            pila.enter_context(patch.object(main, "Latido"))
            pila.enter_context(patch.object(main, "_lanzar_indexado"))
            pila.enter_context(patch.object(main, "time", tiempo))
            main.main()

        return (
            repositorio_ordenes_cls,
            repositorio_ordenes,
            worker_ordenes,
            coordinador,
            worker_sensores,
        )

    def test_main_arranca_con_repositorio_y_encola_ordenes(self):
        cls, repo, worker, coordinador, worker_sensores = self._ejecutar("dsn-falso")

        cls.assert_called_once_with("dsn-falso")
        worker.assert_called_once()
        self.assertIs(coordinador.call_args.kwargs["repositorio_ordenes"], repo)
        self.assertIsNotNone(coordinador.call_args.kwargs["encolar_orden"])
        self.assertIsNotNone(worker_sensores.call_args.kwargs["encolar_orden"])
        worker.return_value.start.assert_called_once_with()
        coordinador.return_value.reanudar_pendientes.assert_called_once_with()

    def test_main_arranca_sin_dsn_y_desactiva_ordenes(self):
        with self.assertLogs("sistema.main", level="WARNING") as registros:
            cls, repo, worker, coordinador, worker_sensores = self._ejecutar("")

        cls.assert_not_called()
        worker.assert_not_called()
        self.assertIsNone(coordinador.call_args.kwargs["repositorio_ordenes"])
        self.assertIsNone(coordinador.call_args.kwargs["encolar_orden"])
        self.assertIsNone(worker_sensores.call_args.kwargs["encolar_orden"])
        self.assertTrue(
            any("sin repositorio de órdenes" in mensaje for mensaje in registros.output)
        )
        self.assertTrue(
            any("no se reanudan pendientes" in mensaje for mensaje in registros.output)
        )
        coordinador.return_value.reanudar_pendientes.assert_not_called()


if __name__ == "__main__":
    unittest.main()
