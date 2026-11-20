"""Persistencia síncrona de órdenes en Postgres, aislada del flujo de publicación."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable

from planta_contrato import EstadoOrden, OrdenSistema

from .config import POSTGRES_REINTENTO_S

REINTENTOS_CONEXION = 4
ESPERA_CONEXION_BASE_S = POSTGRES_REINTENTO_S

DDL_TABLA = """
CREATE TABLE IF NOT EXISTS ordenes (
    id TEXT PRIMARY KEY,
    correlation_id TEXT NOT NULL,
    estado TEXT NOT NULL,
    payload JSONB NOT NULL,
    actualizado_ts TIMESTAMPTZ NOT NULL
)
"""

DDL_INDICES = (
    """
    CREATE INDEX IF NOT EXISTS ordenes_estado_idx ON ordenes (estado)
    """,
    """
    CREATE INDEX IF NOT EXISTS ordenes_correlation_id_idx ON ordenes (correlation_id)
    """,
)

SQL_GUARDAR = """
INSERT INTO ordenes (id, correlation_id, estado, payload, actualizado_ts)
VALUES (%s, %s, %s, %s::jsonb, %s)
ON CONFLICT (id) DO UPDATE SET
    correlation_id = EXCLUDED.correlation_id,
    estado = EXCLUDED.estado,
    payload = EXCLUDED.payload,
    actualizado_ts = EXCLUDED.actualizado_ts
"""

SQL_GUARDAR_SI_ESTADO = """
UPDATE ordenes
SET correlation_id = %s, estado = %s, payload = %s::jsonb, actualizado_ts = %s
WHERE id = %s AND estado = %s
"""

SQL_OBTENER = """
SELECT payload FROM ordenes WHERE id = %s
"""

SQL_PENDIENTES = """
SELECT payload FROM ordenes
WHERE estado IN (%s, %s)
ORDER BY (payload->>'ts')::timestamptz, id
"""

ESTADOS_ABIERTOS = (
    EstadoOrden.pendiente,
    EstadoOrden.aprobada,
    EstadoOrden.ejecutada,
    EstadoOrden.observada,
)

SQL_ABIERTAS = """
SELECT payload FROM ordenes
WHERE estado IN (%s, %s, %s, %s) AND payload->>'equipo' = %s
ORDER BY (payload->>'ts')::timestamptz, id
"""


class ErrorPersistenciaOrden(Exception):
    def __init__(self, operacion: str, causa: Exception) -> None:
        super().__init__(f"falló {operacion} en Postgres: {causa}")
        self.operacion = operacion
        self.causa = causa


def _psycopg() -> Any:
    import psycopg

    return psycopg


def _orden_desde_payload(payload: Any) -> OrdenSistema:
    if isinstance(payload, str):
        payload = json.loads(payload)
    return OrdenSistema.model_validate(payload)


def _es_tabla_ordenes_inexistente(exc: Exception) -> bool:
    textos = [str(exc), type(exc).__name__]
    causa = exc.__cause__
    while causa is not None:
        textos.extend([str(causa), type(causa).__name__])
        causa = causa.__cause__
    texto = " ".join(textos).lower()
    return (
        'relation "ordenes" does not exist' in texto
        or "undefinedtable" in texto
    )


class RepositorioOrdenesPostgres:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._conexion: Any = None

    def _abrir_conexion(self) -> Any:
        ultimo: Exception | None = None
        for intento in range(1, REINTENTOS_CONEXION + 1):
            try:
                conexion = _psycopg().connect(self._dsn, connect_timeout=2)
                self._conexion = conexion
                return conexion
            except Exception as exc:
                ultimo = exc
                if intento < REINTENTOS_CONEXION:
                    time.sleep(ESPERA_CONEXION_BASE_S * 2 ** (intento - 1))
        raise ultimo

    def _ejecutar(
        self,
        operacion: str,
        sql: str,
        params: tuple[Any, ...] | None = None,
        *,
        fetch: Callable[[Any], Any] | None = None,
        recrear: bool = True,
    ) -> Any:
        for intento in range(2):
            conexion = None
            try:
                conexion = self._abrir_conexion()
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
                if intento == 0 and recrear and _es_tabla_ordenes_inexistente(exc):
                    try:
                        self._crear_tablas()
                    except Exception:
                        raise ErrorPersistenciaOrden(operacion, exc) from exc
                    continue
                raise ErrorPersistenciaOrden(operacion, exc) from exc
            finally:
                if conexion is not None:
                    try:
                        conexion.close()
                    except Exception:
                        pass

    def _crear_tablas(self) -> None:
        self._ejecutar("crear tabla ordenes", DDL_TABLA, recrear=False)
        for ddl in DDL_INDICES:
            self._ejecutar("crear índice de ordenes", ddl, recrear=False)

    def guardar(self, orden: OrdenSistema) -> None:
        payload = orden.model_dump(mode="json")
        correlation_id = orden.evento_ids[0] if orden.evento_ids else orden.id
        self._ejecutar(
            "guardar orden",
            SQL_GUARDAR,
            (
                orden.id,
                correlation_id,
                orden.estado.value,
                json.dumps(payload, ensure_ascii=False),
                datetime.now(timezone.utc),
            ),
        )

    def guardar_si_estado(
        self, orden: OrdenSistema, estado_esperado: EstadoOrden
    ) -> bool:
        payload = orden.model_dump(mode="json")
        correlation_id = orden.evento_ids[0] if orden.evento_ids else orden.id
        filas = self._ejecutar(
            "guardar orden condicionado a estado",
            SQL_GUARDAR_SI_ESTADO,
            (
                correlation_id,
                orden.estado.value,
                json.dumps(payload, ensure_ascii=False),
                datetime.now(timezone.utc),
                orden.id,
                estado_esperado.value,
            ),
            fetch=lambda cursor: cursor.rowcount,
        )
        return filas == 1

    def obtener(self, orden_id: str) -> OrdenSistema | None:
        fila = self._ejecutar(
            "obtener orden",
            SQL_OBTENER,
            (orden_id,),
            fetch=lambda cursor: cursor.fetchone(),
        )
        return _orden_desde_payload(fila[0]) if fila is not None else None

    def cargar_pendientes(self) -> list[OrdenSistema]:
        filas = self._ejecutar(
            "cargar órdenes pendientes",
            SQL_PENDIENTES,
            (EstadoOrden.pendiente.value, EstadoOrden.borrador.value),
            fetch=lambda cursor: cursor.fetchall(),
        )
        return [_orden_desde_payload(fila[0]) for fila in filas]

    def ordenes_abiertas(self, equipo: str) -> list[OrdenSistema]:
        filas = self._ejecutar(
            "cargar órdenes abiertas del equipo",
            SQL_ABIERTAS,
            (*(estado.value for estado in ESTADOS_ABIERTOS), equipo),
            fetch=lambda cursor: cursor.fetchall(),
        )
        return [_orden_desde_payload(fila[0]) for fila in filas]

    def cerrar(self) -> None:
        if self._conexion is not None:
            try:
                self._conexion.close()
            except Exception:
                pass
            self._conexion = None
