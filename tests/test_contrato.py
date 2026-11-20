import json
import threading
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from planta_contrato import EstadoSistema, Topicos

from sistema.heartbeat import ColaPendientes, Latido, SondaEnlace


class _Respuesta:
    def __init__(self, contenido='{"arriba": true}') -> None:
        if isinstance(contenido, str):
            self.contenido = contenido.encode()
        else:
            self.contenido = json.dumps(contenido).encode()

    def read(self):
        return self.contenido

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> bool:
        return False


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


class TestColaPendientes(unittest.TestCase):
    def test_solo_cuenta_durante_el_corte_y_limpia_al_volver(self) -> None:
        cola = ColaPendientes()
        self.assertTrue(cola.arriba)

        cola.agregar("evento:1")
        self.assertEqual(cola.cantidad(), 0)

        cola.actualizar_enlace(False)
        cola.agregar("evento:1")
        cola.agregar("evento:1")
        cola.agregar("fotos:2")
        self.assertEqual(cola.ids(), ("evento:1", "fotos:2"))
        self.assertFalse(cola.actualizar_enlace(False))

        self.assertTrue(cola.actualizar_enlace(True))
        self.assertEqual(cola.cantidad(), 0)
        cola.agregar("evento:3")
        self.assertEqual(cola.cantidad(), 0)


class TestSondaEnlace(unittest.TestCase):
    def test_transiciones_true_false_true(self) -> None:
        cambios: list[bool] = []
        sonda = SondaEnlace(
            url="http://destino/estado",
            timeout_s=2,
            intervalo_s=0.01,
            urlopen=lambda url, timeout: _Respuesta(),
            al_cambio=cambios.append,
        )
        self.assertTrue(sonda.arriba)
        self.assertTrue(sonda.probar())
        self.assertEqual(cambios, [])

        def sin_respuesta(url, timeout):
            raise OSError("enlace caído")

        sonda._urlopen = sin_respuesta
        self.assertFalse(sonda.probar())
        self.assertEqual(cambios, [False])

        sonda._urlopen = lambda url, timeout: _Respuesta()
        self.assertTrue(sonda.probar())
        self.assertEqual(cambios, [False, True])

    def test_sonda_lee_arriba_del_json(self) -> None:
        sonda = SondaEnlace(
            url="http://destino/estado",
            urlopen=lambda url, timeout: _Respuesta({"arriba": False}),
        )
        self.assertFalse(sonda.probar())

        sonda._urlopen = lambda url, timeout: _Respuesta({"arriba": True})
        self.assertTrue(sonda.probar())

        sonda._urlopen = lambda url, timeout: _Respuesta("no-json")
        self.assertFalse(sonda.probar())

        sonda._urlopen = lambda url, timeout: _Respuesta({})
        self.assertFalse(sonda.probar())

    def test_sonda_colgada_no_bloquea_el_latido(self) -> None:
        liberar = threading.Event()

        def colgado(url, timeout):
            liberar.wait(1)
            return _Respuesta()

        sonda = SondaEnlace(
            url="http://destino/estado",
            timeout_s=2,
            intervalo_s=0.01,
            urlopen=colgado,
        )
        sonda.start()
        try:
            cliente = MagicMock()
            latido = Latido(
                cliente,
                "test",
                30,
                pendientes=lambda: 4,
                enlace_ok=lambda: sonda.arriba,
            )
            inicio = time.perf_counter()
            latido._publicar()
            self.assertLess(time.perf_counter() - inicio, 0.5)
            topico, estado = cliente.publicar.call_args.args
            self.assertEqual(topico, Topicos.ESTADO)
            self.assertEqual(estado.pendientes_sincronizar, 4)
        finally:
            liberar.set()
            sonda.detener()
            sonda.join(timeout=1)

    def test_latido_usa_ultimo_estado_del_enlace(self) -> None:
        cliente = MagicMock()
        latido = Latido(
            cliente,
            "test",
            30,
            pendientes=lambda: 2,
            enlace_ok=lambda: False,
        )
        latido._publicar()
        _topico, estado = cliente.publicar.call_args.args
        self.assertFalse(estado.enlace_ok)
        self.assertEqual(estado.pendientes_sincronizar, 2)


if __name__ == "__main__":
    unittest.main()
