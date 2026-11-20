from __future__ import annotations

import re
from collections import defaultdict
from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel

from . import tools
from .parte import normalizar, numeros

ResultadoPrueba = Literal["ok", "con_perdida", "no_informado"]
TipoDiferenciaCierre = Literal[
    "TAREA_NO_HECHA",
    "TAREA_EXTRA",
    "REPUESTO_NO_USADO",
    "REPUESTO_DE_MAS",
    "CANTIDAD_MENOR",
    "REPUESTO_NO_RESERVADO",
    "REPUESTO_NO_IDENTIFICADO",
    "PRUEBA_NO_INFORMADA",
    "PRUEBA_CON_PERDIDA",
    "CIERRE_SIN_TRANSCRIPCION",
]

SINONIMOS_TAREAS = {
    "analisis de vibraciones": "I-VIB",
    "medí las tres bombas": "I-VIB",
    "medir las tres bombas": "I-VIB",
    "cambio de empaquetaduras": "T-B-EMP",
    "cambio de correa": "T-B-COR",
}

SINONIMOS_REPUESTOS = {
    "kit de empaquetadura": "TX-EMP-KIT",
    "kit de valvulas": "TX-VAL-KIT",
    "juego de rodamientos": "TX-ROD-CIG",
    "juego de sellos": "TX-SELLO-CAR",
    "aceite iso vg 220": "ACE-ISO220",
    "correa 5v": "COR-5V-1800",
    "elastomeros de acople": "ACO-ELAST-90",
    "junta de tapa": "FC-JUNTA-TAPA",
    "transmisor de presion": "INS-TRANS-P",
}

REPUESTOS_AMBIGUOS = {
    "cartucho filtrante": ("FC-CART-25", "FC-CART-10"),
}


class RepuestoCierre(BaseModel):
    codigo: str
    cantidad: float


class ParteCierre(BaseModel):
    tareas: list[str] = []
    repuestos: list[RepuestoCierre] = []
    horas: float | None = None
    resultado_prueba: ResultadoPrueba = "no_informado"
    presion_prueba: float | None = None
    repuestos_no_identificados: list[str] = []


class DiferenciaCierre(BaseModel):
    tipo: TipoDiferenciaCierre
    valor_pedido: Any = None
    valor_declarado: Any = None
    codigo: str | None = None


def _normalizar(texto: str) -> str:
    return normalizar(texto).replace("\u00b5", "u").replace("\u03bc", "u")


@lru_cache(maxsize=1)
def _catalogos() -> tuple[
    dict[str, str],
    dict[str, str],
    dict[str, tuple[str, ...]],
    dict[str, frozenset[str]],
]:
    datos = tools._cargar_materiales()
    tareas: dict[str, str] = {}
    for clave in ("tareas_estandar", "tareas_no_estandar"):
        for tarea in datos.get(clave, []):
            nombre = _normalizar(tarea["nombre"])
            if nombre:
                tareas[nombre] = tarea["codigo"]
    tareas.update({_normalizar(k): v for k, v in SINONIMOS_TAREAS.items()})

    repuestos: dict[str, str] = {}
    for repuesto in datos.get("repuestos", []):
        nombre = _normalizar(repuesto["nombre"])
        if nombre:
            repuestos[nombre] = repuesto["codigo"]
    repuestos.update({_normalizar(k): v for k, v in SINONIMOS_REPUESTOS.items()})

    ambiguos = {_normalizar(k): v for k, v in REPUESTOS_AMBIGUOS.items()}
    reservados = {
        tag: frozenset(codigos)
        for tag, codigos in (datos.get("lista_materiales") or {}).items()
    }
    return tareas, repuestos, ambiguos, reservados


def _limite(texto: str, inicio: int, fin: int) -> bool:
    anterior = texto[inicio - 1] if inicio else " "
    posterior = texto[fin] if fin < len(texto) else " "
    return not (anterior.isalnum() or posterior.isalnum())


def _buscar(
    texto: str, aliases: dict[str, Any], desde: int
) -> tuple[int, int, str, Any] | None:
    mejor: tuple[int, int, str, Any] | None = None
    for alias, valor in aliases.items():
        if not alias:
            continue
        inicio = texto.find(alias, desde)
        if inicio < 0:
            continue
        fin = inicio + len(alias)
        if not _limite(texto, inicio, fin):
            continue
        if mejor is None or (inicio, -len(alias)) < (mejor[0], -len(mejor[2])):
            mejor = (inicio, fin, alias, valor)
    return mejor


def _numero_a_la_izquierda(
    lista: list[tuple[int, int, float]], posicion: int
) -> float | None:
    previos = [numero for numero in lista if numero[1] <= posicion]
    return previos[-1][2] if previos else None


def _extraer_tareas(texto: str, aliases: dict[str, str]) -> list[str]:
    tareas: list[str] = []
    desde = 0
    while True:
        encontrado = _buscar(texto, aliases, desde)
        if encontrado is None:
            break
        inicio, fin, _, codigo = encontrado
        if codigo not in tareas:
            tareas.append(codigo)
        desde = fin
    return tareas


