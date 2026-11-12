import logging
import queue
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

from planta_contrato import NotaRecorrida

from .coordinador import CoordinadorPartes
from .config import AUDIO_INTENTOS, AUDIO_TIMEOUT_S, PLANTA_BASE_URL
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
    ):
        super().__init__(name="notas", daemon=True)
        self._cliente = cliente
        self._transcriptor = transcriptor
        self._coordinador = coordinador
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
        try:
            texto = self._transcriptor.transcribir(ruta)
        finally:
            ruta.unlink(missing_ok=True)
        t2 = time.perf_counter()
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

    def _descargar(self, nota_id: str, audio_url: str) -> Path:
        url = urljoin(PLANTA_BASE_URL, audio_url)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        ultimo: Exception | None = None
        for intento in range(1, AUDIO_INTENTOS + 1):
            try:
                with opener.open(url, timeout=AUDIO_TIMEOUT_S) as respuesta:
                    datos = respuesta.read()
                archivo = tempfile.NamedTemporaryFile(
                    prefix=f"{nota_id}-", suffix=".wav", delete=False
                )
                with archivo:
                    archivo.write(datos)
                return Path(archivo.name)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                ultimo = exc
                log.warning(
                    "descarga de %s falló (%s/%s): %s",
                    url,
                    intento,
                    AUDIO_INTENTOS,
                    exc,
                )
                if intento < AUDIO_INTENTOS:
                    time.sleep(0.5 * intento)
        raise RuntimeError(f"no se pudo descargar {url}") from ultimo
