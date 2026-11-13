import logging
import os
import subprocess
import sys
import time

from planta_contrato import Topicos

from .catalogo import CatalogoPlanta
from .config import (
    HEARTBEAT_S,
    LOG_LEVEL,
    MQTT_HOST,
    MQTT_PORT,
    PLANTA_BASE_URL,
    POSTGRES_DSN,
    SISTEMA,
    INDEXAR_PG_AL_ARRANCAR,
)
from .coordinador import CoordinadorPartes
from .heartbeat import Latido
from .mqtt import ClienteMQTT
from .repositorio import crear_repositorio
from .transcripcion import Transcriptor
from .worker import WorkerNotas

TOPICOS = [
    Topicos.RECORRIDAS,
    Topicos.CIERRES,
    Topicos.ENERGIA,
    Topicos.RESPUESTAS,
    "planta/sensores/+/+",
]


def _lanzar_indexado() -> None:
    """Lanza el indexado como proceso separado; si falla, loguea y sigue."""
    try:
        cmd = [sys.executable, "-m", "sistema.indexar"]
        log = logging.getLogger(__name__)
        log.info("Lanzando indexado pgvector: %s", " ".join(cmd))
        proc = subprocess.Popen(
            cmd,
            stdout=log.handlers[0].stream if log.handlers else sys.stdout,
            stderr=sys.stderr,
            preexec_fn=lambda: os.nice(19),
        )
        log.info("Indexado lanzado en PID %d (continuarÃ© sin esperar)", proc.pid)
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "No se pudo lanzar el indexado: %s", exc
        )


def main() -> None:
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    transcriptor = Transcriptor()
    cliente = ClienteMQTT(MQTT_HOST, MQTT_PORT, SISTEMA)
    repositorio = crear_repositorio(POSTGRES_DSN)
    catalogo = CatalogoPlanta()
    coordinador = CoordinadorPartes(cliente, repositorio, catalogo)
    worker = WorkerNotas(cliente, transcriptor, coordinador)
    cliente.al_recibir_nota = worker.encolar
    cliente.al_recibir_respuesta = coordinador.encolar_respuesta

    # Primero se reciben y descargan las notas y el latido queda vivo; la
    # transcripción espera a que el modelo esté listo. Así no se pierde una nota
    # si la carga tarda. Postgres se conecta después, en segundo plano.
    cliente.conectar()
    worker.start()
    coordinador.iniciar()
    cliente.suscribir(TOPICOS)

    latido = Latido(
        cliente,
        SISTEMA,
        HEARTBEAT_S,
        pendientes=repositorio.pendientes_sincronizar,
    )
    latido.start()

    try:
        repositorio.iniciar()
        _lanzar_indexado()
        catalogo.refrescar()
        transcriptor.precargar()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        latido.detener()
        latido.join(timeout=2)
        coordinador.detener()
        repositorio.detener()
        worker.detener()
        worker.join(timeout=35)
        cliente.cerrar()


if __name__ == "__main__":
    main()