def _extraer_repuestos(
    texto: str,
    aliases: dict[str, str],
    ambiguos: dict[str, tuple[str, ...]],
    lista_numeros: list[tuple[int, int, float]],
) -> tuple[list[RepuestoCierre], list[str]]:
    encontrados: dict[str, float] = defaultdict(float)
    no_identificados: list[str] = []
    desde = 0
    while True:
        conocido = _buscar(texto, aliases, desde)
        ambiguo = _buscar(texto, ambiguos, desde)
        mejor = None
        for candidato, es_ambiguo in ((conocido, False), (ambiguo, True)):
            if candidato is None:
                continue
            if mejor is None or (candidato[0], -len(candidato[2])) < (
                mejor[0][0],
                -len(mejor[0][2]),
            ):
                mejor = (candidato, es_ambiguo)
        if mejor is None:
            break
        (inicio, fin, alias, valor), es_ambiguo = mejor
        cantidad = _numero_a_la_izquierda(lista_numeros, inicio) or 1.0
        if es_ambiguo:
            no_identificados.append(alias)
        else:
            encontrados[valor] += cantidad
        desde = fin
    repuestos = [
        RepuestoCierre(codigo=codigo, cantidad=cantidad)
        for codigo, cantidad in sorted(encontrados.items())
    ]
    return repuestos, no_identificados


def _extraer_horas(
    texto: str, lista_numeros: list[tuple[int, int, float]]
) -> float | None:
    for coincidencia in re.finditer(r"\bhoras?\b", texto):
        valor = _numero_a_la_izquierda(lista_numeros, coincidencia.start())
        if valor is not None:
            return valor
    return None


def _extraer_presion(
    texto: str, lista_numeros: list[tuple[int, int, float]]
) -> float | None:
    for coincidencia in re.finditer(
        r"\b(kilos|kilogramos|psi|bares|bar|kg/cm2)\b", texto
    ):
        contexto = texto[max(0, coincidencia.start() - 40) : coincidencia.start()]
        if not re.search(r"\b(proba|probe|presion|prueba|test)\b", contexto):
            continue
        valor = _numero_a_la_izquierda(lista_numeros, coincidencia.start())
        if valor is not None:
            return valor
    return None


def _resultado_prueba(texto: str) -> ResultadoPrueba:
    if re.search(r"\b(sin perdida|sin fuga|sin fugas|normal|esta bien|está bien)\b", texto):
        return "ok"
    if re.search(r"\b(con perdida|pierde|perdidas?|fuga)\b", texto):
        return "con_perdida"
    return "no_informado"


def extraer_parte_cierre(texto: str) -> ParteCierre:
    normalizado = _normalizar(texto)
    tareas_alias, repuestos_alias, ambiguos, _ = _catalogos()
    lista_numeros = numeros(normalizado)
    repuestos, no_identificados = _extraer_repuestos(
        normalizado, repuestos_alias, ambiguos, lista_numeros
    )
    return ParteCierre(
        tareas=_extraer_tareas(normalizado, tareas_alias),
        repuestos=repuestos,
        horas=_extraer_horas(normalizado, lista_numeros),
        resultado_prueba=_resultado_prueba(normalizado),
        presion_prueba=_extraer_presion(normalizado, lista_numeros),
        repuestos_no_identificados=no_identificados,
    )


def comparar_cierre(parte: ParteCierre, orden: Any) -> list[DiferenciaCierre]:
    diferencias: list[DiferenciaCierre] = []
    tareas_pedidas = set(orden.tareas)
    tareas_dichas = set(parte.tareas)
    for codigo in sorted(tareas_pedidas - tareas_dichas):
        diferencias.append(
            DiferenciaCierre(
                tipo="TAREA_NO_HECHA", valor_pedido=codigo, valor_declarado=None
            )
        )
    for codigo in sorted(tareas_dichas - tareas_pedidas):
        diferencias.append(
            DiferenciaCierre(
                tipo="TAREA_EXTRA", valor_pedido=None, valor_declarado=codigo
            )
        )

    pedidos = {repuesto.codigo: float(repuesto.cantidad) for repuesto in orden.repuestos}
    declarados: dict[str, float] = defaultdict(float)
    for repuesto in parte.repuestos:
        declarados[repuesto.codigo] += float(repuesto.cantidad)
    _, _, _, reservados = _catalogos()
    permitidos = reservados.get(orden.equipo, frozenset())

    for codigo in sorted(declarados):
        cantidad = declarados[codigo]
        declarado = {"codigo": codigo, "cantidad": cantidad}
        if codigo in pedidos and cantidad < pedidos[codigo]:
            diferencias.append(
                DiferenciaCierre(
                    tipo="CANTIDAD_MENOR",
                    valor_pedido=pedidos[codigo],
                    valor_declarado=cantidad,
                    codigo=codigo,
                )
            )
        elif codigo not in pedidos:
            if permitidos and codigo not in permitidos:
                diferencias.append(
                    DiferenciaCierre(
                        tipo="REPUESTO_NO_RESERVADO",
                        valor_pedido=None,
                        valor_declarado=declarado,
                        codigo=codigo,
                    )
                )
            else:
                diferencias.append(
                    DiferenciaCierre(
                        tipo="REPUESTO_DE_MAS",
                        valor_pedido=None,
                        valor_declarado=declarado,
                        codigo=codigo,
                    )
                )

    for texto in parte.repuestos_no_identificados:
        diferencias.append(
            DiferenciaCierre(
                tipo="REPUESTO_NO_IDENTIFICADO",
                valor_pedido=None,
                valor_declarado=texto,
            )
        )

    for codigo in sorted(pedidos.keys() - declarados.keys()):
        diferencias.append(
            DiferenciaCierre(
                tipo="REPUESTO_NO_USADO",
                valor_pedido=pedidos[codigo],
                valor_declarado=None,
                codigo=codigo,
            )
        )

    if parte.resultado_prueba == "con_perdida":
        diferencias.append(
            DiferenciaCierre(
                tipo="PRUEBA_CON_PERDIDA",
                valor_pedido="ok",
                valor_declarado="con_perdida",
            )
        )
    elif parte.resultado_prueba == "no_informado":
        diferencias.append(
            DiferenciaCierre(
                tipo="PRUEBA_NO_INFORMADA",
                valor_pedido="ok",
                valor_declarado="no_informado",
            )
        )
    return diferencias
