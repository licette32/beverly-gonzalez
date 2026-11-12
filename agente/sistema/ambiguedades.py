from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Literal

from .catalogo import CatalogoPlanta
from .parte import ItemParte, normalizar


@dataclass(frozen=True)
class Ambiguedad:
    tipo: Literal["equipo", "valor"]
    indice: int
    dicho: str
    opciones: tuple[str, ...]
    pregunta: str


def _dicho_generico(texto: str) -> str | None:
    normalizado = normalizar(texto)
    coincidencia = re.search(
        r"\b(?:la|el)\s+(bomba|filtro|equipo|motor|tanque|caudalimetro)\b",
        normalizado,
    )
    return coincidencia.group(1) if coincidencia else None


def detectar(items: list[ItemParte], texto: str, catalogo: CatalogoPlanta) -> list[Ambiguedad]:
    salida: list[Ambiguedad] = []
    dicho = _dicho_generico(texto)

    for indice, item in enumerate(items):
        if item.tag is not None:
            continue
        tipo_equipo = catalogo.tipo_de(dicho) if dicho else None
        if tipo_equipo is None and dicho == "bomba":
            tipo_equipo = "bomba"
        elif tipo_equipo is None and dicho == "filtro":
            tipo_equipo = "filtro"
        opciones = tuple(catalogo.opciones_equipo(tipo_equipo))
        etiqueta = dicho or "el equipo"
        salida.append(
            Ambiguedad(
                tipo="equipo",
                indice=indice,
                dicho=etiqueta,
                opciones=opciones,
                pregunta=f"¿A qué equipo te referís con «{etiqueta}»?",
            )
        )

    for indice, item in enumerate(items):
        if item.variable != "presion_diferencial" or item.valor is None:
            continue
        if item.valor < 10 or not float(item.valor).is_integer():
            continue
        unidad = item.unidad or "kg/cm2"
        menor = item.valor / 10
        opciones = (
            f"{menor:g} {unidad}".replace(".", ","),
            f"{item.valor:g} {unidad}".replace(".", ","),
        )
        salida.append(
            Ambiguedad(
                tipo="valor",
                indice=indice,
                dicho=f"{item.valor:g}",
                opciones=opciones,
                pregunta=(
                    f"Para el diferencial de {item.tag or 'el filtro'} escuché "
                    f"«{item.valor:g}». ¿Fue {opciones[0]} o {opciones[1]}?"
                ),
            )
        )
    return salida


def items_para_pantalla(
    items: list[ItemParte],
    ambiguedades: list[Ambiguedad],
    timeout: bool = False,
) -> list[ItemParte]:
    marcas: dict[int, str] = {}
    for ambiguedad in ambiguedades:
        if ambiguedad.tipo == "equipo":
            marca = f"equipo ambiguo: «{ambiguedad.dicho}»"
        else:
            marca = f"valor ambiguo: se dijo «{ambiguedad.dicho}»"
        if timeout:
            marca += "; sin respuesta del operador"
        marcas[ambiguedad.indice] = marca

    salida = []
    for indice, item in enumerate(items):
        marca = marcas.get(indice)
        if marca:
            observacion = f"{item.observacion}; {marca}" if item.observacion else marca
            if any(
                ambiguedad.indice == indice and ambiguedad.tipo == "valor"
                for ambiguedad in ambiguedades
            ):
                item = replace(item, valor=None, observacion=observacion)
            else:
                item = replace(item, observacion=observacion)
            salida.append(item)
        else:
            salida.append(item)
    return salida


def items_para_b1(
    items: list[ItemParte], ambiguedades: list[Ambiguedad]
) -> list[ItemParte]:
    salida = list(items)
    for ambiguedad in ambiguedades:
        item = salida[ambiguedad.indice]
        if ambiguedad.tipo == "equipo":
            salida[ambiguedad.indice] = replace(item, tag=None)
        else:
            salida[ambiguedad.indice] = replace(item, valor=None, observacion=None)
    return salida


def resolver_equipo(
    items: list[ItemParte], indice: int, tag: str
) -> list[ItemParte]:
    salida = list(items)
    salida[indice] = replace(salida[indice], tag=tag)
    return salida


def resolver_valor(
    items: list[ItemParte], indice: int, valor: float, unidad: str | None
) -> list[ItemParte]:
    salida = list(items)
    salida[indice] = replace(
        salida[indice],
        valor=valor,
        unidad=unidad or salida[indice].unidad,
    )
    return salida
