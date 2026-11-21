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

from . import tools
from .causas import Causa, EvidenciaEquipo, causas_probables
from .control_flujo import ControlProceso
from .historial_causas import reordenar_con_historial
from .llm import AnalizadorLLM
from .ordenes import construir_orden
from .reglas import ContextoReglas, evaluar
from .repositorio_decisiones import (
    RegistroDecisiones,
    argumentos_manuales_buscar,
    argumentos_stock,
    medir_y_registrar,
    registrar_herramienta,
)
from .validacion import Problema, validar_orden_publicable

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


def _codigo_motivo(segmento: str) -> str:
    return segmento.split(":", 1)[0].strip()


def _sumar_problemas(motivo: str, problemas: Sequence[Problema]) -> str:
    segmentos = [
        segmento.strip() for segmento in motivo.split("; ") if segmento.strip()
    ]
    codigos = {_codigo_motivo(segmento) for segmento in segmentos}
    for problema in problemas:
        if problema.codigo in codigos:
            continue
        segmentos.append(f"{problema.codigo}: {problema.detalle}")
        codigos.add(problema.codigo)
    return "; ".join(segmentos)


def _priorizar_causas(
    causas: Sequence[Causa], prioridad: Sequence[str]
) -> list[Causa]:
    if not prioridad:
        return list(causas)
    orden = {codigo: indice for indice, codigo in enumerate(dict.fromkeys(prioridad))}
    return sorted(
        causas,
        key=lambda causa: orden.get(causa.codigo_falla, len(orden)),
    )


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
    fotos_pendientes_de_analisis: bool = False,
    registro: RegistroDecisiones | None = None,
    analizador: AnalizadorLLM | None = None,
) -> ResultadoFlujo:
    """Encadena causas, análisis opcional, orden y reglas deterministas."""
    correlation_id = evento.id
    control = ControlProceso(correlation_id, registro)

    def _sin_orden_por_control(causas: Sequence[Causa]) -> ResultadoFlujo:
        motivo = control.motivo_control or "LIMITE_TIEMPO"
        return ResultadoFlujo(list(causas), None, None, (motivo,), ())

    def _con_orden_por_control(
        causas: Sequence[Causa],
        orden: Any,
        motivos_previos: tuple[str, ...] = (),
        problemas_previos: tuple[str, ...] = (),
        reglas: tuple[EstadoOrden, str] | None = None,
    ) -> ResultadoFlujo:
        motivo_control = control.motivo_control or "LIMITE_TIEMPO"
        motivos = _motivos_unicos(
            *motivos_previos, *control.motivos_pendientes, motivo_control
        )
        problemas = tuple(problemas_previos)
        if motivo_control == "LIMITE_TIEMPO":
            problemas = tuple(dict.fromkeys((*problemas, motivo_control)))
        motivo_final = "; ".join(motivos)
        orden_control = orden.model_copy(
            update={"estado": EstadoOrden.pendiente, "motivo": motivo_final}
        )
        return ResultadoFlujo(
            list(causas),
            orden_control,
            reglas or (EstadoOrden.pendiente, motivo_final),
            problemas,
            motivos,
        )

    def _corte(
        etapa: str,
        *,
        paso: str | None = None,
        herramienta: str | None = None,
        argumentos: Mapping[str, Any] | None = None,
    ) -> bool:
        if control.verificar(etapa):
            return True
        if paso is not None:
            control.detectar_loop(paso, herramienta, argumentos)
        return control.motivo_control is not None

    def buscar(texto: str):
        return registrar_herramienta(
            registro,
            correlation_id,
            "manuales_buscar",
            argumentos_manuales_buscar(texto),
            tools.manuales_buscar,
            texto,
            registro=registro,
            correlation_id=correlation_id,
        )

    if _corte("inicio"):
        return _sin_orden_por_control(())
    causas_base = medir_y_registrar(
        registro, correlation_id, "causas_probables", causas_probables, evidencia, buscar=buscar
    )
    if _corte(
        "causas_probables",
        paso="causas_probables",
        herramienta=None,
        argumentos=None,
    ):
        return _sin_orden_por_control(causas_base)
    causas = medir_y_registrar(
        registro,
        correlation_id,
        "reordenar_con_historial",
        reordenar_con_historial,
        causas_base,
        historial,
        evidencia,
    )
    if _corte(
        "reordenar_con_historial",
        paso="reordenar_con_historial",
        herramienta=None,
        argumentos=None,
    ):
        return _sin_orden_por_control(causas)
    if analizador is not None:
        analisis = analizador.analizar(
            evento=evento,
            evidencia=evidencia,
            historial=historial,
            causas=causas,
            registro=registro,
        )
        if analisis is not None:
            causas = _priorizar_causas(causas, analisis.prioridad)
    if _corte("analisis_llm"):
        return _sin_orden_por_control(causas)
    tareas = list(
        registrar_herramienta(
            registro, correlation_id, "tareas_catalogo", {}, catalogo.tareas_catalogo
        )
    )
    if _corte(
        "tareas_catalogo",
        paso="tareas_catalogo",
        herramienta="tareas_catalogo",
        argumentos={},
    ):
        return _sin_orden_por_control(causas)
    no_estandar = list(
        registrar_herramienta(
            registro,
            correlation_id,
            "tareas_no_estandar",
            {"fuente": "tareas_no_estandar"},
            catalogo.tareas_no_estandar,
            paso="materiales",
            herramienta="materiales",
        )
    )
    if _corte(
        "tareas_no_estandar",
        paso="materiales",
        herramienta="materiales",
        argumentos={"fuente": "tareas_no_estandar"},
    ):
        return _sin_orden_por_control(causas)
    candidata = next(
        (
            causa
            for causa in causas
            if causa.genera_orden
            and causa.accion in ("orden", "I-VIB", "I-VAL")
            and causa.tarea_codigo is not None
        ),
        None,
    )
    if candidata is None:
        return ResultadoFlujo(causas, None, None, ("SIN_ORDEN",), ())

    tarea = candidata.tarea_codigo or ""
    equipo = candidata.equipo_orden
    stock_equipo = list(
        registrar_herramienta(
            registro,
            correlation_id,
            "stock",
            argumentos_stock(equipo),
            catalogo.stock,
            equipo,
        )
    )
    if _corte(
        "stock",
        paso="stock",
        herramienta="stock",
        argumentos=argumentos_stock(equipo),
    ):
        return _sin_orden_por_control(causas)
    if not _tarea_en_catalogo(tareas, no_estandar, tarea, equipo, stock_equipo):
        return ResultadoFlujo(causas, None, None, ("EQUIPO_SIN_CATALOGO",), ())

    if _corte("construir_orden"):
        return _sin_orden_por_control(causas)
    pedidos = _repuestos_de_tarea(tareas, no_estandar, tarea, equipo)
    orden = medir_y_registrar(
        registro,
        correlation_id,
        "construir_orden",
        construir_orden,
        evento,
        equipo,
        [tarea],
        tarea=tarea,
        ejecutor=candidata.ejecutor,
        repuestos=pedidos,
        estado_bombas=estado_bombas,
        catalogo_tareas=tareas,
        catalogo_stock=stock_equipo,
    )

    if _corte(
        "evaluar",
        paso="construir_orden",
        herramienta=None,
        argumentos=None,
    ):
        return _con_orden_por_control(causas, orden)
    pendiente_por: tuple[str, ...] = ()
    entregados = {repuesto.codigo for repuesto in orden.repuestos}
    if any(repuesto.codigo not in entregados for repuesto in pedidos):
        pendiente_por = _motivos_unicos("REPUESTO_FALTANTE")

    contexto = ContextoReglas(
        tareas=tareas,
        stock=stock_equipo,
        estado_bombas=estado_bombas,
        dano_estructural_grave=False,
        fotos_pendientes_de_analisis=fotos_pendientes_de_analisis,
    )
    estado, motivo = medir_y_registrar(
        registro, correlation_id, "evaluar", evaluar, orden, contexto, tarea=tarea
    )
    if _corte(
        "validar_orden_publicable",
        paso="evaluar",
        herramienta=None,
        argumentos=None,
    ):
        return _con_orden_por_control(
            causas, orden, pendiente_por, (), (estado, motivo)
        )
    if estado == EstadoOrden.pendiente:
        pendiente_por = _motivos_unicos(*pendiente_por, motivo)
    pendiente_por = _motivos_unicos(*pendiente_por, *control.motivos_pendientes)

    if pendiente_por:
        estado_final = EstadoOrden.pendiente
        motivo_final = "; ".join(pendiente_por)
    else:
        estado_final = EstadoOrden.aprobada
        motivo_final = motivo

    materiales = registrar_herramienta(
        registro,
        correlation_id,
        "_cargar_materiales",
        {"fuente": "_cargar_materiales"},
        tools._cargar_materiales,
        paso="materiales",
        herramienta="materiales",
    )
    if _corte(
        "validar_orden_publicable:materiales",
        paso="materiales",
        herramienta="materiales",
        argumentos={"fuente": "_cargar_materiales"},
    ):
        return _con_orden_por_control(
            causas, orden, pendiente_por, (), (estado, motivo)
        )
    hallazgos = medir_y_registrar(
        registro,
        correlation_id,
        "validar_orden_publicable",
        validar_orden_publicable,
        orden,
        candidata.citas,
        materiales,
        tarea=tarea,
    )
    if hallazgos:
        if estado_final == EstadoOrden.aprobada:
            estado_final = EstadoOrden.pendiente
        motivo_final = _sumar_problemas(motivo_final, hallazgos)
    problemas_revisor = tuple(dict.fromkeys(problema.codigo for problema in hallazgos))
    if control.motivo_control == "LIMITE_TIEMPO":
        problemas_revisor = tuple(dict.fromkeys((*problemas_revisor, "LIMITE_TIEMPO")))

    orden = orden.model_copy(update={"estado": estado_final, "motivo": motivo_final})

    return ResultadoFlujo(
        causas, orden, (estado, motivo), problemas_revisor, pendiente_por
    )
