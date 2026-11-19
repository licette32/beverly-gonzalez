import logging
import threading
from collections import deque
from datetime import timedelta

from planta_contrato import LecturaSensor

log = logging.getLogger(__name__)


class VentanaSensores:
    def __init__(self, horizonte_horas: float, max_lecturas: int) -> None:
        if horizonte_horas <= 0:
            raise ValueError("horizonte_horas debe ser positivo")
        if max_lecturas <= 0:
            raise ValueError("max_lecturas debe ser positivo")
        self._horizonte = timedelta(hours=horizonte_horas)
        self._max_lecturas = max_lecturas
        self._lock = threading.Lock()
        self._ventanas: dict[tuple[str, str], deque[LecturaSensor]] = {}

    def registrar(self, lectura: LecturaSensor) -> None:
        clave = (lectura.tag, lectura.variable)
        with self._lock:
            ventana = self._ventanas.get(clave)
            if ventana is None:
                ventana = deque(maxlen=self._max_lecturas)
                self._ventanas[clave] = ventana
            elif ventana and lectura.ts < ventana[-1].ts:
                log.debug(
                    "lectura fuera de orden descartada en %s/%s: %s anterior a %s",
                    lectura.tag,
                    lectura.variable,
                    lectura.ts,
                    ventana[-1].ts,
                )
                return
            ventana.append(lectura)
            limite = lectura.ts - self._horizonte
            while ventana and ventana[0].ts < limite:
                ventana.popleft()

    def ventana(self, tag: str, variable: str) -> tuple[LecturaSensor, ...]:
        with self._lock:
            return tuple(self._ventanas.get((tag, variable), ()))

    def claves(self) -> list[tuple[str, str]]:
        with self._lock:
            return sorted(self._ventanas)
