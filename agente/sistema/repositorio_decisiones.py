"""Registro de decisiones y llamadas a herramientas del flujo de órdenes."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from .config import POSTGRES_REINTENTO_S

log = logging.getLogger(__name__)

NAMESPACE = uuid.NAMESPACE_URL
MODELO_REGLAS = "reglas"
MODELO_HUMANO = "humano"
MODELO_WHISPER = "whisper-base-int8"

T = TypeVar("T")


class DecisionRegistrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    correlation_id: str
    tarea: str | None = None
    paso: str
    modelo: str
    herramienta: str | None = None
    argumentos: dict[str, Any] = Field(default_factory=dict)
    tokens: int = 0
    costo_usd: float = 0.0
    duracion_ms: int = 0
    creado_ts: datetime


class RegistroDecisiones(Protocol):
    def registrar(
        self,
        *,
        correlation_id: str,
        paso: str,
        tarea: str | None = None,
        modelo: str = MODELO_REGLAS,
        herramienta: str | None = None,
        argumentos: Mapping[str, Any] | None = None,
        tokens: int = 0,
        costo_usd: float = 0.0,
        duracion_ms: int = 0,
    ) -> None: ...

    def listar(self, correlation_id: str) -> Sequence[DecisionRegistrada]: ...


class _BaseDecisiones:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._secuencias: dict[tuple[str, str], int] = {}
        self._ultimos: dict[str, datetime] = {}

    def _clave(
        self, correlation_id: str, paso: str
    ) -> tuple[str, str, int, datetime]:
        with self._lock:
            clave = (correlation_id, paso)
            secuencia = self._secuencias.get(clave, 0) + 1
            self._secuencias[clave] = secuencia
            creado_ts = datetime.now(timezone.utc)
            ultimo = self._ultimos.get(correlation_id)
            if ultimo is not None and creado_ts <= ultimo:
                creado_ts = ultimo + timedelta(microseconds=1)
            self._ultimos[correlation_id] = creado_ts
        id_decision = str(
            uuid.uuid5(
                NAMESPACE,
                f"pia3:decision:{correlation_id}:{paso}:{secuencia}:"
                f"{creado_ts.isoformat()}",
            )
        )
        return id_decision, correlation_id, secuencia, creado_ts


class RegistroDecisionesMemoria(_BaseDecisiones):
    def __init__(self) -> None:
        super().__init__()
        self._filas: list[DecisionRegistrada] = []

    def registrar(
        self,
        *,
        correlation_id: str,
        paso: str,
        tarea: str | None = None,
        modelo: str = MODELO_REGLAS,
        herramienta: str | None = None,
        argumentos: Mapping[str, Any] | None = None,
        tokens: int = 0,
        costo_usd: float = 0.0,
        duracion_ms: int = 0,
    ) -> None:
        id_decision, correlation_id, _, creado_ts = self._clave(correlation_id, paso)
        self._filas.append(
            DecisionRegistrada(
                id=id_decision,
                correlation_id=correlation_id,
                tarea=tarea,
                paso=paso,
                modelo=modelo,
                herramienta=herramienta,
                argumentos=dict(argumentos or {}),
                tokens=tokens,
                costo_usd=costo_usd,
                duracion_ms=duracion_ms,
                creado_ts=creado_ts,
            )
        )

    def listar(self, correlation_id: str) -> list[DecisionRegistrada]:
        filas = [
            fila for fila in self._filas if fila.correlation_id == correlation_id
        ]
        return sorted(filas, key=lambda fila: (fila.creado_ts, fila.id))


DDL_TABLA = """
CREATE TABLE IF NOT EXISTS decisiones (
    id TEXT PRIMARY KEY,
    correlation_id TEXT NOT NULL,
    tarea TEXT,
    paso TEXT NOT NULL,
    modelo TEXT NOT NULL,
    herramienta TEXT,
    argumentos JSONB NOT NULL DEFAULT '{}'::jsonb,
    tokens INTEGER NOT NULL DEFAULT 0,
    costo_usd NUMERIC(12,6) NOT NULL DEFAULT 0,
    duracion_ms INTEGER NOT NULL,
    creado_ts TIMESTAMPTZ NOT NULL
)
"""

DDL_INDICES = (
    """
    CREATE INDEX IF NOT EXISTS decisiones_correlation_creado_idx
    ON decisiones (correlation_id, creado_ts)
    """,
)

SQL_GUARDAR = """
INSERT INTO decisiones
    (id, correlation_id, tarea, paso, modelo, herramienta, argumentos,
     tokens, costo_usd, duracion_ms, creado_ts)
VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
ON CONFLICT (id) DO NOTHING
"""

SQL_LISTAR = """
SELECT id, correlation_id, tarea, paso, modelo, herramienta, argumentos,
       tokens, costo_usd, duracion_ms, creado_ts
FROM decisiones
WHERE correlation_id = %s
ORDER BY creado_ts, id
"""

REINTENTOS_CONEXION = 4
REINTENTOS_CONEXION_REGISTRO = 1
TIMEOUT_CONEXION_S = 2
TIMEOUT_CONEXION_REGISTRO_S = 1
ESPERA_CONEXION_BASE_S = POSTGRES_REINTENTO_S


class ErrorPersistenciaDecision(Exception):
    def __init__(self, operacion: str, causa: Exception) -> None:
        super().__init__(f"falló {operacion} en Postgres: {causa}")
        self.operacion = operacion
        self.causa = causa


class RepositorioDecisionesPostgres(_BaseDecisiones):
    def __init__(self, dsn: str) -> None:
        super().__init__()
        self._dsn = dsn

    @staticmethod
    def _psycopg() -> Any:
        import psycopg

        return psycopg

    def _abrir_conexion(
        self,
        *,
        reintentos: int = REINTENTOS_CONEXION,
        timeout_s: int = TIMEOUT_CONEXION_S,
    ) -> Any:
        ultimo: Exception | None = None
        for intento in range(1, reintentos + 1):
            try:
                return self._psycopg().connect(self._dsn, connect_timeout=timeout_s)
            except Exception as exc:
                ultimo = exc
                if intento < reintentos:
                    time.sleep(ESPERA_CONEXION_BASE_S * 2 ** (intento - 1))
        raise ultimo

    @staticmethod
    def _es_tabla_inexistente(exc: Exception) -> bool:
        textos = [str(exc), type(exc).__name__]
        causa = exc.__cause__
        while causa is not None:
            textos.extend([str(causa), type(causa).__name__])
            causa = causa.__cause__
        texto = " ".join(textos).lower()
        return (
            'relation "decisiones" does not exist' in texto
            or "undefinedtable" in texto
        )

    def _ejecutar(
        self,
        operacion: str,
        sql: str,
        params: tuple[Any, ...] | None = None,
        *,
        fetch: Callable[[Any], Any] | None = None,
        recrear: bool = True,
        reintentos_conexion: int = REINTENTOS_CONEXION,
        timeout_s: int = TIMEOUT_CONEXION_S,
    ) -> Any:
        for intento in range(2):
            conexion = None
            try:
                conexion = self._abrir_conexion(
                    reintentos=reintentos_conexion, timeout_s=timeout_s
                )
                with conexion.cursor() as cursor:
                    cursor.execute(sql, params)
                    resultado = fetch(cursor) if fetch is not None else None
                conexion.commit()
                return resultado
            except Exception as exc:
                if conexion is not None:
                    try:
                        conexion.rollback()
                    except Exception:
                        pass
                if intento == 0 and recrear and self._es_tabla_inexistente(exc):
                    try:
                        self._crear_tablas(
                            reintentos_conexion=reintentos_conexion,
                            timeout_s=timeout_s,
                        )
                    except Exception:
                        raise ErrorPersistenciaDecision(operacion, exc) from exc
                    continue
                raise ErrorPersistenciaDecision(operacion, exc) from exc
            finally:
                if conexion is not None:
                    try:
                        conexion.close()
                    except Exception:
                        pass

    def _crear_tablas(
        self,
        *,
        reintentos_conexion: int = REINTENTOS_CONEXION,
        timeout_s: int = TIMEOUT_CONEXION_S,
    ) -> None:
        self._ejecutar(
            "crear tabla decisiones",
            DDL_TABLA,
            recrear=False,
            reintentos_conexion=reintentos_conexion,
            timeout_s=timeout_s,
        )
        for ddl in DDL_INDICES:
            self._ejecutar(
                "crear índice de decisiones",
                ddl,
                recrear=False,
                reintentos_conexion=reintentos_conexion,
                timeout_s=timeout_s,
            )

    def registrar(
        self,
        *,
        correlation_id: str,
        paso: str,
        tarea: str | None = None,
        modelo: str = MODELO_REGLAS,
        herramienta: str | None = None,
        argumentos: Mapping[str, Any] | None = None,
        tokens: int = 0,
        costo_usd: float = 0.0,
        duracion_ms: int = 0,
    ) -> None:
        id_decision, correlation_id, _, creado_ts = self._clave(correlation_id, paso)
        try:
            self._ejecutar(
                "guardar decisión",
                SQL_GUARDAR,
                (
                    id_decision,
                    correlation_id,
                    tarea,
                    paso,
                    modelo,
                    herramienta,
                    json.dumps(dict(argumentos or {}), ensure_ascii=False),
                    tokens,
                    costo_usd,
                    duracion_ms,
                    creado_ts,
                ),
                reintentos_conexion=REINTENTOS_CONEXION_REGISTRO,
                timeout_s=TIMEOUT_CONEXION_REGISTRO_S,
            )
        except Exception:
            log.exception("no se pudo guardar la decisión %s", paso)

    def listar(self, correlation_id: str) -> list[DecisionRegistrada]:
        filas = self._ejecutar(
            "listar decisiones",
            SQL_LISTAR,
            (correlation_id,),
            fetch=lambda cursor: cursor.fetchall(),
        )
        return [DecisionRegistrada.model_validate(fila) for fila in filas]


def argumentos_permitidos(
    valores: Mapping[str, Any], claves: Sequence[str]
) -> dict[str, Any]:
    return {
        clave: valores[clave]
        for clave in claves
        if clave in valores and valores[clave] is not None
    }


def argumentos_historian(
    tag: str, variable: str, desde: str | None = None, hasta: str | None = None
) -> dict[str, Any]:
    return argumentos_permitidos(
        {"tag": tag, "variable": variable, "desde": desde, "hasta": hasta},
        ("tag", "variable", "desde", "hasta"),
    )


def argumentos_catalogo(tag: str | None = None) -> dict[str, Any]:
    return argumentos_permitidos({"tag": tag}, ("tag",))


def argumentos_stock(tag: str | None = None) -> dict[str, Any]:
    return argumentos_permitidos({"tag": tag}, ("tag",))


def argumentos_historial_ordenes(
    equipo: str, orden_id: str | None = None
) -> dict[str, Any]:
    return argumentos_permitidos(
        {"equipo": equipo, "orden_id": orden_id}, ("equipo", "orden_id")
    )


def argumentos_manuales_buscar(texto: str) -> dict[str, Any]:
    return {
        "len_texto": len(texto),
        "sha256": hashlib.sha256(texto.encode("utf-8")).hexdigest()[:12],
    }


def correlation_de_orden(orden: Any) -> str:
    evento_ids = getattr(orden, "evento_ids", ())
    return evento_ids[0] if evento_ids else orden.id


def registrar_directo(
    registro: RegistroDecisiones | None,
    *,
    correlation_id: str,
    paso: str,
    tarea: str | None = None,
    modelo: str = MODELO_REGLAS,
    herramienta: str | None = None,
    argumentos: Mapping[str, Any] | None = None,
    tokens: int = 0,
    costo_usd: float = 0.0,
    duracion_ms: int = 0,
) -> None:
    if registro is None:
        return
    try:
        registro.registrar(
            correlation_id=correlation_id,
            paso=paso,
            tarea=tarea,
            modelo=modelo,
            herramienta=herramienta,
            argumentos=argumentos,
            tokens=tokens,
            costo_usd=costo_usd,
            duracion_ms=duracion_ms,
        )
    except Exception:
        log.exception("no se pudo registrar la decisión %s", paso)


def medir_y_registrar(
    registro: RegistroDecisiones | None,
    correlation_id: str,
    paso: str,
    fn: Callable[..., T],
    *args: Any,
    tarea: str | None = None,
    modelo: str = MODELO_REGLAS,
    herramienta: str | None = None,
    argumentos: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> T:
    inicio = time.perf_counter()
    try:
        return fn(*args, **kwargs)
    finally:
        duracion_ms = max(0, int((time.perf_counter() - inicio) * 1000))
        registrar_directo(
            registro,
            correlation_id=correlation_id,
            paso=paso,
            tarea=tarea,
            modelo=modelo,
            herramienta=herramienta,
            argumentos=argumentos,
            duracion_ms=duracion_ms,
        )


def registrar_herramienta(
    registro: RegistroDecisiones | None,
    correlation_id: str,
    nombre: str,
    argumentos: Mapping[str, Any],
    fn: Callable[..., T],
    *args: Any,
    **kwargs: Any,
) -> T:
    return medir_y_registrar(
        registro,
        correlation_id,
        nombre,
        fn,
        *args,
        herramienta=nombre,
        argumentos=argumentos,
        **kwargs,
    )


def registrar_manuales_buscar(
    registro: RegistroDecisiones | None,
    correlation_id: str,
    texto: str,
    buscar: Callable[..., T],
    *args: Any,
    **kwargs: Any,
) -> T:
    return registrar_herramienta(
        registro,
        correlation_id,
        "manuales_buscar",
        argumentos_manuales_buscar(texto),
        buscar,
        texto,
        *args,
        **kwargs,
    )
