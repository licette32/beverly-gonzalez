import uuid

NAMESPACE = uuid.NAMESPACE_URL


def id_tablet(nota_id: str, proposito: str, intento: int = 0, secuencia: int = 0) -> str:
    clave = f"pia3:{nota_id}:tablet:{proposito}:{intento}:{secuencia}"
    return str(uuid.uuid5(NAMESPACE, clave))


def id_evento(nota_id: str, sufijo: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"pia3:{nota_id}:{sufijo}"))
