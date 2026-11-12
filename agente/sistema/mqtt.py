import json
import logging
import time
import uuid
from collections.abc import Callable

from paho.mqtt import client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from planta_contrato import (
    EstadoEnergia,
    LecturaSensor,
    NotaCierre,
    NotaRecorrida,
    RespuestaOperador,
    Topicos,
)
from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

MODELOS = {
    Topicos.RECORRIDAS: NotaRecorrida,
    Topicos.CIERRES: NotaCierre,
    Topicos.ENERGIA: EstadoEnergia,
    Topicos.RESPUESTAS: RespuestaOperador,
}


class ClienteMQTT:
    def __init__(self, host: str, port: int, sistema: str):
        self._host = host
        self._port = port
        self._client = mqtt.Client(
            CallbackAPIVersion.VERSION2,
            client_id=f"{sistema}-{uuid.uuid4().hex[:8]}",
        )
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self.al_recibir_nota: Callable[[NotaRecorrida], None] | None = None
        self.al_recibir_respuesta: Callable[[RespuestaOperador], None] | None = None

    def conectar(self, intentos: int = 30, espera_s: float = 2.0) -> None:
        for intento in range(1, intentos + 1):
            try:
                self._client.connect(self._host, self._port, keepalive=60)
                self._client.loop_start()
                log.info("conectado a MQTT %s:%s", self._host, self._port)
                return
            except OSError:
                log.warning("MQTT no disponible (%s/%s)", intento, intentos)
                time.sleep(espera_s)
        raise RuntimeError(f"No se pudo conectar a MQTT {self._host}:{self._port}")

    def suscribir(self, topicos: list[str]) -> None:
        for topico in topicos:
            self._client.subscribe(topico, qos=1)
            log.info("suscrito a %s", topico)

    def publicar(self, topico: str, modelo: BaseModel) -> None:
        valido = type(modelo).model_validate(modelo.model_dump(mode="json"))
        payload = json.dumps(valido.model_dump(mode="json"), ensure_ascii=False)
        info = self._client.publish(topico, payload, qos=1, retain=False)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"falló la publicación en {topico}: {info.rc}")

    def cerrar(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code != 0:
            log.error("conexión MQTT rechazada: %s", reason_code)
            return
        log.info("conexión MQTT establecida")

    def _on_message(self, client, userdata, msg) -> None:
        if msg.topic.startswith("planta/sensores/"):
            modelo = LecturaSensor
        else:
            modelo = MODELOS.get(msg.topic)
        if modelo is None:
            return
        try:
            datos = modelo.model_validate_json(msg.payload)
        except ValidationError as exc:
            log.error("mensaje inválido en %s: %s", msg.topic, exc)
            return
        if not msg.topic.startswith("planta/sensores/"):
            log.info("mensaje válido en %s", msg.topic)
        if msg.topic == Topicos.RECORRIDAS and self.al_recibir_nota is not None:
            try:
                self.al_recibir_nota(datos)
            except Exception:
                log.exception("no se pudo encolar la nota")
        elif msg.topic == Topicos.RESPUESTAS and self.al_recibir_respuesta is not None:
            try:
                self.al_recibir_respuesta(datos)
            except Exception:
                log.exception("no se pudo encolar la respuesta")
