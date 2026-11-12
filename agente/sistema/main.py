import logging
import time

from planta_contrato import Topicos

from .catalogo import CatalogoPlanta
from .config import (
    HEARTBEAT_S,
    LOG_LEVEL,
    MQTT_HOST,
    MQTT_PORT,
    POSTGRES_DSN,
    SISTEMA,
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
