from __future__ import annotations

import threading
from collections import deque
from datetime import datetime
from typing import Iterable, Literal

from .causas import (
    Anomalia,
    CAUDALIMETRO,
    EQUIPOS_RELACIONADOS,
    TANQUE,
    lado_desde_limite,
)
from .parte import A_KG, LIMITES, VARIABLES_CON_LIMITE, ItemParte, fuera_de_limite

EQUIPOS_EVIDENCIA = frozenset(
    {*EQUIPOS_RELACIONADOS, CAUDALIMETRO, TANQUE}
)


def equipos_relacionados(equipo: str | None = None) -> frozenset[str]:
    if equipo is None:
        return EQUIPOS_EVIDENCIA
    return EQUIPOS_EVIDENCIA | {equipo}


def anomalia_desde_item(item: ItemParte, ts: datetime) -> Anomalia | None:
    if not fuera_de_limite(item) or item.tag is None or item.valor is None:
        return None
    variable = VARIABLES_CON_LIMITE.get(item.variable)
    if variable is None:
        return None
    limites = LIMITES.get((item.tag, variable))
    if not limites:
        return None
    valor = item.valor * A_KG.get(item.unidad or "kg/cm2", 1.0)
    alta = limites.get("alarma_alta")
    baja = limites.get("alarma_baja")
    if alta is not None and valor >= alta:
        lado: Literal["alta", "baja"] = "alta"
    elif baja is not None and valor <= baja:
        lado = "baja"
    else:
        return None
    return Anomalia(item.tag, variable, ts, lado)


def anomalia_desde_resultado(resultado, ts: datetime | None = None) -> Anomalia | None:
    ultima = resultado.ultima_lectura
    if ultima is None:
        return None
    lado = lado_desde_limite(resultado.limite_violado)
    if lado is None:
        return None
    return Anomalia(resultado.tag, resultado.variable, ts or ultima.ts, lado)


class AlmacenAnomalias:
    def __init__(self, maximo: int = 200) -> None:
        self._anomalias: deque[Anomalia] = deque(maxlen=maximo)
        self._vistas: set[Anomalia] = set()
        self._lock = threading.Lock()

    def registrar(self, anomalia: Anomalia | None) -> bool:
        if anomalia is None:
            return False
        with self._lock:
            if anomalia in self._vistas:
                return False
            self._vistas.add(anomalia)
            self._anomalias.append(anomalia)
            return True

    def recientes(
        self,
        desde: datetime,
        hasta: datetime,
        equipos: Iterable[str] | None = None,
    ) -> tuple[Anomalia, ...]:
        objetivos = frozenset(equipos) if equipos is not None else EQUIPOS_EVIDENCIA
        with self._lock:
            return tuple(
                anomalia
                for anomalia in self._anomalias
                if anomalia.tag in objetivos and desde <= anomalia.ts <= hasta
            )

    def limpiar(self) -> None:
        with self._lock:
            self._anomalias.clear()
            self._vistas.clear()
