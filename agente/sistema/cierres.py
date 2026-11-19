from __future__ import annotations

import logging
from collections.abc import Callable

from planta_contrato import EstadoOrden, NotaCierre, OrdenSistema, Topicos
from pydantic import BaseModel

from .ordenes import RepositorioOrdenes
from .transiciones import Accion, ErrorTransicion, transicionar

log = logging.getLogger(__name__)


class ManejadorCierres:
    def __init__(
        self,
        repositorio: RepositorioOrdenes,
        publicador: Callable[[str, BaseModel], None],
    ) -> None:
        self._repositorio = repositorio
        self._publicador = publicador

    def __call__(self, nota: NotaCierre) -> OrdenSistema | None:
        orden = self._repositorio.obtener(nota.orden_id)
        if orden is None:
            log.error(
                "anomalía en cierre %s: orden %s no encontrada",
                nota.id,
                nota.orden_id,
            )
            return None

        if orden.estado is EstadoOrden.ejecutada:
            log.info(
                "cierre idempotente %s: orden %s ya ejecutada", nota.id, orden.id
            )
            return None

        try:
            ejecutada = transicionar(
                orden, Accion.registrar_cierre, nota=nota
            )
        except ErrorTransicion as exc:
            log.error("anomalía en cierre %s: %s", nota.id, exc)
            return None

        self._repositorio.guardar(ejecutada)
        self._publicador(Topicos.ORDENES, ejecutada)
        log.info(
            "cierre %s aplicado: orden %s pasó a %s",
            nota.id,
            orden.id,
            ejecutada.estado.value,
        )
        return ejecutada
