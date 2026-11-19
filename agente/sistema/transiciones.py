from __future__ import annotations

import re
from enum import Enum

from planta_contrato import EstadoOrden, NotaCierre, OrdenSistema

HABILITA_RE = re.compile(r"HAB-\d{4}-\d{4}")


class Accion(str, Enum):
    evaluar = "evaluar"
    aprobar = "aprobar"
    rechazar = "rechazar"
    registrar_cierre = "registrar_cierre"
    cerrar = "cerrar"
    certificar = "certificar"
    observar = "observar"


class ErrorTransicion(Exception):
    def __init__(
        self,
        orden_id: str,
        accion: Accion | str,
        origen: EstadoOrden,
        destino: EstadoOrden,
        detalle: str | None = None,
    ) -> None:
        self.orden_id = orden_id
        self.accion = accion.value if isinstance(accion, Accion) else accion
        self.origen = origen
        self.destino = destino
        self.detalle = detalle
        mensaje = (
            f"transición inválida id={orden_id} acción={self.accion} "
            f"desde={origen.value} hacia={destino.value}"
        )
        if detalle:
            mensaje = f"{mensaje}: {detalle}"
        super().__init__(mensaje)


TRANSICIONES: dict[Accion, dict[EstadoOrden, frozenset[EstadoOrden]]] = {
    Accion.evaluar: {  # acción interna: publicar_orden la usa vía validar_cambio, no es comando CLI
        EstadoOrden.borrador: frozenset(
            {EstadoOrden.pendiente, EstadoOrden.aprobada}
        )
    },
    Accion.aprobar: {
        EstadoOrden.pendiente: frozenset({EstadoOrden.aprobada})
    },
    Accion.rechazar: {
        EstadoOrden.pendiente: frozenset({EstadoOrden.rechazada})
    },
    Accion.registrar_cierre: {
        EstadoOrden.aprobada: frozenset({EstadoOrden.ejecutada})
    },
    Accion.cerrar: {
        EstadoOrden.ejecutada: frozenset({EstadoOrden.cerrada})
    },
    Accion.certificar: {
        EstadoOrden.ejecutada: frozenset({EstadoOrden.certificada})
    },
    Accion.observar: {
        EstadoOrden.ejecutada: frozenset({EstadoOrden.observada})
    },
}


def _accion(accion: Accion | str) -> Accion:
    return accion if isinstance(accion, Accion) else Accion(accion)


def _validar_nota(orden: OrdenSistema, nota: NotaCierre | None) -> None:
    detalle: str | None = None
    if nota is None:
        detalle = "nota de cierre obligatoria"
    elif nota.orden_id != orden.id:
        detalle = f"nota {nota.id} pertenece a orden {nota.orden_id}"
    elif (nota.empresa == "propio") != (orden.ejecutor == "propio"):
        detalle = (
            f"empresa de la nota {nota.empresa!r} no coincide con "
            f"ejecutor de la orden {orden.ejecutor!r}"
        )
    if detalle is not None:
        raise ErrorTransicion(
            orden.id, Accion.registrar_cierre, orden.estado, EstadoOrden.ejecutada, detalle
        )


def validar_accion(
    orden: OrdenSistema,
    accion: Accion | str,
    destino: EstadoOrden | None = None,
    *,
    motivo: str | None = None,
    nota: NotaCierre | None = None,
) -> None:
    accion_resuelta = _accion(accion)
    destino_resuelto = orden.estado if destino is None else destino
    permitidos = TRANSICIONES.get(accion_resuelta, {}).get(
        orden.estado, frozenset()
    )
    if destino_resuelto not in permitidos:
        raise ErrorTransicion(
            orden.id, accion_resuelta, orden.estado, destino_resuelto
        )
    if accion_resuelta in (Accion.rechazar, Accion.observar) and not (
        motivo or ""
    ).strip():
        raise ErrorTransicion(
            orden.id,
            accion_resuelta,
            orden.estado,
            destino_resuelto,
            "motivo obligatorio",
        )
    if accion_resuelta is Accion.cerrar and orden.ejecutor != "propio":
        raise ErrorTransicion(
            orden.id,
            accion_resuelta,
            orden.estado,
            destino_resuelto,
            "el cierre de contratista lo certifica u observa el inspector",
        )
    if accion_resuelta in (Accion.certificar, Accion.observar) and (
        orden.ejecutor == "propio"
    ):
        raise ErrorTransicion(
            orden.id,
            accion_resuelta,
            orden.estado,
            destino_resuelto,
            "el trabajo propio se cierra, no se certifica ni se observa",
        )
    if accion_resuelta is Accion.registrar_cierre:
        _validar_nota(orden, nota)


def validar_cambio(
    orden: OrdenSistema,
    destino: EstadoOrden,
    *,
    origen: EstadoOrden | None = None,
) -> Accion:
    origen_resuelto = orden.estado if origen is None else origen
    for accion, origenes in TRANSICIONES.items():
        if destino in origenes.get(origen_resuelto, frozenset()):
            return accion
    raise ErrorTransicion(orden.id, "cambio", origen_resuelto, destino)


def _destino_unico(accion: Accion, orden: OrdenSistema) -> EstadoOrden:
    destinos = TRANSICIONES.get(accion, {}).get(orden.estado, frozenset())
    if len(destinos) != 1:
        raise ErrorTransicion(
            orden.id, accion, orden.estado, orden.estado, "destino no determinado"
        )
    return next(iter(destinos))


def transicionar(
    orden: OrdenSistema,
    accion: Accion | str,
    motivo: str | None = None,
    *,
    nota: NotaCierre | None = None,
    habilita: str | None = None,
    monto_habilita_usd: float | None = None,
) -> OrdenSistema:
    accion_resuelta = _accion(accion)
    if accion_resuelta is Accion.registrar_cierre:
        _validar_nota(orden, nota)
        if orden.estado is EstadoOrden.ejecutada:
            return orden

    destino = _destino_unico(accion_resuelta, orden)
    validar_accion(
        orden, accion_resuelta, destino, motivo=motivo, nota=nota
    )
    cambios: dict[str, object] = {"estado": destino}

    if accion_resuelta in (Accion.rechazar, Accion.observar):
        cambios["motivo"] = (motivo or "").strip()

    if accion_resuelta is Accion.certificar:
        habilita_resuelta = habilita if habilita is not None else orden.habilita
        monto_resuelto = (
            monto_habilita_usd
            if monto_habilita_usd is not None
            else orden.monto_habilita_usd
        )
        if habilita_resuelta is None or not HABILITA_RE.fullmatch(
            habilita_resuelta
        ):
            raise ErrorTransicion(
                orden.id,
                accion_resuelta,
                orden.estado,
                destino,
                "habilita con formato HAB-AAAA-NNNN obligatoria",
            )
        if monto_resuelto is None or monto_resuelto <= 0:
            raise ErrorTransicion(
                orden.id,
                accion_resuelta,
                orden.estado,
                destino,
                "monto_habilita_usd mayor que cero obligatorio",
            )
        cambios["habilita"] = habilita_resuelta
        cambios["monto_habilita_usd"] = monto_resuelto

    return orden.model_copy(update=cambios)
