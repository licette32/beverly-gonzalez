from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from planta_contrato import EstadoOrden, NotaCierre, OrdenSistema, Topicos

from . import audio
from .config import TRANSCRIPCION_LIMITE_S
from .ordenes import RepositorioOrdenes
from .parte_cierre import (
    DiferenciaCierre,
    ParteCierre,
    comparar_cierre,
    extraer_parte_cierre,
)
from .transiciones import Accion, ErrorTransicion, transicionar

log = logging.getLogger(__name__)

PROMPT_CIERRE = (
    "Orden, cierre, hice, realice, cambio, cambio de cartuchos, "
    "cambio de empaquetadura, cambio de valvulas, cambio de correas, "
    "alineacion laser, analisis de vibraciones, cartucho filtrante 25 um, "
    "cartucho filtrante 10 um, juego de rodamientos, juego de sellos, "
    "elastomero de acople, kit de empaquetadura, aceite, horas, horas hombre, "
    "cuarenta y ocho, probe, kilos, psi, bar, presion, diferencial normal, "
    "sin perdida, con perdida, en servicio."
)
REINTENTOS_TRANSCRIPCION = 3


def aplicar_cierre(
    nota: NotaCierre,
    repositorio: RepositorioOrdenes,
    publicador: Callable[[str, BaseModel], None],
    *,
    republicar_si_ejecutada: bool = False,
) -> OrdenSistema | None:
    orden = repositorio.obtener(nota.orden_id)
    if orden is None:
        log.error(
            "anomalía en cierre %s: orden %s no encontrada",
            nota.id,
            nota.orden_id,
        )
        return None

    if orden.estado is EstadoOrden.ejecutada:
        log.info("cierre idempotente %s: orden %s ya ejecutada", nota.id, orden.id)
        if republicar_si_ejecutada:
            publicador(Topicos.ORDENES, orden)
        return None

    try:
        ejecutada = transicionar(orden, Accion.registrar_cierre, nota=nota)
    except ErrorTransicion as exc:
        log.error("anomalía en cierre %s: %s", nota.id, exc)
        return None

    repositorio.guardar(ejecutada)
    publicador(Topicos.ORDENES, ejecutada)
    log.info(
        "cierre %s aplicado: orden %s pasó a %s",
        nota.id,
        orden.id,
        ejecutada.estado.value,
    )
    return ejecutada


class ManejadorCierres:
    def __init__(
        self,
        repositorio: RepositorioOrdenes,
        publicador: Callable[[str, BaseModel], None],
        repositorio_cierres: Any = None,
        encolar: Callable[[NotaCierre], None] | None = None,
    ) -> None:
        self._repositorio = repositorio
        self._publicador = publicador
        self._cierres = repositorio_cierres
        self._encolar = encolar

    def __call__(self, nota: NotaCierre) -> OrdenSistema | None:
        if self._cierres is not None:
            try:
                self._cierres.guardar_recibido(nota)
            except Exception:
                log.exception("no se pudo guardar el cierre %s al recibirlo", nota.id)

        ejecutada = aplicar_cierre(nota, self._repositorio, self._publicador)
        if ejecutada is not None and self._encolar is not None:
            self._encolar(nota)
        return ejecutada


