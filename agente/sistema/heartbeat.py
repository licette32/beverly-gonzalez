import json
import logging
import threading
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

from planta_contrato import EstadoSistema, Topicos

from .config import (
    ENLACE_SONDA_INTERVALO_S,
    ENLACE_SONDA_TIMEOUT_S,
    ENLACE_SONDA_URL,
)
from .mqtt import ClienteMQTT

log = logging.getLogger(__name__)


class ColaPendientes:
    def __init__(self, arriba_inicial: bool = True) -> None:
        self._lock = threading.Lock()
        self._arriba = arriba_inicial
        self._ids: set[str] = set()

    @property
    def arriba(self) -> bool:
        with self._lock:
            return self._arriba

    def actualizar_enlace(self, arriba: bool) -> bool:
        with self._lock:
            if arriba == self._arriba:
                return False
            self._arriba = arriba
            if arriba:
                self._ids.clear()
            return arriba

    def agregar(self, identificador: str) -> None:
        with self._lock:
            if not self._arriba:
                self._ids.add(str(identificador))

    def cantidad(self) -> int:
        with self._lock:
            return len(self._ids)

    def ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._ids))


class SondaEnlace(threading.Thread):
    def __init__(
        self,
        url: str = ENLACE_SONDA_URL,
        timeout_s: float = ENLACE_SONDA_TIMEOUT_S,
        intervalo_s: float = ENLACE_SONDA_INTERVALO_S,
        urlopen: Callable[[str, float], Any] | None = None,
        al_cambio: Callable[[bool], None] | None = None,
        arriba_inicial: bool = True,
    ) -> None:
        super().__init__(name="sonda-enlace", daemon=True)
        self._url = url
        self._timeout_s = timeout_s
        self._intervalo_s = intervalo_s
        self._urlopen = urlopen if urlopen is not None else urllib.request.urlopen
        self._al_cambio = al_cambio
        self._arriba = arriba_inicial
        self._detener = threading.Event()

    @property
    def arriba(self) -> bool:
        return self._arriba

    def probar(self) -> bool:
        try:
            with self._urlopen(self._url, timeout=self._timeout_s) as respuesta:
                datos = json.load(respuesta)
                if isinstance(datos, dict) and "arriba" in datos:
                    arriba = bool(datos.get("arriba", True))
                else:
                    arriba = False
        except Exception as exc:
            log.warning("sonda de enlace sin respuesta: %s", exc)
            arriba = False
        if arriba == self._arriba:
            return arriba
        self._arriba = arriba
        if self._al_cambio is not None:
            try:
                self._al_cambio(arriba)
            except Exception:
                log.exception("falló el aviso de cambio de enlace")
        return arriba

    def run(self) -> None:
        while not self._detener.is_set():
            self.probar()
            if self._detener.wait(self._intervalo_s):
                return

    def detener(self) -> None:
        self._detener.set()


class Latido(threading.Thread):
    def __init__(
        self,
        cliente: ClienteMQTT,
        sistema: str,
        intervalo_s: int,
        pendientes: Callable[[], int] | None = None,
        enlace_ok: Callable[[], bool] | None = None,
    ):
        super().__init__(name="latido", daemon=True)
        self._cliente = cliente
        self._sistema = sistema
        self._intervalo_s = intervalo_s
        self._pendientes = pendientes
        self._enlace_ok = enlace_ok
        self._detener = threading.Event()

    def run(self) -> None:
        self._publicar()
        while not self._detener.wait(self._intervalo_s):
            self._publicar()

    def detener(self) -> None:
        self._detener.set()

    def _publicar(self) -> None:
        pendientes = self._valor(self._pendientes, 0, "pendientes")
        enlace_ok = self._valor(self._enlace_ok, True, "enlace")
        estado = EstadoSistema(
            ts=datetime.now(timezone.utc),
            sistema=self._sistema,
            enlace_ok=enlace_ok,
            pendientes_sincronizar=pendientes,
        )
        try:
            self._cliente.publicar(Topicos.ESTADO, estado)
        except Exception:
            log.exception("no se pudo publicar el latido")

    @staticmethod
    def _valor(funcion: Callable[[], Any] | None, defecto: Any, nombre: str) -> Any:
        if funcion is None:
            return defecto
        try:
            return funcion()
        except Exception:
            log.exception("no se pudo consultar %s para el latido", nombre)
            return defecto
