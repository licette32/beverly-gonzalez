import logging
import threading
from datetime import datetime, timezone

from planta_contrato import EstadoSistema, Topicos

from .mqtt import ClienteMQTT

log = logging.getLogger(__name__)


class Latido(threading.Thread):
    def __init__(
        self,
        cliente: ClienteMQTT,
        sistema: str,
        intervalo_s: int,
        pendientes=None,
    ):
        super().__init__(name="latido", daemon=True)
        self._cliente = cliente
        self._sistema = sistema
        self._intervalo_s = intervalo_s
        self._pendientes = pendientes
        self._detener = threading.Event()

    def run(self) -> None:
        self._publicar()
        while not self._detener.wait(self._intervalo_s):
            self._publicar()

    def detener(self) -> None:
        self._detener.set()

    def _publicar(self) -> None:
        pendientes = self._pendientes() if self._pendientes is not None else 0
        estado = EstadoSistema(
            ts=datetime.now(timezone.utc),
            sistema=self._sistema,
            enlace_ok=True,
            pendientes_sincronizar=pendientes,
        )
        try:
            self._cliente.publicar(Topicos.ESTADO, estado)
        except Exception:
            log.exception("no se pudo publicar el latido")
