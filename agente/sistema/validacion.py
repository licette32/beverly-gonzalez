"""Validación previa a la publicación de una orden: citas y repuestos."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from planta_contrato import OrdenSistema

from . import causas, tools


@dataclass(frozen=True)
class Problema:
    codigo: str
    detalle: str


def _partir_cita(cita: str) -> tuple[str, str] | None:
    documento, separador, seccion = cita.partition("§")
    if not separador or not documento.strip() or not seccion.strip():
        return None
    return documento.strip(), seccion.strip()


def _codigos_materiales(
    materiales: Mapping[str, Any] | Sequence[dict[str, Any]], equipo: str
) -> set[str]:
    if isinstance(materiales, Mapping):
        lista = materiales.get("lista_materiales")
        if not isinstance(lista, Mapping):
            return set()
        codigos = lista.get(equipo, ())
    else:
        codigos = materiales
    resultado: set[str] = set()
    for codigo in codigos or ():
        if isinstance(codigo, str):
            resultado.add(codigo)
        elif isinstance(codigo, Mapping) and isinstance(codigo.get("codigo"), str):
            resultado.add(codigo["codigo"])
    return resultado


def _vigencia_conocida(cita: str) -> bool | None:
    try:
        por_id = tools._fragmentos_manuales()
    except Exception:
        return None
    fragmento = por_id.get(cita)
    if fragmento is None:
        return None
    return getattr(fragmento, "vigente", None) is True


def validar_orden_publicable(
    orden: OrdenSistema,
    citas: Sequence[str],
    materiales: Mapping[str, Any] | Sequence[dict[str, Any]],
) -> tuple[Problema, ...]:
    """Devuelve los problemas que impiden publicar ``orden``, o ``()``."""
    problemas: list[Problema] = []
    permitidos = _codigos_materiales(materiales, orden.equipo)

    for cita in citas:
        partes = _partir_cita(cita)
        if partes is None:
            problemas.append(Problema("CITA_INEXISTENTE", cita))
            continue
        documento, seccion = partes
        try:
            existe = causas.verificar_cita(documento, seccion)
        except Exception:
            problemas.append(Problema("CITA_NO_VERIFICABLE", cita))
            continue
        if existe:
            continue
        vigente = _vigencia_conocida(cita)
        codigo = "CITA_VENCIDA" if vigente is False else "CITA_INEXISTENTE"
        problemas.append(Problema(codigo, cita))

    for repuesto in orden.repuestos:
        if repuesto.codigo not in permitidos:
            problemas.append(Problema("REPUESTO_FUERA_DE_LISTA", repuesto.codigo))

    return tuple(problemas)
