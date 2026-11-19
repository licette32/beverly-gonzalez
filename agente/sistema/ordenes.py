from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from planta_contrato import (
    EstadoOrden,
    EventoSistema,
    NotaRecorrida,
    OrdenSistema,
    Repuesto,
    Topicos,
)
from pydantic import BaseModel

from .reglas import (
    ContextoReglas,
    calcular_detiene_equipo,
    calcular_reduce_inyeccion,
    evaluar,
)
from .tools import StockItem, stock, tareas_catalogo
from .transiciones import validar_cambio

NAMESPACE = uuid.NAMESPACE_URL


class ErrorEstadoEsperado(Exception):
    def __init__(self, orden_id: str, estado_esperado: EstadoOrden) -> None:
        super().__init__(
            f"estado esperado {estado_esperado.value} no coincide para orden {orden_id}"
        )
        self.orden_id = orden_id
        self.estado_esperado = estado_esperado


@dataclass(frozen=True)
class ContextoOrden:
    """Datos para decidir y publicar una orden.

    ``stock`` debe ser el stock filtrado por la lista de materiales del equipo
    (``stock(equipo).items``). ``estado_bombas`` debe leerse fresco con
    ``EstadoPlanta.estado_bombas()`` al momento de publicar; ``None`` significa
    desconocido. ``notas_analizadas`` contiene las notas cuyas fotos ya fueron
    analizadas por visión.
    """

    tareas: Sequence[dict[str, Any]]
    stock: Sequence[StockItem]
    estado_bombas: dict[str, str] | None = None
    eventos: Sequence[EventoSistema] = ()
    notas: Mapping[str, NotaRecorrida] = field(default_factory=dict)
    notas_analizadas: frozenset[str] = frozenset()
    dano_estructural_grave: bool = False


class RegistroOrdenes(Protocol):
    """Último estado publicado por id. En el issue 10 se respalda con Postgres."""

    def get(self, orden_id: str) -> EstadoOrden | None: ...

    def set(self, orden_id: str, estado: EstadoOrden) -> None: ...


class RegistroOrdenesMemoria:
    def __init__(self) -> None:
        self._estados: dict[str, EstadoOrden] = {}

    def get(self, orden_id: str) -> EstadoOrden | None:
        return self._estados.get(orden_id)

    def set(self, orden_id: str, estado: EstadoOrden) -> None:
        self._estados[orden_id] = estado


class RepositorioOrdenes(Protocol):
    """Persistencia de órdenes para la publicación y la reanudación."""

    def guardar(self, orden: OrdenSistema) -> None: ...

    def guardar_si_estado(
        self, orden: OrdenSistema, estado_esperado: EstadoOrden
    ) -> bool: ...

    def obtener(self, orden_id: str) -> OrdenSistema | None: ...

    def cargar_pendientes(self) -> Sequence[OrdenSistema]: ...


def _id_orden(equipo: str, evento_ids: Sequence[str]) -> str:
    clave = f"pia3:orden:{equipo}:{','.join(sorted(evento_ids))}"
    return str(uuid.uuid5(NAMESPACE, clave))


def construir_orden(
    evento: EventoSistema,
    equipo: str,
    tareas: Sequence[str],
    ejecutor: str,
    repuestos: Sequence[Repuesto] = (),
    estado_bombas: Mapping[str, str] | None = None,
    *,
    catalogo_tareas: Sequence[dict[str, Any]] | None = None,
    catalogo_stock: Sequence[StockItem] | None = None,
) -> OrdenSistema:
    """Arma el Borrador interno de la orden a partir del evento.

    ``catalogo_stock`` debe ser el stock filtrado por la lista de materiales
    del equipo: los repuestos ajenos a esa lista no se incluyen en la orden.
    """
    tareas_del_catalogo = (
        list(catalogo_tareas)
        if catalogo_tareas is not None
        else tareas_catalogo()
    )
    stock_del_equipo = (
        list(catalogo_stock)
        if catalogo_stock is not None
        else stock(equipo).items
    )
    codigos = {item.codigo for item in stock_del_equipo}
    repuestos_validos = [
        repuesto for repuesto in repuestos if repuesto.codigo in codigos
    ]
    # El Borrador nunca se publica: publicar_orden lo decide antes de enviarlo.
    # La publicación del Borrador se evalúa en el issue 10, cuando haya
    # persistencia.
    return OrdenSistema(
        id=_id_orden(equipo, [evento.id]),
        ts=evento.ts,
        estado=EstadoOrden.borrador,
        equipo=equipo,
        evento_ids=[evento.id],
        tareas=list(tareas),
        detiene_equipo=calcular_detiene_equipo(tareas, tareas_del_catalogo),
        reduce_inyeccion=calcular_reduce_inyeccion(
            equipo, tareas, estado_bombas, tareas_del_catalogo
        ),
        ejecutor=ejecutor,
        repuestos=repuestos_validos,
    )


def _fotos_pendientes(orden: OrdenSistema, contexto: ContextoOrden) -> bool:
    """True si una nota vinculada tiene fotos sin analizar o no se encuentra."""
    buscados = set(orden.evento_ids)
    for evento in contexto.eventos:
        if evento.id not in buscados:
            continue
        for nota_id in evento.nota_ids:
            nota = contexto.notas.get(nota_id)
            if nota is None:
                return True
            if nota.fotos and nota_id not in contexto.notas_analizadas:
                return True
    return False


def _contexto_reglas(
    orden: OrdenSistema, contexto: ContextoOrden
) -> ContextoReglas:
    return ContextoReglas(
        tareas=list(contexto.tareas),
        stock=list(contexto.stock),
        estado_bombas=contexto.estado_bombas,
        dano_estructural_grave=contexto.dano_estructural_grave,
        fotos_pendientes_de_analisis=_fotos_pendientes(orden, contexto),
    )


def publicar_orden(
    orden: OrdenSistema,
    contexto: ContextoOrden | None = None,
    publicador: Callable[[str, BaseModel], None] | None = None,
    registro: RegistroOrdenes | None = None,
    repositorio: RepositorioOrdenes | None = None,
    *,
    estado_esperado: EstadoOrden | None = None,
) -> OrdenSistema | None:
    """Publica en ``sistema/ordenes`` la orden ya decidida.

    Si llega en Borrador, ``reglas.evaluar`` decide el estado y la tabla de
    transiciones solo valida ese destino. Con ``estado_esperado``, valida el
    cambio desde ese estado y guarda con comparación condicional antes de
    publicar. Si el guardado condicional falla, no publica.
    """
    if publicador is None:
        raise ValueError("publicador obligatorio")

    if orden.estado == EstadoOrden.borrador:
        if contexto is None:
            raise ValueError("contexto obligatorio para evaluar un Borrador")
        estado, motivo = evaluar(orden, _contexto_reglas(orden, contexto))
        decidida = orden.model_copy(
            update={"estado": estado, "motivo": motivo}
        )
        if estado_esperado is None:
            validar_cambio(decidida, estado, origen=EstadoOrden.borrador)
    else:
        decidida = orden

    if estado_esperado is not None:
        validar_cambio(decidida, decidida.estado, origen=estado_esperado)

    if registro is not None and registro.get(decidida.id) == decidida.estado:
        return None

    if repositorio is not None:
        if estado_esperado is None:
            repositorio.guardar(decidida)
        elif not repositorio.guardar_si_estado(decidida, estado_esperado):
            raise ErrorEstadoEsperado(decidida.id, estado_esperado)

    publicador(Topicos.ORDENES, decidida)
    if registro is not None:
        registro.set(decidida.id, decidida.estado)
    return decidida
