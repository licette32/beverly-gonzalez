import logging
import time

from planta_contrato import Topicos

from .config import HEARTBEAT_S, LOG_LEVEL, MQTT_HOST, MQTT_PORT, SISTEMA
from .heartbeat import Latido
from .mqtt import ClienteMQTT

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

    cliente = ClienteMQTT(MQTT_HOST, MQTT_PORT, SISTEMA)
    cliente.conectar()
    cliente.suscribir(TOPICOS)

    latido = Latido(cliente, SISTEMA, HEARTBEAT_S)
    latido.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        latido.detener()
        latido.join(timeout=2)
        cliente.cerrar()


if __name__ == "__main__":
    main()
