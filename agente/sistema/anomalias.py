"""Detección de desvíos sostenidos por límites de alarma.

Función pura: no accede a la red, no publica eventos y no modifica la ventana.

Usa únicamente los límites de alarma de /api/planta. Un desvío relativo que se
mantiene dentro de los límites no se detecta: en fuga-sin-enlace la presión de
descarga cae de 113,6 a 104,7 kg/cm2, pero el límite bajo es 95, así que la fuga
S1 sale por la nota y no por sensores.

Las lecturas con valor None o calidad distinta de buena se ignoran. La ventana
se mide con el ts de las lecturas, no con el reloj de la máquina. Un valor
exactamente igual a alarma_alta o alarma_baja cuenta como fuera de límite. Un
desvío es sostenido si hay al menos ``minimo_fuera`` lecturas fuera dentro de
``ventana_min`` y esas lecturas abarcan al menos ``span_min``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Mapping, Sequence

from planta_contrato import Calidad, LecturaSensor


@dataclass(frozen=True)
class ParametrosDeteccion:
    ventana_min: float
    minimo_fuera: int
    span_min: float
    equipos_excluidos: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Resultado:
    tag: str
    variable: str
    anomalia: bool
    motivo: str
    cantidad_fuera: int
    ultima_lectura: LecturaSensor | None
    limite_violado: str | None
    lecturas_consideradas: int


def _lados_fuera(
    lectura: LecturaSensor, limites: Mapping[str, float]
) -> set[str]:
    if lectura.valor is None:
        return set()
    lados = set()
    alta = limites.get("alarma_alta")
    baja = limites.get("alarma_baja")
    if alta is not None and lectura.valor >= alta:
        lados.add("alta")
    if baja is not None and lectura.valor <= baja:
        lados.add("baja")
    return lados


def _texto_limite(
    lados: set[str], limites: Mapping[str, float]
) -> str | None:
    partes = []
    if "alta" in lados:
        partes.append(f"alarma_alta={limites['alarma_alta']}")
    if "baja" in lados:
        partes.append(f"alarma_baja={limites['alarma_baja']}")
    return ", ".join(partes) if partes else None


def detectar_anomalia(
    ventana: Sequence[LecturaSensor],
    limites: Mapping[str, float],
    parametros: ParametrosDeteccion,
) -> Resultado:
    """Evalúa un único (tag, variable) y devuelve la evidencia del desvío."""
    tag = ventana[0].tag if ventana else ""
    variable = ventana[0].variable if ventana else ""

    if tag and tag in parametros.equipos_excluidos:
        return Resultado(
            tag=tag,
            variable=variable,
            anomalia=False,
            motivo="equipo_excluido",
            cantidad_fuera=0,
            ultima_lectura=None,
            limite_violado=None,
            lecturas_consideradas=0,
        )

    por_ts = {lectura.ts: lectura for lectura in ventana}
    ordenadas = [por_ts[ts] for ts in sorted(por_ts)]
    validas = [
        lectura
        for lectura in ordenadas
        if lectura.valor is not None and lectura.calidad == Calidad.buena
    ]
    if not validas:
        return Resultado(
            tag=tag,
            variable=variable,
            anomalia=False,
            motivo="sin_datos",
            cantidad_fuera=0,
            ultima_lectura=None,
            limite_violado=None,
            lecturas_consideradas=0,
        )

    ultima = validas[-1]
    if limites.get("alarma_alta") is None and limites.get("alarma_baja") is None:
        return Resultado(
            tag=tag,
            variable=variable,
            anomalia=False,
            motivo="sin_limite",
            cantidad_fuera=0,
            ultima_lectura=ultima,
            limite_violado=None,
            lecturas_consideradas=0,
        )

    desde = ultima.ts - timedelta(minutes=parametros.ventana_min)
    consideradas = [
        lectura for lectura in validas if desde <= lectura.ts <= ultima.ts
    ]
    fuera = [
        lectura for lectura in consideradas if _lados_fuera(lectura, limites)
    ]
    lados = set()
    for lectura in fuera:
        lados.update(_lados_fuera(lectura, limites))

    if not fuera:
        motivo = "sin_desvio"
    elif len(fuera) < parametros.minimo_fuera:
        motivo = "pico_aislado"
    elif (fuera[-1].ts - fuera[0].ts).total_seconds() < parametros.span_min * 60:
        motivo = "span_insuficiente"
    else:
        motivo = "sostenido"

    return Resultado(
        tag=tag,
        variable=variable,
        anomalia=motivo == "sostenido",
        motivo=motivo,
        cantidad_fuera=len(fuera),
        ultima_lectura=ultima,
        limite_violado=_texto_limite(lados, limites),
        lecturas_consideradas=len(consideradas),
    )
