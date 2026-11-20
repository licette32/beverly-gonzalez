from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from planta_contrato import NotaCierre

from .config import POSTGRES_REINTENTO_S

REINTENTOS_CONEXION = 4
ESPERA_CONEXION_BASE_S = POSTGRES_REINTENTO_S

DDL_TABLA = """
CREATE TABLE IF NOT EXISTS cierres (
    nota_id TEXT PRIMARY KEY,
    estado TEXT NOT NULL,
    nota JSONB NOT NULL,
    parte JSONB,
    diferencias JSONB,
    orden_id TEXT NOT NULL
)
"""

DDL_INDICES = (
    """
    CREATE INDEX IF NOT EXISTS cierres_estado_idx ON cierres (estado)
    """,
    """
    CREATE INDEX IF NOT EXISTS cierres_orden_id_idx ON cierres (orden_id)
    """,
)

SQL_GUARDAR = """
INSERT INTO cierres (nota_id, estado, nota, orden_id)
VALUES (%s, %s, %s::jsonb, %s)
ON CONFLICT (nota_id) DO NOTHING
"""

SQL_MARCAR = """
UPDATE cierres
SET estado = %s, parte = %s::jsonb, diferencias = %s::jsonb
WHERE nota_id = %s
"""

SQL_RECIBIDOS = """
SELECT nota, estado, orden_id, parte, diferencias FROM cierres
WHERE estado = 'recibido'
ORDER BY (nota->>'ts')::timestamptz, nota_id
"""

SQL_POR_ORDEN = """
SELECT nota, estado, orden_id, parte, diferencias FROM cierres
WHERE orden_id = %s
ORDER BY (nota->>'ts')::timestamptz, nota_id
"""

SQL_OBTENER = """
SELECT nota, estado, orden_id, parte, diferencias FROM cierres
WHERE nota_id = %s
"""


class ErrorPersistenciaCierre(Exception):
    def __init__(self, operacion: str, causa: Exception) -> None:
        super().__init__(f"falló {operacion} en Postgres: {causa}")
        self.operacion = operacion
        self.causa = causa


@dataclass(frozen=True)
class FilaCierre:
    nota: NotaCierre
    estado: str
    orden_id: str
    parte: dict[str, Any] | None
    diferencias: list[dict[str, Any]]


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _objeto(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def _fila(fila: tuple[Any, ...]) -> FilaCierre:
    nota = NotaCierre.model_validate(_objeto(fila[0]))
    parte = _objeto(fila[3])
    diferencias = _objeto(fila[4])
    return FilaCierre(
        nota=nota,
        estado=fila[1],
        orden_id=fila[2],
        parte=parte,
        diferencias=diferencias or [],
    )


def _es_tabla_inexistente(exc: Exception) -> bool:
    textos = [str(exc), type(exc).__name__]
    causa = exc.__cause__
    while causa is not None:
        textos.extend([str(causa), type(causa).__name__])
        causa = causa.__cause__
    texto = " ".join(textos).lower()
    return (
        'relation "cierres" does not exist' in texto
        or "undefinedtable" in texto
    )


class RepositorioCierresPostgres:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._conexion: Any = None

    def _abrir_conexion(self) -> Any:
        ultimo: Exception | None = None
        for intento in range(1, REINTENTOS_CONEXION + 1):
            try:
                conexion = self._psycopg().connect(self._dsn, connect_timeout=2)
                self._conexion = conexion
                return conexion
            except Exception as exc:
                ultimo = exc
                if intento < REINTENTOS_CONEXION:
                    time.sleep(ESPERA_CONEXION_BASE_S * 2 ** (intento - 1))
        raise ultimo

    @staticmethod
    def _psycopg() -> Any:
        import psycopg

        return psycopg

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
                if intento == 0 and recrear and _es_tabla_inexistente(exc):
                    try:
                        self._crear_tablas()
                    except Exception:
                        raise ErrorPersistenciaCierre(operacion, exc) from exc
                    continue
                raise ErrorPersistenciaCierre(operacion, exc) from exc
            finally:
                if conexion is not None:
                    try:
                        conexion.close()
                    except Exception:
                        pass
                    self._conexion = None

    def _crear_tablas(self) -> None:
        self._ejecutar("crear tabla cierres", DDL_TABLA, recrear=False)
        for ddl in DDL_INDICES:
            self._ejecutar("crear índice de cierres", ddl, recrear=False)

    def guardar_recibido(self, nota: NotaCierre) -> None:
        self._ejecutar(
            "guardar cierre recibido",
            SQL_GUARDAR,
            (
                nota.id,
                "recibido",
                json.dumps(nota.model_dump(mode="json"), ensure_ascii=False),
                nota.orden_id,
            ),
        )

    def marcar_procesado(
        self,
        nota_id: str,
        parte: dict[str, Any],
        diferencias: list[dict[str, Any]],
    ) -> None:
        self._ejecutar(
            "marcar cierre procesado",
            SQL_MARCAR,
            ("procesado", _json(parte), _json(diferencias), nota_id),
        )

    def marcar_error(
        self,
        nota_id: str,
        parte: dict[str, Any],
        diferencias: list[dict[str, Any]],
    ) -> None:
        self._ejecutar(
            "marcar cierre con error",
            SQL_MARCAR,
            ("error", _json(parte), _json(diferencias), nota_id),
        )

    def cargar_recibidos(self) -> list[FilaCierre]:
        filas = self._ejecutar(
            "cargar cierres recibidos",
            SQL_RECIBIDOS,
            fetch=lambda cursor: cursor.fetchall(),
        )
        return [_fila(fila) for fila in filas]

    def listar_por_orden(self, orden_id: str) -> list[FilaCierre]:
        filas = self._ejecutar(
            "listar cierres de una orden",
            SQL_POR_ORDEN,
            (orden_id,),
            fetch=lambda cursor: cursor.fetchall(),
        )
        return [_fila(fila) for fila in filas]

    def obtener(self, nota_id: str) -> FilaCierre | None:
        fila = self._ejecutar(
            "obtener cierre",
            SQL_OBTENER,
            (nota_id,),
            fetch=lambda cursor: cursor.fetchone(),
        )
        return _fila(fila) if fila is not None else None

    def cerrar(self) -> None:
        if self._conexion is not None:
            try:
                self._conexion.close()
            except Exception:
                pass
            self._conexion = None
