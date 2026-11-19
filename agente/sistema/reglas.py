from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from planta_contrato import EstadoOrden, OrdenSistema

from .tools import StockItem

COSTO_MAX_USD = 2500.0
ALMACEN = "yacimiento"
MOTIVO_APROBADA = "cumple todas las reglas"


@dataclass(frozen=True)
class ContextoReglas:
    tareas: list[dict[str, Any]]
    stock: list[StockItem]
    estado_bombas: dict[str, str] | None = None
    dano_estructural_grave: bool = False
    fotos_pendientes_de_analisis: bool = False


def _tareas_estandar_por_equipo(tareas: list[dict[str, Any]]) -> dict[str, set[str]]:
    estandar: dict[str, set[str]] = {}
    for tarea in tareas:
        codigo = tarea.get("codigo")
        if not isinstance(codigo, str):
            continue
        for equipo in tarea.get("equipos") or []:
            estandar.setdefault(equipo, set()).add(codigo)
    return estandar


def _tareas_por_codigo(tareas: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    indice: dict[str, list[dict[str, Any]]] = {}
    for tarea in tareas:
        codigo = tarea.get("codigo")
        if isinstance(codigo, str):
            indice.setdefault(codigo, []).append(tarea)
    return indice


def _detiene(codigo: str, tareas: dict[str, list[dict[str, Any]]]) -> bool:
    """Una tarea desconocida se asume que detiene el equipo (falla cerrado)."""
    encontradas = tareas.get(codigo)
    if not encontradas:
        return True
    return any(tarea.get("detiene", True) for tarea in encontradas)


def _pedidos_validos(orden: OrdenSistema) -> tuple[dict[str, float], bool]:
    """Suma cantidades por código, descartando filas no positivas o no finitas."""
    pedidos: dict[str, float] = {}
    invalida = False
    for repuesto in orden.repuestos:
        if not math.isfinite(repuesto.cantidad) or repuesto.cantidad <= 0:
            invalida = True
            continue
        pedidos[repuesto.codigo] = pedidos.get(repuesto.codigo, 0.0) + repuesto.cantidad
    return pedidos, invalida


def evaluar(orden: OrdenSistema, contexto: ContextoReglas) -> tuple[EstadoOrden, str]:
    """Aplica las reglas de aprobación del planificador.

    El llamador debe pasar ``stock(orden.equipo)``, es decir el stock filtrado
    por ``lista_materiales[orden.equipo]``: los códigos presentes en
    ``contexto.stock`` son la lista de materiales admitida para el equipo.
    Debe pasar ``fotos_pendientes_de_analisis=True`` si la nota vinculada a la
    orden tiene fotos sin analizar. ``estado_bombas`` es el estado actual
    (tag -> "marcha"/"parada"/...); si es ``None`` el dato es desconocido y la
    reserva se considera no confirmada.

    Devuelve (Aprobada, motivo) si cumple todas; (PendienteAprobacion, motivo)
    si falla alguna, listando en orden fijo las reglas que fallaron.
    """
    estandar = _tareas_estandar_por_equipo(contexto.tareas)
    materiales = {item.codigo for item in contexto.stock}
    costos = {item.codigo: item.costo_unitario for item in contexto.stock}
    en_almacen = {
        item.codigo: item for item in contexto.stock if item.almacen == ALMACEN
    }
    pedidos, cantidad_invalida = _pedidos_validos(orden)
    fallan: list[str] = []

    codigos = estandar.get(orden.equipo, set())
    if not orden.tareas or any(tarea not in codigos for tarea in orden.tareas):
        fallan.append("TAREA_NO_ESTANDAR")

    por_codigo = _tareas_por_codigo(contexto.tareas)
    detiene = any(_detiene(tarea, por_codigo) for tarea in orden.tareas)
    bombas = contexto.estado_bombas
    reduce_calculado = detiene and (
        bombas is None
        or (
            bombas.get(orden.equipo) == "marcha"
            and not any(
                estado == "parada"
                for tag, estado in bombas.items()
                if tag != orden.equipo
            )
        )
    )
    if orden.reduce_inyeccion or reduce_calculado:
        fallan.append("REDUCE_INYECCION")

    if cantidad_invalida:
        fallan.append("CANTIDAD_INVALIDA")

    fuera_de_lista = False
    sin_stock = False
    for codigo, cantidad in pedidos.items():
        if codigo not in materiales:
            fuera_de_lista = True
            continue
        item = en_almacen.get(codigo)
        if item is None or cantidad > item.cantidad:
            sin_stock = True
    if fuera_de_lista:
        fallan.append("REPUESTO_FUERA_DE_LISTA")
    if sin_stock:
        fallan.append("REPUESTO_SIN_STOCK")

    costo = sum(
        costos[codigo] * cantidad
        for codigo, cantidad in pedidos.items()
        if codigo in costos
    )
    if costo >= COSTO_MAX_USD:
        fallan.append("COSTO_EXCEDIDO")

    if orden.ejecutor != "propio":
        fallan.append("EJECUTOR_NO_PROPIO")
    if contexto.dano_estructural_grave:
        fallan.append("DANO_ESTRUCTURAL")
    if contexto.fotos_pendientes_de_analisis:
        fallan.append("FOTOS_PENDIENTES")

    if fallan:
        return EstadoOrden.pendiente, "; ".join(fallan)
    return EstadoOrden.aprobada, MOTIVO_APROBADA
