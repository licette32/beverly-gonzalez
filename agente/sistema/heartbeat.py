import logging
import threading
from datetime import datetime, timezone

from planta_contrato import EstadoSistema, Topicos

from .mqtt import ClienteMQTT

log = logging.getLogger(__name__)


class Latido(threading.Thread):
    def __init__(self, cliente: ClienteMQTT, sistema: str, intervalo_s: int):
        super().__init__(name="latido", daemon=True)
        self._cliente = cliente
        self._sistema = sistema
        self._intervalo_s = intervalo_s
        self._detener = threading.Event()

    def run(self) -> None:
        self._publicar()
        while not self._detener.wait(self._intervalo_s):
            self._publicar()

    def detener(self) -> None:
        self._detener.set()

    def _publicar(self) -> None:
        estado = EstadoSistema(
            ts=datetime.now(timezone.utc),
            sistema=self._sistema,
            enlace_ok=True,
            pendientes_sincronizar=0,
        )
        try:
            self._cliente.publicar(Topicos.ESTADO, estado)
        except Exception:
            log.exception("no se pudo publicar el latido")
