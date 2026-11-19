from __future__ import annotations

import logging
import queue
import threading
import uuid
from datetime import datetime, timedelta
from typing import Mapping, Sequence

from planta_contrato import (
    Calidad,
    EventoSistema,
    LecturaSensor,
    TipoEvento,
    Topicos,
)

from .anomalias import ParametrosDeteccion, Resultado, detectar_anomalia
from .catalogo import EstadoPlanta
from .sensores import VentanaSensores

log = logging.getLogger(__name__)


def _id(tag: str, variable: str, inicio: datetime) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"pia3:sensor:{tag}:{variable}:{inicio.isoformat()}",
        )
    )


def _fuera(lectura: LecturaSensor, limites: Mapping[str, float]) -> bool:
    if lectura.valor is None:
        return False
    alta = limites.get("alarma_alta")
    baja = limites.get("alarma_baja")
    return (alta is not None and lectura.valor >= alta) or (
        baja is not None and lectura.valor <= baja
    )


def _ultima_valida(lecturas: Sequence[LecturaSensor]) -> LecturaSensor | None:
    for lectura in reversed(lecturas):
        if lectura.valor is not None and lectura.calidad == Calidad.buena:
            return lectura
    return None


def _evaluadas(
    lecturas: Sequence[LecturaSensor], ultima_ts: datetime, ventana_min: float
) -> list[LecturaSensor]:
    por_ts = {lectura.ts: lectura for lectura in lecturas}
    desde = ultima_ts - timedelta(minutes=ventana_min)
    return [
        por_ts[ts]
        for ts in sorted(por_ts)
        if desde <= ts <= ultima_ts
        and por_ts[ts].valor is not None
        and por_ts[ts].calidad == Calidad.buena
    ]


def _inicio_episodio(
    evaluadas: Sequence[LecturaSensor], limites: Mapping[str, float]
) -> datetime | None:
    ultimo_dentro = None
    for lectura in evaluadas:
        if not _fuera(lectura, limites):
            ultimo_dentro = lectura.ts
    fuera = [lectura for lectura in evaluadas if _fuera(lectura, limites)]
    if ultimo_dentro is not None:
        fuera = [lectura for lectura in fuera if lectura.ts > ultimo_dentro]
    return fuera[0].ts if fuera else None


def _numero(valor: float) -> str:
    return f"{valor:g}"


def evento_desvio(
    resultado: Resultado,
    evaluadas: Sequence[LecturaSensor],
    inicio: datetime,
) -> EventoSistema:
    ultima = resultado.ultima_lectura
    if ultima is None or resultado.limite_violado is None:
        raise ValueError("el resultado no tiene evidencia de desvío")
    valores = [lectura.valor for lectura in evaluadas if lectura.valor is not None]
    if not valores:
        valores = [ultima.valor]
    minimo = _numero(min(valores))
    maximo = _numero(max(valores))
    rango = f"{minimo}–{maximo}"
    if ultima.unidad:
        rango = f"{rango} {ultima.unidad}"
    resumen = (
        f"{resultado.tag} {resultado.variable} fuera de "
        f"{resultado.limite_violado}: {resultado.cantidad_fuera} lecturas entre "
        f"{inicio.isoformat()} y {ultima.ts.isoformat()} "
        f"(valores {rango}, última {_numero(ultima.valor)})"
    )
    return EventoSistema(
        id=_id(resultado.tag, resultado.variable, inicio),
        ts=ultima.ts,
        tipo=TipoEvento.escalado,
        equipo=resultado.tag,
        origen="sensor",
        resumen=resumen,
    )


class DetectorSensores:
    def __init__(
        self,
        ventana: VentanaSensores,
        limites: Mapping[tuple[str, str], Mapping[str, float]],
        parametros: ParametrosDeteccion,
    ) -> None:
        self._ventana = ventana
        self._limites = limites
        self._parametros = parametros
        self._activos: dict[tuple[str, str], EventoSistema] = {}

    def evaluar(
        self,
        tag: str,
        variable: str,
        equipos_excluidos: frozenset[str] = frozenset(),
    ) -> EventoSistema | None:
        clave = (tag, variable)
        lecturas = self._ventana.ventana(tag, variable)
        limites = self._limites.get(clave, {})
        parametros = ParametrosDeteccion(
            self._parametros.ventana_min,
            self._parametros.minimo_fuera,
            self._parametros.span_min,
            frozenset(equipos_excluidos),
        )
        resultado = detectar_anomalia(lecturas, limites, parametros)
        ultima = resultado.ultima_lectura
        if (
            ultima is None
            or not resultado.anomalia
            or not _fuera(ultima, limites)
        ):
            self._activos.pop(clave, None)
            return None
        if clave in self._activos:
            return None
        evaluadas = _evaluadas(
            lecturas, ultima.ts, self._parametros.ventana_min
        )
        inicio = _inicio_episodio(evaluadas, limites)
        if inicio is None:
            return None
        evento = evento_desvio(resultado, evaluadas, inicio)
        self._activos[clave] = evento
        return evento

    def activo(self, tag: str, variable: str) -> EventoSistema | None:
        return self._activos.get((tag, variable))

    def olvidar(self, tag: str, variable: str) -> None:
        self._activos.pop((tag, variable), None)


class WorkerSensores(threading.Thread):
    def __init__(
        self,
        cliente,
        ventana: VentanaSensores,
        limites: Mapping[tuple[str, str], Mapping[str, float]],
        parametros: ParametrosDeteccion,
        estado: EstadoPlanta | None = None,
    ) -> None:
        super().__init__(name="sensores", daemon=True)
        self._cliente = cliente
        self._ventana = ventana
        self._limites = limites
        self._detector = DetectorSensores(ventana, limites, parametros)
        self._estado = estado if estado is not None else EstadoPlanta()
        self._cola: queue.Queue[tuple[str, str] | None] = queue.Queue()
        self._pendientes: set[tuple[str, str]] = set()
        self._lock = threading.Lock()

    def encolar(self, lectura: LecturaSensor) -> None:
        self._ventana.registrar(lectura)
        clave = (lectura.tag, lectura.variable)
        with self._lock:
            if clave in self._pendientes:
                return
            self._pendientes.add(clave)
        self._cola.put_nowait(clave)

    def detener(self) -> None:
        self._cola.put_nowait(None)

    def run(self) -> None:
        while True:
            clave = self._cola.get()
            try:
                if clave is None:
                    return
                with self._lock:
                    self._pendientes.discard(clave)
                self._procesar(clave)
            except Exception:
                log.exception("falló la evaluación de sensores de %s", clave)
            finally:
                self._cola.task_done()

    def _procesar(self, clave: tuple[str, str]) -> None:
        tag, variable = clave
        limites = self._limites.get(clave, {})
        lecturas = self._ventana.ventana(tag, variable)
        ultima = _ultima_valida(lecturas)
        ultimo_estado = self._estado.ultimo()
        excluidos = ultimo_estado if ultimo_estado is not None else frozenset()
        activo = self._detector.activo(tag, variable)
        fuera = ultima is not None and _fuera(ultima, limites)
        refrescar = activo is None and (
            (fuera and tag not in excluidos)
            or (not fuera and tag in excluidos)
        )
        if refrescar:
            nuevos = self._estado.excluidos()
            if nuevos is None:
                return
            excluidos = nuevos
        evento = self._detector.evaluar(tag, variable, excluidos)
        if evento is None:
            return
        try:
            self._cliente.publicar(Topicos.EVENTOS, evento)
        except Exception:
            self._detector.olvidar(tag, variable)
            raise
