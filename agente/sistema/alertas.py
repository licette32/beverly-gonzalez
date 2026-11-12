import uuid

from planta_contrato import (
    EventoSistema,
    FilaParte,
    MensajeTablet,
    NotaRecorrida,
    Pantalla,
    TipoEvento,
)

from .seguridad import Deteccion

PROCEDIMIENTOS = {
    "S1": "Aléjese de la fuga, no se acerque y avise por radio al supervisor.",
    "S2": "Aléjese del sector, no encienda equipos y avise por radio al supervisor.",
    "S3": "Aléjese del fuego o humo, no use el equipo y avise por radio al supervisor.",
    "S4": "No mueva a la persona lesionada, pida ayuda y avise por radio al supervisor.",
}
FALLBACK = "Siga el procedimiento de emergencia y avise por radio al supervisor."


def _id(nota_id: str, sufijo: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"pia3:{nota_id}:{sufijo}"))


def eventos_seguridad(
    nota: NotaRecorrida, detecciones: list[Deteccion]
) -> list[EventoSistema]:
    return [
        EventoSistema(
            id=_id(nota.id, deteccion.categoria),
            ts=nota.ts,
            tipo=TipoEvento.alerta_seguridad,
            origen="parte",
            nota_ids=[nota.id],
            resumen=f"{deteccion.categoria}: {deteccion.evidencia}",
        )
        for deteccion in detecciones
    ]


def mensaje_seguridad(
    nota: NotaRecorrida, detecciones: list[Deteccion]
) -> MensajeTablet:
    procedimientos = " ".join(
        PROCEDIMIENTOS.get(deteccion.categoria, FALLBACK) for deteccion in detecciones
    )
    detalle = "; ".join(
        f"{deteccion.categoria}: {deteccion.evidencia}" for deteccion in detecciones
    )
    return MensajeTablet(
        id=_id(nota.id, "tablet-seguridad"),
        ts=nota.ts,
        nota_ids=[nota.id],
        texto=f"Alerta de seguridad. {procedimientos}",
        pantalla=Pantalla(
            titulo="Alerta de seguridad",
            filas=[
                FilaParte(
                    tag="PLANTA",
                    variable="condicion_insegura",
                    valor=None,
                    observacion=detalle,
                )
            ],
            opciones=[],
        ),
        espera_respuesta=False,
    )
