"""Limites de control de la Entrega 1.

Sin LLM en el camino critico no hay tokens ni costo que limitar: se limitan el
tiempo y las rondas. Al llegar a un limite el agente avisa a la tablet y se
detiene. Nunca publica SinNovedad ni ningun evento de planta como si la nota se
hubiera procesado.
"""
from __future__ import annotations

import uuid

from planta_contrato import MensajeTablet, NotaRecorrida

from .config import MAX_CORRECCIONES, TRANSCRIPCION_LIMITE_S

LIMITE_TRANSCRIPCION_S = TRANSCRIPCION_LIMITE_S

TEXTOS = {
    "descarga": "No pude descargar el audio de esta nota. Revisala a mano.",
    "transcripcion": "No pude transcribir esta nota. Revisala a mano.",
    "correcciones": (
        "Llegamos al máximo de correcciones para esta nota. Revisá el parte a mano."
    ),
}


def mensaje_corte(nota: NotaRecorrida, motivo: str) -> MensajeTablet:
    return MensajeTablet(
        id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"pia3:corte:{motivo}:{nota.id}")),
        ts=nota.ts,
        nota_ids=[nota.id],
        texto=TEXTOS[motivo],
        pantalla=None,
        espera_respuesta=False,
    )
