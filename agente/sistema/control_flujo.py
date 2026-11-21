from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .config import FLUJO_LIMITE_S, UMBRAL_LOOP_PASOS
from .repositorio_decisiones import (
    MODELO_CONTROL,
    RegistroDecisiones,
    registrar_directo,
)

PASOS_CONTROL = frozenset({"deadline", "loop", "tool_timeout"})


def _clave(paso: str, herramienta: str | None, argumentos: Mapping[str, Any] | None) -> str:
    datos = {
        "paso": paso,
        "herramienta": herramienta or "",
        "argumentos": dict(argumentos or {}),
    }
    return json.dumps(datos, ensure_ascii=False, sort_keys=True)


@dataclass
class ControlProceso:
    correlation_id: str
    registro: RegistroDecisiones | None = None
    limite_s: float = FLUJO_LIMITE_S
    umbral: int = UMBRAL_LOOP_PASOS
    inicio: float = field(default_factory=time.monotonic)
    reloj: Callable[[], float] = time.monotonic
    deadline_registrado: bool = False
    loop_registrado: bool = False
    motivos_pendientes: tuple[str, ...] = ()

    def transcurrido_s(self) -> float:
        return max(0.0, self.reloj() - self.inicio)

    def verificar(self, etapa: str) -> bool:
        if self.deadline_registrado:
            return True
        transcurrido = self.transcurrido_s()
        if transcurrido < self.limite_s:
            return False
        self.deadline_registrado = True
        self.motivos_pendientes = tuple(dict.fromkeys((*self.motivos_pendientes, "LIMITE_TIEMPO")))
        registrar_directo(
            self.registro,
            correlation_id=self.correlation_id,
            paso="deadline",
            modelo=MODELO_CONTROL,
            argumentos={
                "limite_s": self.limite_s,
                "transcurrido_s": round(transcurrido, 3),
                "etapa": etapa,
            },
            duracion_ms=max(0, int(transcurrido * 1000)),
        )
        return True

    def detectar_loop(
        self,
        paso: str,
        herramienta: str | None = None,
        argumentos: Mapping[str, Any] | None = None,
    ) -> bool:
        if self.loop_registrado or self.registro is None:
            return self.loop_registrado
        clave = _clave(paso, herramienta, argumentos)
        try:
            filas = self.registro.listar(self.correlation_id)
        except Exception:
            return False
        repeticiones = sum(
            1
            for fila in filas
            if fila.paso not in PASOS_CONTROL
            and _clave(fila.paso, fila.herramienta, fila.argumentos) == clave
        )
        if repeticiones < self.umbral:
            return False
        self.loop_registrado = True
        self.motivos_pendientes = tuple(dict.fromkeys((*self.motivos_pendientes, "LOOP_DETECTADO")))
        registrar_directo(
            self.registro,
            correlation_id=self.correlation_id,
            paso="loop",
            modelo=MODELO_CONTROL,
            argumentos={"clave": clave, "repeticiones": repeticiones},
        )
        return True

    @property
    def motivo_control(self) -> str | None:
        if self.deadline_registrado:
            return "LIMITE_TIEMPO"
        if self.loop_registrado:
            return "LOOP_DETECTADO"
        return None
