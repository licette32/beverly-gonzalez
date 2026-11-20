from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from planta_contrato import EventoSistema, OrdenSistema

from . import tools
from .causas import EvidenciaEquipo
from .catalogo import EstadoPlanta
from .flujo import CatalogoFlujo, CatalogoTools, ResultadoFlujo
from .flujo import procesar as procesar_flujo
from .llm import AnalizadorLLM
from .ordenes import ErrorEstadoEsperado, RepositorioOrdenes, publicar_orden
from .repositorio_decisiones import (
    RegistroDecisiones,
    argumentos_historial_ordenes,
    medir_y_registrar,
    registrar_herramienta,
)
from .repositorio_ordenes import ErrorPersistenciaOrden

log = logging.getLogger(__name__)

ClaveOrden = tuple[str, frozenset[str]]
REINTENTOS_PUBLICAR_ORDEN = 3
ESPERA_PUBLICAR_ORDEN_S = 2


@dataclass(frozen=True)
class TrabajoOrden:
    evento: EventoSistema
    evidencia: EvidenciaEquipo
    fotos_pendientes_de_analisis: bool = False


def _historial_por_equipo(
    equipo: str,
    correlation_id: str,
    registro: RegistroDecisiones | None = None,
) -> Sequence[Any]:
    respuesta = registrar_herramienta(
        registro,
        correlation_id,
        "historial_ordenes",
        argumentos_historial_ordenes(equipo),
        tools.historial_ordenes,
        equipo,
    )
    return list(respuesta.ordenes)


class WorkerOrdenes(threading.Thread):
    def __init__(
        self,
        publicador: Callable[[str, Any], None],
        repositorio: RepositorioOrdenes,
        *,
        catalogo: CatalogoFlujo | None = None,
        estado_bombas: Callable[[], dict[str, str] | None] | None = None,
        historial: Callable[[str], Sequence[Any]] | None = None,
        procesar: Callable[..., ResultadoFlujo] | None = None,
        registro: RegistroDecisiones | None = None,
        analizador: AnalizadorLLM | None = None,
    ) -> None:
        super().__init__(name="ordenes", daemon=True)
        self._publicador = publicador
        self._repositorio = repositorio
        self._catalogo = catalogo if catalogo is not None else CatalogoTools()
        estado = EstadoPlanta()
        self._estado_bombas = (
            estado_bombas if estado_bombas is not None else estado.estado_bombas
        )
        self._historial_fn = historial
        self._procesar = procesar if procesar is not None else procesar_flujo
        self._registro = registro
        self._analizador = analizador
        self._cola: queue.Queue[TrabajoOrden | None] = queue.Queue()
        self._cache: dict[ClaveOrden, str] = {}
        self._lock = threading.Lock()

    def encolar(
        self,
        evento: EventoSistema,
        evidencia: EvidenciaEquipo,
        fotos_pendientes_de_analisis: bool = False,
    ) -> None:
        self._cola.put_nowait(
            TrabajoOrden(evento, evidencia, fotos_pendientes_de_analisis)
        )

    def detener(self) -> None:
        self._cola.put_nowait(None)

    def run(self) -> None:
        while True:
            trabajo = self._cola.get()
            try:
                if trabajo is None:
                    return
                self._procesar_trabajo(trabajo)
            except Exception:
                log.exception("falló la generación de orden")
            finally:
                self._cola.task_done()

    @staticmethod
    def _clave(orden: OrdenSistema) -> ClaveOrden:
        return (orden.equipo, frozenset(orden.tareas))

    def _ya_abierta(self, orden: OrdenSistema) -> bool:
        clave = self._clave(orden)
        try:
            abiertas = list(self._repositorio.ordenes_abiertas(orden.equipo))
        except Exception:
            log.exception("no se pudieron consultar las órdenes abiertas")
            with self._lock:
                return clave in self._cache
        claves = {self._clave(abierta) for abierta in abiertas}
        with self._lock:
            viejas = [
                clave_cache
                for clave_cache in self._cache
                if clave_cache[0] == orden.equipo and clave_cache not in claves
            ]
            for clave_cache in viejas:
                self._cache.pop(clave_cache, None)
            for abierta in abiertas:
                self._cache.setdefault(self._clave(abierta), abierta.id)
            return clave in self._cache

    def _estado_actual(self) -> dict[str, str] | None:
        try:
            return self._estado_bombas()
        except Exception:
            log.exception("no se pudo leer el estado de las bombas")
            return None

    def _historial(self, equipo: str, correlation_id: str) -> Sequence[Any]:
        try:
            if self._historial_fn is not None:
                return self._historial_fn(equipo)
            return _historial_por_equipo(equipo, correlation_id, self._registro)
        except Exception:
            log.warning("no se pudo leer el historial de %s; se sigue sin reordenar", equipo)
            return []

    def _procesar_trabajo(self, trabajo: TrabajoOrden) -> None:
        evento = trabajo.evento
        correlation_id = evento.id
        equipo = evento.equipo or ""
        estado_bombas = self._estado_actual()
        historial = self._historial(equipo, correlation_id)
        opciones: dict[str, Any] = {}
        if self._registro is not None:
            opciones["registro"] = self._registro
        if self._analizador is not None:
            opciones["analizador"] = self._analizador
        resultado = self._procesar(
            evento,
            trabajo.evidencia,
            historial,
            self._catalogo,
            estado_bombas,
            trabajo.fotos_pendientes_de_analisis,
            **opciones,
        )
        log.info("diagnóstico evento=%s equipo=%s historial=%d causas=%s", evento.id, equipo, len(historial), [(c.codigo_falla, c.accion, c.tarea_codigo) for c in resultado.causas])
        if resultado.orden is None:
            log.info(
                "sin orden para el evento %s: %s", evento.id, resultado.problemas
            )
            return
        orden = resultado.orden
        if self._ya_abierta(orden):
            log.info(
                "orden duplicada omitida id=%s equipo=%s tareas=%s",
                orden.id,
                orden.equipo,
                ",".join(orden.tareas),
            )
            return
        publicada = None
        for intento in range(1, REINTENTOS_PUBLICAR_ORDEN + 1):
            try:
                publicada = medir_y_registrar(
                    self._registro,
                    correlation_id,
                    "publicar_orden",
                    publicar_orden,
                    orden,
                    None,
                    self._publicador,
                    repositorio=self._repositorio,
                )
                break
            except ErrorEstadoEsperado as exc:
                log.error("conflicto de estado al publicar orden %s: %s", orden.id, exc)
                return
            except ErrorPersistenciaOrden as exc:
                if intento == REINTENTOS_PUBLICAR_ORDEN:
                    log.error(
                        "no se pudo publicar la orden %s tras %d intentos: %s",
                        orden.id,
                        intento,
                        exc,
                    )
                    return
                log.warning(
                    "falló el intento %d/%d de publicar la orden %s: %s",
                    intento,
                    REINTENTOS_PUBLICAR_ORDEN,
                    orden.id,
                    exc,
                )
                time.sleep(ESPERA_PUBLICAR_ORDEN_S)
        if publicada is not None:
            with self._lock:
                self._cache[self._clave(publicada)] = publicada.id
            log.info(
                "orden publicada id=%s equipo=%s tareas=%s estado=%s",
                publicada.id,
                publicada.equipo,
                ",".join(publicada.tareas),
                publicada.estado.value,
            )
