import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from planta_contrato import MensajeTablet, NotaRecorrida, Topicos

from sistema.catalogo import CatalogoPlanta
from sistema.coordinador import CoordinadorPartes
from sistema.corte import MAX_CORRECCIONES, mensaje_corte
from sistema.repositorio import RepositorioMemoria
from sistema.worker import TrabajoNota, WorkerNotas

from test_catalogo import DATOS
from test_coordinador import ClienteFalso, nota, respuesta

CORRECCION = "No. La uno estaba en ciento doce kilos, no en ciento dos. Con eso está."


class CoordinadorFalso:
    def __init__(self):
        self.textos = []

    def procesar_nota(self, nota, texto, detecciones):
        self.textos.append(texto)


class TranscriptorFalso:
    def __init__(self, demora_s=0.0, falla=False):
        self.demora_s = demora_s
        self.falla = falla

    def transcribir(self, ruta):
        time.sleep(self.demora_s)
        if self.falla:
            raise RuntimeError("falla simulada")
        return "la uno esta en ciento doce kilos de descarga"


def audio_temporal() -> Path:
    archivo = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    archivo.close()
    return Path(archivo.name)


class CorteWorkerTest(unittest.TestCase):
    def armar(self, transcriptor, limite_s):
        self.cliente = ClienteFalso()
        self.coordinador = CoordinadorFalso()
        worker = WorkerNotas(
            self.cliente, transcriptor, self.coordinador, limite_transcripcion_s=limite_s
        )
        self.addCleanup(worker.detener)
        return worker

    def procesar(self, worker):
        ruta = audio_temporal()
        worker._procesar(TrabajoNota(nota("NOTA-00099"), time.perf_counter(), ruta))
        return ruta

    def test_dentro_del_limite_sigue_el_flujo_normal(self):
        worker = self.armar(TranscriptorFalso(0.0), 5.0)
        ruta = self.procesar(worker)
        self.assertEqual(len(self.coordinador.textos), 1)
        self.assertEqual(self.cliente.publicados, [])
        self.assertFalse(ruta.exists())

    def test_si_se_agota_el_tiempo_avisa_y_no_procesa(self):
        worker = self.armar(TranscriptorFalso(1.0), 0.1)
        self.procesar(worker)
        self.assertEqual(self.coordinador.textos, [])
        self.assertEqual(len(self.cliente.publicados), 1)
        topico, mensaje = self.cliente.publicados[0]
        self.assertEqual(topico, Topicos.TABLET)
        self.assertIsInstance(mensaje, MensajeTablet)
        self.assertFalse(mensaje.espera_respuesta)
        self.assertEqual(mensaje.nota_ids, ["NOTA-00099"])

    def test_el_corte_nunca_publica_eventos_de_planta(self):
        worker = self.armar(TranscriptorFalso(1.0), 0.1)
        self.procesar(worker)
        topicos = [t for t, _ in self.cliente.publicados]
        self.assertNotIn(Topicos.EVENTOS, topicos)

    def test_si_falla_la_transcripcion_tambien_avisa(self):
        worker = self.armar(TranscriptorFalso(falla=True), 5.0)
        self.procesar(worker)
        self.assertEqual(self.coordinador.textos, [])
        self.assertEqual(len(self.cliente.publicados), 1)

    def test_si_falla_la_descarga_avisa(self):
        worker = self.armar(TranscriptorFalso(), 5.0)

        def falla(nota_id, audio_url):
            raise RuntimeError("sin red")

        worker._descargar = falla
        n = NotaRecorrida(
            id="NOTA-00098",
            ts=datetime(2026, 11, 5, 9, 40, tzinfo=timezone.utc),
            operador="operador-1",
            audio_url="/media/audios/NOTA-00098.wav",
            fotos=[],
            recorrida_id="REC-1",
        )
        worker._descargar_nota(TrabajoNota(n, time.perf_counter()))
        self.assertEqual(len(self.cliente.publicados), 1)
        self.assertEqual(self.cliente.publicados[0][0], Topicos.TABLET)

    def test_el_mensaje_de_corte_es_estable(self):
        a = mensaje_corte(nota("NOTA-00099"), "transcripcion")
        b = mensaje_corte(nota("NOTA-00099"), "transcripcion")
        c = mensaje_corte(nota("NOTA-00099"), "correcciones")
        self.assertEqual(a.id, b.id)
        self.assertNotEqual(a.id, c.id)


class LimiteCorreccionesTest(unittest.TestCase):
    def setUp(self):
        self.cliente = ClienteFalso()
        self.repositorio = RepositorioMemoria()
        self.coordinador = CoordinadorPartes(
            self.cliente, self.repositorio, CatalogoPlanta.desde_datos(DATOS)
        )
        self.coordinador.procesar_nota(
            nota("NOTA-00099"), "la uno esta en ciento dos kilos de descarga", []
        )
        self.borrador = self.cliente.publicados[-1][1]

    def test_correccion_dentro_del_limite_publica_nuevo_borrador(self):
        self.coordinador._procesar_respuesta(respuesta(self.borrador.id, CORRECCION))
        estado = self.repositorio.obtener_nota("NOTA-00099")
        self.assertEqual(estado.intento, 1)
        self.assertTrue(self.cliente.publicados[-1][1].espera_respuesta)

    def test_al_llegar_al_maximo_avisa_y_no_corrige(self):
        estado = self.repositorio.obtener_nota("NOTA-00099")
        estado.intento = MAX_CORRECCIONES
        self.repositorio.guardar_estado(estado)
        antes = list(estado.items)
        self.coordinador._procesar_respuesta(respuesta(self.borrador.id, CORRECCION))
        topico, mensaje = self.cliente.publicados[-1]
        self.assertEqual(topico, Topicos.TABLET)
        self.assertFalse(mensaje.espera_respuesta)
        self.assertIn("máximo", mensaje.texto)
        self.assertEqual(self.repositorio.obtener_nota("NOTA-00099").items, antes)

    def test_confirmar_en_el_maximo_sigue_funcionando(self):
        estado = self.repositorio.obtener_nota("NOTA-00099")
        estado.intento = MAX_CORRECCIONES
        self.repositorio.guardar_estado(estado)
        self.coordinador._procesar_respuesta(
            respuesta(self.borrador.id, "Sí, así es. Confirmo.")
        )
        self.assertEqual(self.repositorio.obtener_nota("NOTA-00099").estado, "CONFIRMADO")


if __name__ == "__main__":
    unittest.main()
