"""Punto de entrada determinista del issue #7: causas, historial, orden y reglas.

``estado_bombas`` por defecto es ``None``: ``flujo`` no consulta el estado vivo
de la planta. El enganche en ``coordinador`` debe pasar el estado real cuando
lo tenga y propagarlo a ``construir_orden`` y ``ContextoReglas``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from planta_contrato import EstadoOrden, EventoSistema, OrdenSistema, Repuesto

from .causas import Causa, EvidenciaEquipo, causas_probables
from .historial_causas import reordenar_con_historial
from .ordenes import construir_orden
from .reglas import ContextoReglas, evaluar

if TYPE_CHECKING:
    from .tools import StockItem


class CatalogoFlujo(Protocol):
    def tareas_catalogo(self) -> Sequence[dict[str, Any]]: ...

    def tareas_no_estandar(self) -> Sequence[dict[str, Any]]: ...

    def stock(self, equipo: str) -> Sequence["StockItem"]: ...


class CatalogoTools:
    """Adaptador concreto; importa ``tools`` de forma diferida para evitar ciclos."""

    def tareas_catalogo(self) -> Sequence[dict[str, Any]]:
        from . import tools

        return tools.tareas_catalogo()

    def tareas_no_estandar(self) -> Sequence[dict[str, Any]]:
        from . import tools

        datos = tools._cargar_materiales()
        tareas = datos.get("tareas_no_estandar")
        return tareas if isinstance(tareas, list) else []

    def stock(self, equipo: str) -> Sequence["StockItem"]:
        from . import tools

        return tools.stock(equipo).items


@dataclass(frozen=True)
class ResultadoFlujo:
    causas: list[Causa]
    orden: OrdenSistema | None
    reglas: tuple[EstadoOrden, str] | None
    problemas: tuple[str, ...]
    pendiente_por: tuple[str, ...]


def _motivos_unicos(*partes: str) -> tuple[str, ...]:
    unicos: list[str] = []
    for parte in partes:
        for codigo in parte.split("; "):
            codigo = codigo.strip()
            if codigo and codigo not in unicos:
                unicos.append(codigo)
    return tuple(unicos)


def _tarea_en_catalogo(
    tareas_estandar: Sequence[dict[str, Any]],
    tareas_no_estandar: Sequence[dict[str, Any]],
    codigo: str,
    equipo: str,
    stock_equipo: Sequence[Any] = (),
) -> bool:
    if any(
        tarea.get("codigo") == codigo and equipo in (tarea.get("equipos") or [])
        for tarea in tareas_estandar
    ):
        return True
    if any(tarea.get("codigo") == codigo for tarea in tareas_no_estandar):
        return bool(stock_equipo) or any(
            equipo in (tarea.get("equipos") or []) for tarea in tareas_estandar
        )
    return False


def _repuestos_de_tarea(
    tareas_estandar: Sequence[dict[str, Any]],
    tareas_no_estandar: Sequence[dict[str, Any]],
    codigo: str,
    equipo: str,
) -> tuple[Repuesto, ...]:
    for tarea in (*tareas_estandar, *tareas_no_estandar):
        if tarea.get("codigo") != codigo:
            continue
        equipos = tarea.get("equipos")
        if equipos is not None and equipo not in equipos:
            continue
        try:
            return tuple(
                Repuesto(codigo=fila["codigo"], cantidad=float(fila["cantidad"]))
                for fila in (tarea.get("repuestos") or [])
            )
        except (KeyError, TypeError, ValueError):
            return ()
    return ()


def procesar(
    evento: EventoSistema,
    evidencia: EvidenciaEquipo,
    historial: Sequence[Any],
    catalogo: CatalogoFlujo,
    estado_bombas: Mapping[str, str] | None = None,
) -> ResultadoFlujo:
    """Encadena causas, historial, orden y reglas sin LLM ni efectos externos."""
    causas = reordenar_con_historial(
        causas_probables(evidencia), historial, evidencia
    )
    tareas = list(catalogo.tareas_catalogo())
    no_estandar = list(catalogo.tareas_no_estandar())
    candidata = next(
        (
            causa
            for causa in causas
            if causa.genera_orden
            and causa.accion == "orden"
            and causa.tarea_codigo is not None
        ),
        None,
    )
    if candidata is None:
        return ResultadoFlujo(causas, None, None, ("SIN_ORDEN",), ())

    equipo = candidata.equipo_orden
    stock_equipo = list(catalogo.stock(equipo))
    if not _tarea_en_catalogo(
        tareas, no_estandar, candidata.tarea_codigo or "", equipo, stock_equipo
    ):
        return ResultadoFlujo(causas, None, None, ("EQUIPO_SIN_CATALOGO",), ())

    pedidos = _repuestos_de_tarea(
        tareas, no_estandar, candidata.tarea_codigo or "", equipo
    )
    orden = construir_orden(
        evento,
        equipo,
        [candidata.tarea_codigo or ""],
        ejecutor=candidata.ejecutor,
        repuestos=pedidos,
        estado_bombas=estado_bombas,
        catalogo_tareas=tareas,
        catalogo_stock=stock_equipo,
    )

    pendiente_por: tuple[str, ...] = ()
    entregados = {repuesto.codigo for repuesto in orden.repuestos}
    if any(repuesto.codigo not in entregados for repuesto in pedidos):
        pendiente_por = _motivos_unicos("REPUESTO_FALTANTE")

    contexto = ContextoReglas(
        tareas=tareas,
        stock=stock_equipo,
        estado_bombas=estado_bombas,
        dano_estructural_grave=False,
        fotos_pendientes_de_analisis=False,
    )
    estado, motivo = evaluar(orden, contexto)
    if estado == EstadoOrden.pendiente:
        pendiente_por = _motivos_unicos(*pendiente_por, motivo)

    if pendiente_por:
        estado_final = EstadoOrden.pendiente
        motivo_final = "; ".join(pendiente_por)
    else:
        estado_final = EstadoOrden.aprobada
        motivo_final = motivo
    orden = orden.model_copy(update={"estado": estado_final, "motivo": motivo_final})

    return ResultadoFlujo(causas, orden, (estado, motivo), (), pendiente_por)