class WorkerCierres(threading.Thread):
    def __init__(
        self,
        repositorio_cierres: Any,
        repositorio_ordenes: Any,
        transcriptor: Any,
        *,
        publicador: Callable[[str, BaseModel], None] | None = None,
        limite_transcripcion_s: float = TRANSCRIPCION_LIMITE_S,
        reintentos_transcripcion: int = REINTENTOS_TRANSCRIPCION,
        descargar: Callable[[str, str], Path] | None = None,
    ) -> None:
        super().__init__(name="cierres", daemon=True)
        self._cierres = repositorio_cierres
        self._ordenes = repositorio_ordenes
        self._transcriptor = transcriptor
        self._publicador = publicador
        self._limite_transcripcion_s = limite_transcripcion_s
        self._reintentos = reintentos_transcripcion
        self._descargar = descargar if descargar is not None else audio.descargar_audio
        self._transcripcion = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="transcribir-cierre"
        )
        self._cola: queue.Queue[NotaCierre | None] = queue.Queue()

    def encolar(self, nota: NotaCierre) -> None:
        self._cola.put_nowait(nota)

    def detener(self) -> None:
        self._transcripcion.shutdown(wait=False, cancel_futures=True)
        self._cola.put_nowait(None)

    def reencolar_recibidos(self) -> int:
        try:
            filas = list(self._cierres.cargar_recibidos())
        except Exception:
            log.exception("no se pudieron cargar los cierres recibidos")
            return 0
        for fila in filas:
            if self._publicador is None:
                log.warning(
                    "sin publicador: no se puede reanudar la transición del cierre %s",
                    fila.nota.id,
                )
                continue
            try:
                aplicar_cierre(
                    fila.nota,
                    self._ordenes,
                    self._publicador,
                    republicar_si_ejecutada=True,
                )
            except Exception:
                log.exception(
                    "no se pudo reaplicar el cierre %s al reanudar", fila.nota.id
                )
                continue
            self.encolar(fila.nota)
        return len(filas)

    def start(self) -> None:
        self.reencolar_recibidos()
        super().start()

    def run(self) -> None:
        while True:
            nota = self._cola.get()
            try:
                if nota is None:
                    return
                self._procesar(nota)
            except Exception:
                log.exception("falló el procesamiento del cierre")
            finally:
                self._cola.task_done()

    def _error_sin_transcripcion(self, nota: NotaCierre) -> None:
        parte = ParteCierre()
        diferencias = [
            DiferenciaCierre(
                tipo="CIERRE_SIN_TRANSCRIPCION",
                valor_pedido="transcripcion",
                valor_declarado=None,
            )
        ]
        try:
            self._cierres.marcar_error(
                nota.id,
                parte.model_dump(mode="json"),
                [diferencia.model_dump(mode="json") for diferencia in diferencias],
            )
        except Exception:
            log.exception("no se pudo registrar el error del cierre %s", nota.id)

    def _procesar(self, nota: NotaCierre) -> None:
        ruta: Path | None = None
        try:
            if nota.audio_url is None:
                raise RuntimeError(f"cierre {nota.id} sin audio_url")
            ruta = self._descargar(nota.id, nota.audio_url)
            texto: str | None = None
            for _ in range(self._reintentos):
                texto = audio.transcribir_con_limite(
                    self._transcripcion,
                    self._transcriptor,
                    ruta,
                    self._limite_transcripcion_s,
                    nota_id=nota.id,
                    prompt=PROMPT_CIERRE,
                    cronometrar_desde_lock=True,
                    conservar_archivo=True,
                )
                if texto is not None:
                    break
            if texto is None:
                raise RuntimeError(
                    f"no se pudo transcribir el cierre {nota.id} tras "
                    f"{self._reintentos} intentos"
                )
            parte = extraer_parte_cierre(texto)
            orden = self._ordenes.obtener(nota.orden_id)
            if orden is None:
                raise RuntimeError(f"orden {nota.orden_id} no encontrada")
            diferencias = comparar_cierre(parte, orden)
            self._cierres.marcar_procesado(
                nota.id,
                parte.model_dump(mode="json"),
                [diferencia.model_dump(mode="json") for diferencia in diferencias],
            )
            log.info(
                "cierre %s procesado: orden=%s diferencias=%d",
                nota.id,
                nota.orden_id,
                len(diferencias),
            )
        except Exception:
            log.exception("no se pudo procesar el cierre %s", nota.id)
            self._error_sin_transcripcion(nota)
        finally:
            if ruta is not None:
                try:
                    ruta.unlink(missing_ok=True)
                except OSError:
                    pass
