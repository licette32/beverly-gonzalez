"""Persistencia síncrona de órdenes en Postgres, aislada del flujo de publicación."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable

from planta_contrato import EstadoOrden, OrdenSistema

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


class RepositorioOrdenesPostgres:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._conexion: Any = None
        self._crear_tablas()

    def _abrir_conexion(self) -> Any:
        conexion = _psycopg().connect(self._dsn, connect_timeout=2)
        self._conexion = conexion
        return conexion

    def _ejecutar(
        self,
        operacion: str,
        sql: str,
        params: tuple[Any, ...] | None = None,
        *,
        fetch: Callable[[Any], Any] | None = None,
    ) -> Any:
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
            raise ErrorPersistenciaOrden(operacion, exc) from exc
        finally:
            if conexion is not None:
                try:
                    conexion.close()
                except Exception:
                    pass

    def _crear_tablas(self) -> None:
        self._ejecutar("crear tabla ordenes", DDL_TABLA)
        for ddl in DDL_INDICES:
            self._ejecutar("crear índice de ordenes", ddl)

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

    def cerrar(self) -> None:
        if self._conexion is not None:
            try:
                self._conexion.close()
            except Exception:
                pass
            self._conexion = None
