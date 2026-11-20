import logging
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from planta_contrato import NotaRecorrida, Topicos

from . import audio
from .coordinador import CoordinadorPartes
from .corte import LIMITE_TRANSCRIPCION_S, mensaje_corte
from .mqtt import ClienteMQTT
from .seguridad import detectar
from .transcripcion import Transcriptor

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrabajoNota:
    nota: NotaRecorrida
    recibido_en: float
    ruta: Path | None = None
    descarga_s: float = 0.0


class WorkerNotas(threading.Thread):
    def __init__(
        self,
        cliente: ClienteMQTT,
        transcriptor: Transcriptor,
        coordinador: CoordinadorPartes,
        limite_transcripcion_s: float = LIMITE_TRANSCRIPCION_S,
    ):
        super().__init__(name="notas", daemon=True)
        self._cliente = cliente
        self._transcriptor = transcriptor
        self._coordinador = coordinador
        self._limite_transcripcion_s = limite_transcripcion_s
        # Un solo hilo estable para transcribir (OpenMP) y poder cortar por tiempo.
        self._transcripcion = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="transcribir"
        )
        self._cola: queue.Queue[TrabajoNota | None] = queue.Queue()
        self._descargas = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="descargas"
        )

    def encolar(self, nota: NotaRecorrida) -> None:
        if nota.audio_url is None:
            log.warning("nota %s sin audio_url", nota.id)
            return
        trabajo = TrabajoNota(nota, time.perf_counter())
        self._descargas.submit(self._descargar_nota, trabajo)

    def detener(self) -> None:
        self._descargas.shutdown(wait=False, cancel_futures=True)
        self._transcripcion.shutdown(wait=False, cancel_futures=True)
        self._cola.put_nowait(None)

    def _descargar_nota(self, trabajo: TrabajoNota) -> None:
        # La descarga arranca apenas llega la nota, fuera de la cola de
        # transcripción, para que no haga esperar a las notas siguientes.
        nota = trabajo.nota
        t0 = time.perf_counter()
        try:
            ruta = self._descargar(nota.id, nota.audio_url)
        except Exception:
            log.exception("no se pudo descargar la nota %s", nota.id)
            self._avisar_corte(nota, "descarga")
            return
        self._cola.put_nowait(
            TrabajoNota(nota, trabajo.recibido_en, ruta, time.perf_counter() - t0)
        )

    def run(self) -> None:
        while True:
            trabajo = self._cola.get()
            try:
                if trabajo is None:
                    return
                self._procesar(trabajo)
            except Exception:
                log.exception("falló el procesamiento de una nota")
            finally:
                self._cola.task_done()

    def _procesar(self, trabajo: TrabajoNota) -> None:
        nota = trabajo.nota
        ruta = trabajo.ruta
        if ruta is None:
            log.warning("nota %s sin audio descargado", nota.id)
            return
        t1 = time.perf_counter()
        texto = self._transcribir_con_limite(nota, ruta)
        if texto is None:
            return
        t2 = time.perf_counter()
        log.info("nota %s texto: %s", nota.id, texto)
        detecciones = detectar(texto)
        t3 = time.perf_counter()
        self._coordinador.procesar_nota(nota, texto, detecciones)
        t4 = time.perf_counter()
        log.info(
            "nota %s descarga=%.2fs transcripcion=%.2fs deteccion=%.3fs "
            "publicacion=%.3fs total=%.2fs categorias=%s",
            nota.id,
            trabajo.descarga_s,
            t2 - t1,
            t3 - t2,
            t4 - t3,
            t4 - trabajo.recibido_en,
            ",".join(deteccion.categoria for deteccion in detecciones) or "ninguna",
        )

    def _avisar_corte(self, nota: NotaRecorrida, motivo: str) -> None:
        try:
            self._cliente.publicar(Topicos.TABLET, mensaje_corte(nota, motivo))
        except Exception:
            log.exception("no se pudo publicar el aviso de corte de %s", nota.id)

    def _transcribir_con_limite(self, nota: NotaRecorrida, ruta: Path) -> str | None:
        """Transcribe con tiempo maximo. Si se agota o falla, avisa a la tablet."""
        return audio.transcribir_con_limite(
            self._transcripcion,
            self._transcriptor,
            ruta,
            self._limite_transcripcion_s,
            nota_id=nota.id,
            avisar=lambda: self._avisar_corte(nota, "transcripcion"),
        )

    def _descargar(self, nota_id: str, audio_url: str) -> Path:
        return audio.descargar_audio(nota_id, audio_url)
