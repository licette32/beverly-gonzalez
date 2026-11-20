from __future__ import annotations

import logging
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturoTimeout
from pathlib import Path
from typing import Any

from .config import AUDIO_INTENTOS, AUDIO_TIMEOUT_S, PLANTA_BASE_URL

log = logging.getLogger(__name__)


def descargar_audio(nota_id: str, audio_url: str) -> Path:
    url = urllib.parse.urljoin(PLANTA_BASE_URL, audio_url)
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


def _transcribir(
    transcriptor: Any,
    ruta: Path,
    prompt: str | None,
    al_adquirir_lock: Callable[[], None] | None,
    conservar_archivo: bool,
) -> str:
    try:
        opciones: dict[str, object] = {}
        if prompt is not None:
            opciones["prompt"] = prompt
        if al_adquirir_lock is not None:
            opciones["al_adquirir_lock"] = al_adquirir_lock
        return transcriptor.transcribir(ruta, **opciones)
    finally:
        if not conservar_archivo:
            ruta.unlink(missing_ok=True)


def transcribir_con_limite(
    executor: ThreadPoolExecutor,
    transcriptor: Any,
    ruta: Path,
    limite_s: float,
    *,
    nota_id: str,
    avisar: Callable[[], None] | None = None,
    prompt: str | None = None,
    al_adquirir_lock: Callable[[], None] | None = None,
    cronometrar_desde_lock: bool = False,
    conservar_archivo: bool = False,
) -> str | None:
    """Transcribe con límite de tiempo; el texto se limpia siempre."""
    futuro: Future[str]
    if cronometrar_desde_lock:
        tomado = threading.Event()

        def al_tomar() -> None:
            tomado.set()
            if al_adquirir_lock is not None:
                al_adquirir_lock()

        futuro = executor.submit(
            _transcribir, transcriptor, ruta, prompt, al_tomar, conservar_archivo
        )
        tomado.wait()
    else:
        futuro = executor.submit(
            _transcribir,
            transcriptor,
            ruta,
            prompt,
            al_adquirir_lock,
            conservar_archivo,
        )
    try:
        return futuro.result(timeout=limite_s)
    except FuturoTimeout:
        if futuro.cancel() and not conservar_archivo:
            ruta.unlink(missing_ok=True)
        log.error(
            "nota %s: la transcripción superó el límite de %.0f s; se corta",
            nota_id,
            limite_s,
        )
    except Exception as exc:
        log.error("nota %s: falló la transcripción: %s", nota_id, exc)
    if avisar is not None:
        avisar()
    return None
