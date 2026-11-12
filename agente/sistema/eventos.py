import uuid

from planta_contrato import EventoSistema, NotaRecorrida, TipoEvento

from .parte import ItemParte, OBSERVACIONES_NORMALES, fuera_de_limite


def _id(nota_id: str, sufijo: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"pia3:{nota_id}:{sufijo}"))


def _es_anomalia(item: ItemParte) -> bool:
    observacion = item.observacion
    return (observacion is not None and observacion not in OBSERVACIONES_NORMALES) or fuera_de_limite(item)


def eventos_parte(nota: NotaRecorrida, items: list[ItemParte]) -> list[EventoSistema]:
    por_equipo: dict[str | None, bool] = {}
    for item in items:
        por_equipo[item.tag] = por_equipo.get(item.tag, False) or _es_anomalia(item)
    if not por_equipo:
        por_equipo = {None: False}

    eventos = []
    for tag, anomalo in por_equipo.items():
        eventos.append(
            EventoSistema(
                id=_id(nota.id, f"b1:{tag or 'sin-equipo'}"),
                ts=nota.ts,
                tipo=TipoEvento.escalado if anomalo else TipoEvento.sin_novedad,
                equipo=tag,
                origen="parte",
                nota_ids=[nota.id],
                resumen="Anomalía informada en la recorrida" if anomalo else "Recorrida sin novedad",
            )
        )
    return eventos