"""Cruza órdenes históricas con las causas probables del evento actual.

Reglas deterministas, sin LLM. El historial es dato: nunca se interpreta como
instrucción. Los identificadores de orden solo viajan en ``Causa.antecedentes``
o en ``AntecedenteOrden.orden_id``; no se codifican reglas por id.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

from .causas import (
    BOMBAS,
    FILTROS,
    TANQUE,
    Causa,
    EvidenciaEquipo,
    _citas,
    _primer_filtro,
)
from .parte import normalizar

VENTANA_HISTORIAL_DIAS = 400
VENTANA_ACOPLE_DIAS = 90
VENTANA_VALVULAS_DIAS = 14
VENTANA_RETEN_MIN_DIAS = 21
VENTANA_RETEN_MAX_DIAS = 45
ESTADOS_EJECUTADAS = frozenset({"cerrada", "certificada", "ejecutada"})

# Tabla propia del historial. No sale de FALLAS ni de reglas.py.
TABLA_HISTORIAL = {
    "H-EMB": dict(
        descripcion="H-EMB Émbolo rayado por repetición de empaquetadura",
        tarea=None,
        accion="inspeccion",
        ejecutor="propio",
    ),
    "H-RET": dict(
        descripcion="H-RET Retén del piñón con consumo de aceite repetido",
        tarea=None,
        accion="inspeccion",
        ejecutor="propio",
    ),
}


@dataclass(frozen=True)
class AntecedenteOrden:
    orden_id: str
    fecha: datetime
    equipo: str
    tareas: tuple[str, ...]
    estado: str
    ejecutor: str
    texto: str
    repuestos: tuple[str, ...] = ()


@dataclass(frozen=True)
class Repeticion:
    clave: str
    antecedentes: tuple[AntecedenteOrden, ...]
    resuelto: bool = False
    equipo_raiz: str | None = None


def _fecha_cruda(valor: Any) -> datetime | None:
    if isinstance(valor, datetime):
        return valor
    if not isinstance(valor, str) or not valor:
        return None
    try:
        return datetime.fromisoformat(valor)
    except ValueError:
        return None


def _texto_crudo(raw: dict[str, Any]) -> str:
    campos = ("aviso", "trabajo_realizado", "descripcion", "observacion", "detalle")
    return " ".join(str(raw.get(campo) or "") for campo in campos)


def _repuestos_crudos(raw: dict[str, Any]) -> tuple[str, ...]:
    repuestos = raw.get("repuestos")
    if not isinstance(repuestos, list):
        return ()
    codigos = []
    for repuesto in repuestos:
        if isinstance(repuesto, dict) and isinstance(repuesto.get("codigo"), str):
            codigos.append(repuesto["codigo"])
        elif isinstance(repuesto, str):
            codigos.append(repuesto)
    return tuple(codigos)


def _a_antecedente(raw: Any, equipo_default: str | None = None) -> AntecedenteOrden | None:
    if isinstance(raw, AntecedenteOrden):
        return raw
    if not isinstance(raw, dict):
        raise TypeError(f"antecedente inválido: {type(raw).__name__}")
    estado = str(raw.get("estado") or "").strip().lower()
    if estado not in ESTADOS_EJECUTADAS:
        return None
    fecha = _fecha_cruda(raw.get("fecha") or raw.get("fecha_aviso"))
    if fecha is None:
        return None
    equipo = raw.get("equipo") or equipo_default
    if not isinstance(equipo, str) or not equipo:
        return None
    tareas = raw.get("tareas")
    if not isinstance(tareas, list):
        tarea = raw.get("tarea")
        tareas = [tarea] if isinstance(tarea, str) else []
    return AntecedenteOrden(
        orden_id=str(raw.get("id") or raw.get("orden_id") or ""),
        fecha=fecha,
        equipo=equipo,
        tareas=tuple(str(tarea) for tarea in tareas),
        estado=estado,
        ejecutor=str(raw.get("ejecutor") or ""),
        texto=normalizar(_texto_crudo(raw)),
        repuestos=_repuestos_crudos(raw),
    )


def _antecedentes(historial: Sequence[Any]) -> tuple[AntecedenteOrden, ...]:
    vistos: dict[str, AntecedenteOrden] = {}
    for indice, raw in enumerate(historial or ()):
        antecedente = _a_antecedente(raw)
        if antecedente is None:
            continue
        clave = antecedente.orden_id or f"sin-id-{indice}"
        vistos.setdefault(clave, antecedente)
    return tuple(vistos.values())


def _parecido(texto: str, claves: Iterable[str]) -> bool:
    for clave in claves:
        if clave in texto:
            return True
        for token in texto.split():
            if SequenceMatcher(None, clave, token).ratio() >= 0.85:
                return True
    return False


def _ids(repeticion: Repeticion) -> tuple[str, ...]:
    return tuple(
        antecedente.orden_id
        for antecedente in sorted(repeticion.antecedentes, key=lambda a: a.fecha)
        if antecedente.orden_id
    )


def _repeticion_acople(
    antecedentes: Sequence[AntecedenteOrden], equipo: str, hasta: datetime
) -> Repeticion | None:
    valvulas = [
        antecedente
        for antecedente in antecedentes
        if antecedente.equipo == equipo
        and "T-B-VAL" in antecedente.tareas
        and timedelta(0) <= hasta - antecedente.fecha <= timedelta(days=VENTANA_ACOPLE_DIAS)
    ]
    if not valvulas:
        return None
    confirmaciones = [
        antecedente
        for antecedente in antecedentes
        if antecedente.equipo == equipo
        and _parecido(antecedente.texto, ("acople", "desalinea", "alinea"))
    ]
    referencia = max(antecedente.fecha for antecedente in (*valvulas, *confirmaciones))
    resuelto = any(
        antecedente.equipo == equipo
        and "T-B-ALI" in antecedente.tareas
        and antecedente.fecha > referencia
        for antecedente in antecedentes
    )
    unicos = {a.orden_id: a for a in (*valvulas, *confirmaciones)}
    return Repeticion("acople", tuple(unicos.values()), resuelto, equipo)


def _repeticion_embolo(
    antecedentes: Sequence[AntecedenteOrden], equipo: str
) -> Repeticion | None:
    senales = [
        antecedente
        for antecedente in antecedentes
        if antecedente.equipo == equipo
        and "T-B-EMP" in antecedente.tareas
        and _parecido(
            antecedente.texto,
            ("embolo", "emoblo", "ebolo", "raya", "otra vez", "3ra vez", "tx-emb-57c"),
        )
    ]
    if not senales:
        return None
    ultima = max(senales, key=lambda a: a.fecha)
    resuelto = any(
        antecedente.equipo == equipo
        and antecedente.fecha > ultima.fecha
        and ("T-B-EMP" in antecedente.tareas or "NO-ESTANDAR" in antecedente.tareas)
        and _parecido(antecedente.texto, ("se cambio embolo", "cambio de embolo", "embolo nuevo"))
        for antecedente in antecedentes
    )
    return Repeticion("embolo", tuple(senales), resuelto, equipo)


def _repeticion_reten(
    antecedentes: Sequence[AntecedenteOrden], equipo: str
) -> Repeticion | None:
    aceites = [
        antecedente
        for antecedente in antecedentes
        if antecedente.equipo == equipo and "T-B-ACE" in antecedente.tareas
    ]
    senales: list[AntecedenteOrden] = []
    for i, primero in enumerate(aceites):
        for segundo in aceites[i + 1 :]:
            dias = (segundo.fecha - primero.fecha).days
            if not (VENTANA_RETEN_MIN_DIAS <= dias <= VENTANA_RETEN_MAX_DIAS):
                continue
            if _parecido(primero.texto, ("reten", "mancha", "piso", "otra vez")) or _parecido(
                segundo.texto, ("reten", "mancha", "piso", "otra vez")
            ):
                senales.extend([primero, segundo])
    if not senales:
        return None
    unicos = {a.orden_id: a for a in senales}
    ultima = max(unicos.values(), key=lambda a: a.fecha)
    resuelto = any(
        antecedente.equipo == equipo
        and antecedente.fecha > ultima.fecha
        and ("NO-ESTANDAR" in antecedente.tareas or "T-B-ACE" in antecedente.tareas)
        and _parecido(antecedente.texto, ("cambio de reten", "se cambio reten", "reten del eje"))
        for antecedente in antecedentes
    )
    return Repeticion("reten", tuple(unicos.values()), resuelto, equipo)


def _repeticion_filtro(
    antecedentes: Sequence[AntecedenteOrden],
    equipo: str,
    clave: str,
    claves_texto: tuple[str, ...],
) -> Repeticion | None:
    senales = [
        antecedente
        for antecedente in antecedentes
        if antecedente.equipo == equipo
        and "T-F-CAR" in antecedente.tareas
        and _parecido(antecedente.texto, claves_texto)
    ]
    if not senales:
        return None
    ultima = max(senales, key=lambda a: a.fecha)
    resuelto = any(
        antecedente.equipo == equipo
        and "T-F-CAR" in antecedente.tareas
        and antecedente.fecha > ultima.fecha
        and _parecido(antecedente.texto, claves_texto)
        for antecedente in antecedentes
    )
    return Repeticion(clave, tuple(senales), resuelto, equipo)


def _repeticion_valvulas_dos_bombas(
    antecedentes: Sequence[AntecedenteOrden],
) -> Repeticion | None:
    valvulas = sorted(
        (
            antecedente
            for antecedente in antecedentes
            if antecedente.equipo in BOMBAS and "T-B-VAL" in antecedente.tareas
        ),
        key=lambda a: a.fecha,
    )
    clusters: list[tuple[AntecedenteOrden, ...]] = []
    for i in range(len(valvulas)):
        j = i
        while (
            j + 1 < len(valvulas)
            and (valvulas[j + 1].fecha - valvulas[i].fecha).days
            <= VENTANA_VALVULAS_DIAS
        ):
            j += 1
        grupo = valvulas[i : j + 1]
        if len({a.equipo for a in grupo}) >= 2:
            clusters.append(tuple(grupo))
    if not clusters:
        return None
    ultimo = max(clusters, key=lambda grupo: max(a.fecha for a in grupo))
    fin = max(a.fecha for a in ultimo)
    resuelto = any(
        antecedente.equipo in FILTROS
        and "T-F-CAR" in antecedente.tareas
        and antecedente.fecha > fin
        for antecedente in antecedentes
    )
    return Repeticion("valvulas-dos-bombas", ultimo, resuelto, None)


def detectar_repeticiones(
    historial: Sequence[Any],
    equipo: str,
    hasta: datetime | None = None,
) -> tuple[Repeticion, ...]:
    """Detecta patrones repetidos para ``equipo`` dentro de la ventana temporal."""
    antecedentes = _antecedentes(historial)
    if not antecedentes:
        return ()
    referencia = hasta or max(a.fecha for a in antecedentes)
    repeticiones: list[Repeticion] = []
    if equipo in BOMBAS:
        for repeticion in (
            _repeticion_acople(antecedentes, equipo, referencia),
            _repeticion_embolo(antecedentes, equipo),
            _repeticion_reten(antecedentes, equipo),
        ):
            if repeticion is not None:
                repeticiones.append(repeticion)
    filtros = FILTROS if equipo in BOMBAS else (equipo,) if equipo in FILTROS else ()
    for filtro in filtros:
        roto = _repeticion_filtro(
            antecedentes,
            filtro,
            "cartucho-roto",
            ("partido", "roto", "mal trabado", "salido del asiento", "0,09", "0,11"),
        )
        if roto is not None:
            repeticiones.append(roto)
        cavitacion = _repeticion_filtro(
            antecedentes,
            filtro,
            "cavitacion",
            ("cavita", "piedras", "succion"),
        )
        if cavitacion is not None:
            repeticiones.append(cavitacion)
    cluster = _repeticion_valvulas_dos_bombas(antecedentes)
    if cluster is not None:
        repeticiones.append(cluster)
    return tuple(repeticiones)


def _filtro_de_evidencia(evidencia: EvidenciaEquipo) -> str | None:
    return (
        _primer_filtro(evidencia, "baja")
        or _primer_filtro(evidencia, "alta")
        or next(
            (
                anomalia.tag
                for anomalia in evidencia.anomalias
                if anomalia.tag in FILTROS and anomalia.variable == "presion_diferencial"
            ),
            None,
        )
    )


def _menciona_codigo(texto: str, codigos: Iterable[str]) -> bool:
    tokens = set(texto.split())
    return any(codigo in tokens for codigo in codigos)


def _filtro_por_texto(repeticion: Repeticion) -> str | None:
    texto = " ".join(antecedente.texto for antecedente in repeticion.antecedentes)
    menciona_fa = _menciona_codigo(texto, ("fa", "f-201a", "primario"))
    menciona_fb = _menciona_codigo(texto, ("fb", "f-201b"))
    if menciona_fa == menciona_fb:
        return None
    return "F-201A" if menciona_fa else "F-201B"


def _causa_nueva(
    codigo: str,
    descripcion: str,
    repeticion: Repeticion,
    equipo_orden: str,
    *,
    tarea_codigo: str | None,
    citas: tuple[str, ...],
    accion: str,
    ejecutor: str,
    genera_orden: bool = True,
) -> Causa:
    return Causa(
        codigo_falla=codigo,
        descripcion=descripcion,
        evidencia=("historial_repetido",),
        faltantes=(),
        tarea_codigo=tarea_codigo,
        equipo_orden=equipo_orden,
        citas=citas,
        accion=accion,
        genera_orden=genera_orden,
        ejecutor=ejecutor,
        antecedentes=_ids(repeticion),
    )


def _con_antecedentes(causa: Causa, repeticion: Repeticion) -> Causa:
    return replace(causa, antecedentes=_ids(repeticion))


def _priorizar(resultado: list[Causa], codigos: Sequence[str]) -> list[Causa]:
    buscados = list(codigos)
    adelante = [causa for causa in resultado if causa.codigo_falla in buscados]
    resto = [causa for causa in resultado if causa.codigo_falla not in buscados]
    return adelante + resto


def _insertar_o_actualizar(
    resultado: list[Causa], nueva: Causa, repeticion: Repeticion
) -> list[Causa]:
    for i, causa in enumerate(resultado):
        if causa.codigo_falla == nueva.codigo_falla:
            resultado[i] = _con_antecedentes(causa, repeticion)
            return _priorizar(resultado, (nueva.codigo_falla,))
    return [nueva, *resultado]


def _aplicar_acople(
    resultado: list[Causa], repeticion: Repeticion, evidencia: EvidenciaEquipo
) -> list[Causa]:
    confirmado = any(
        _parecido(antecedente.texto, ("acople", "desalinea", "alinea"))
        for antecedente in repeticion.antecedentes
    )
    citas = _citas("F06")
    if not confirmado:
        actualizado = [
            replace(
                causa,
                accion="I-VIB",
                tarea_codigo="I-VIB",
                ejecutor="contratista",
                antecedentes=_ids(repeticion),
            )
            if causa.codigo_falla == "F06"
            else causa
            for causa in resultado
        ]
        if any(causa.codigo_falla == "F06" for causa in actualizado):
            return _priorizar(actualizado, ("F06",))
        return [
            _causa_nueva(
                "F06",
                "F06 Acople desalineado / elastómero gastado",
                repeticion,
                evidencia.equipo,
                tarea_codigo="I-VIB",
                citas=citas,
                accion="I-VIB",
                ejecutor="contratista",
            ),
            *resultado,
        ]
    for i, causa in enumerate(resultado):
        if causa.codigo_falla == "F06":
            resultado[i] = replace(
                causa,
                accion="orden",
                tarea_codigo="T-B-ALI",
                ejecutor="contratista (Servipat)",
                antecedentes=_ids(repeticion),
            )
            return _priorizar(resultado, ("F06",))
    return [
        _causa_nueva(
            "F06",
            "F06 Acople desalineado / elastómero gastado",
            repeticion,
            evidencia.equipo,
            tarea_codigo="T-B-ALI",
            citas=citas,
            accion="orden" if citas else "inspeccion",
            ejecutor="contratista (Servipat)",
        ),
        *resultado,
    ]


def _aplicar_filtro(
    resultado: list[Causa],
    repeticion: Repeticion,
    evidencia: EvidenciaEquipo,
    codigo: str,
) -> list[Causa]:
    if codigo == "F09":
        raiz = (
            _filtro_de_evidencia(evidencia)
            or _filtro_por_texto(repeticion)
            or (repeticion.equipo_raiz if repeticion.equipo_raiz in FILTROS else TANQUE)
        )
        tarea = "T-F-CAR" if raiz in FILTROS else None
    else:
        raiz = (
            _filtro_de_evidencia(evidencia)
            or _filtro_por_texto(repeticion)
            or (repeticion.equipo_raiz if repeticion.equipo_raiz in FILTROS else FILTROS[0])
        )
        tarea = "T-F-CAR"
    citas = _citas(codigo)
    for i, causa in enumerate(resultado):
        if causa.codigo_falla == codigo:
            resultado[i] = replace(
                _con_antecedentes(causa, repeticion),
                equipo_orden=raiz,
                tarea_codigo=tarea if citas else None,
                accion="orden" if citas else "inspeccion",
            )
            return _priorizar(resultado, (codigo,))
    return [
        _causa_nueva(
            codigo,
            f"{codigo} {repeticion.clave.replace('-', ' ')}",
            repeticion,
            raiz,
            tarea_codigo=tarea if citas else None,
            citas=citas,
            accion="orden" if citas else "inspeccion",
            ejecutor="propio",
        ),
        *resultado,
    ]


def _sin_tarea_en_bomba(resultado: list[Causa], evidencia: EvidenciaEquipo) -> list[Causa]:
    arreglado: list[Causa] = []
    for causa in resultado:
        if causa.codigo_falla == "F09" and (
            causa.equipo_orden in BOMBAS
            or causa.tarea_codigo in {"T-B-EMP", "T-B-VAL", "T-B-ACE", "T-B-COR", "T-B-ALI", "T-B-ROD"}
        ):
            raiz = _filtro_de_evidencia(evidencia) or (
                causa.equipo_orden if causa.equipo_orden in FILTROS else TANQUE
            )
            causa = replace(
                causa,
                equipo_orden=raiz,
                tarea_codigo="T-F-CAR" if causa.accion == "orden" and raiz in FILTROS else None,
                accion="orden" if causa.accion == "orden" and raiz in FILTROS else "inspeccion",
            )
        arreglado.append(causa)
    return arreglado


def reordenar_con_historial(
    causas: Sequence[Causa],
    historial: Sequence[Any],
    evidencia: EvidenciaEquipo,
) -> list[Causa]:
    """Reordena e inserta causas a partir del historial de órdenes.

    Ante historial vacío, inválido o sin antecedentes dentro de la ventana,
    devuelve exactamente las mismas causas. Nunca falla por datos del historial.
    """
    base = list(causas)
    try:
        antecedentes = _antecedentes(historial)
    except Exception:
        return base
    if not antecedentes:
        return base
    desde = evidencia.hasta - timedelta(days=VENTANA_HISTORIAL_DIAS)
    antecedentes = tuple(
        antecedente
        for antecedente in antecedentes
        if desde <= antecedente.fecha <= evidencia.hasta
    )
    if not antecedentes:
        return base
    try:
        repeticiones = detectar_repeticiones(
            antecedentes, evidencia.equipo, hasta=evidencia.hasta
        )
    except Exception:
        return base

    resultado = base
    for repeticion in repeticiones:
        if repeticion.resuelto:
            continue
        if repeticion.clave == "acople":
            resultado = _aplicar_acople(resultado, repeticion, evidencia)
        elif repeticion.clave == "embolo":
            tabla = TABLA_HISTORIAL["H-EMB"]
            resultado = _insertar_o_actualizar(
                resultado,
                _causa_nueva(
                    "H-EMB",
                    tabla["descripcion"],
                    repeticion,
                    evidencia.equipo,
                    tarea_codigo=tabla["tarea"],
                    citas=(),
                    accion=tabla["accion"],
                    ejecutor=tabla["ejecutor"],
                ),
                repeticion,
            )
        elif repeticion.clave == "reten":
            tabla = TABLA_HISTORIAL["H-RET"]
            resultado = _insertar_o_actualizar(
                resultado,
                _causa_nueva(
                    "H-RET",
                    tabla["descripcion"],
                    repeticion,
                    evidencia.equipo,
                    tarea_codigo=tabla["tarea"],
                    citas=(),
                    accion=tabla["accion"],
                    ejecutor=tabla["ejecutor"],
                ),
                repeticion,
            )
        elif repeticion.clave in ("cartucho-roto", "valvulas-dos-bombas"):
            resultado = _aplicar_filtro(resultado, repeticion, evidencia, "F08")
        elif repeticion.clave == "cavitacion":
            resultado = _aplicar_filtro(resultado, repeticion, evidencia, "F09")
    return _sin_tarea_en_bomba(resultado, evidencia)
