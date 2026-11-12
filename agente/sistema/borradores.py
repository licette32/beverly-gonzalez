from __future__ import annotations

from planta_contrato import FilaParte, MensajeTablet, NotaRecorrida, Pantalla

from .ids import id_tablet
from .parte import ItemParte

TAG_SIN_EQUIPO = "SIN-EQUIPO"


def fila_desde_item(item: ItemParte) -> FilaParte:
    # El contrato exige tag string; el equipo sin resolver se marca explícitamente.
    return FilaParte(
        tag=item.tag or TAG_SIN_EQUIPO,
        variable=item.variable,
        valor=item.valor,
        unidad=item.unidad,
        observacion=item.observacion,
    )


def borrador(
    nota: NotaRecorrida,
    items: list[ItemParte],
    intento: int,
    texto: str | None = None,
) -> MensajeTablet:
    filas = [fila_desde_item(item) for item in items]
    return MensajeTablet(
        id=id_tablet(nota.id, "borrador", intento),
        ts=nota.ts,
        nota_ids=[nota.id],
        texto=texto or "Revisá y confirmá el parte de la recorrida.",
        pantalla=Pantalla(
            titulo="Parte de recorrida",
            filas=filas,
            opciones=[],
        ),
        espera_respuesta=True,
    )


def pregunta(
    nota: NotaRecorrida,
    items: list[ItemParte],
    intento: int,
    secuencia: int,
    texto: str,
    opciones: list[str],
) -> MensajeTablet:
    filas = [fila_desde_item(item) for item in items]
    return MensajeTablet(
        id=id_tablet(nota.id, "pregunta", intento, secuencia),
        ts=nota.ts,
        nota_ids=[nota.id],
        texto=texto,
        pantalla=Pantalla(
            titulo="Parte de recorrida",
            filas=filas,
            opciones=opciones,
        ),
        espera_respuesta=True,
    )


def items_seguridad(detecciones) -> list[ItemParte]:
    detalle = "; ".join(
        f"{deteccion.categoria}: {deteccion.evidencia}" for deteccion in detecciones
    )
    return [
        ItemParte(
            tag="PLANTA",
            variable="condicion_insegura",
            valor=None,
            unidad=None,
            observacion=detalle,
        )
    ]
