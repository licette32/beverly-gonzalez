from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from planta_contrato import FilaParte, MensajeTablet, NotaRecorrida, RespuestaOperador

from .config import POSTGRES_REINTENTO_S
from .parte import ItemParte

log = logging.getLogger(__name__)


@dataclass
class EstadoNota:
    nota_id: str
    mensaje: MensajeTablet
    nota: NotaRecorrida
    borrador: list[FilaParte]
    items: list[ItemParte]
    texto: str
    intento: int = 0
    estado: str = "BORRADOR"
    pregunta: MensajeTablet | None = None
    actualizado_ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _estado_json(estado: EstadoNota) -> dict[str, Any]:
    return {
        "nota_id": estado.nota_id,
        "mensaje": estado.mensaje.model_dump(mode="json"),
        "nota": estado.nota.model_dump(mode="json"),
        "borrador": [fila.model_dump(mode="json") for fila in estado.borrador],
        "items": [
            {
                "tag": item.tag,
                "variable": item.variable,
                "valor": item.valor,
                "unidad": item.unidad,
                "observacion": item.observacion,
                "unidad_inferida": item.unidad_inferida,
            }
            for item in estado.items
        ],
        "texto": estado.texto,
        "intento": estado.intento,
        "estado": estado.estado,
        "pregunta": estado.pregunta.model_dump(mode="json") if estado.pregunta else None,
        "actualizado_ts": estado.actualizado_ts.isoformat(),
    }


def _estado_desde_json(datos: dict[str, Any]) -> EstadoNota:
    return EstadoNota(
        nota_id=datos["nota_id"],
        mensaje=MensajeTablet.model_validate(datos["mensaje"]),
        nota=NotaRecorrida.model_validate(datos["nota"]),
        borrador=[FilaParte.model_validate(fila) for fila in datos["borrador"]],
        items=[ItemParte(**item) for item in datos["items"]],
        texto=datos["texto"],
        intento=int(datos["intento"]),
        estado=datos["estado"],
        pregunta=(
            MensajeTablet.model_validate(datos["pregunta"])
            if datos.get("pregunta")
            else None
        ),
        actualizado_ts=datetime.fromisoformat(datos["actualizado_ts"]),
    )


class RepositorioMemoria:
    def __init__(self) -> None:
        self._estados: dict[str, EstadoNota] = {}
        self._respuestas: dict[str, RespuestaOperador] = {}
        self._lock = threading.RLock()

    def guardar_estado(self, estado: EstadoNota) -> None:
        with self._lock:
            self._estados[estado.nota_id] = estado

    def obtener_nota(self, nota_id: str) -> EstadoNota | None:
        with self._lock:
            return self._estados.get(nota_id)

    def obtener_por_mensaje(self, mensaje_id: str) -> EstadoNota | None:
        with self._lock:
            for estado in self._estados.values():
                if estado.mensaje.id == mensaje_id:
                    return estado
                if estado.pregunta is not None and estado.pregunta.id == mensaje_id:
                    return estado
        return None

    def guardar_respuesta(self, respuesta: RespuestaOperador) -> None:
        with self._lock:
            self._respuestas[respuesta.id] = respuesta

    def respuestas(self) -> list[RespuestaOperador]:
        with self._lock:
            return list(self._respuestas.values())

    def pendientes_sincronizar(self) -> int:
        return 0

    def iniciar(self) -> None:
        return None

    def detener(self) -> None:
        return None


class RepositorioSincronizado(RepositorioMemoria):
    """Memoria primero; Postgres se conecta y sincroniza en segundo plano."""

    def __init__(self, dsn: str, reintento_s: float = POSTGRES_REINTENTO_S) -> None:
        super().__init__()
        self._dsn = dsn
        self._reintento_s = reintento_s
        self._conexion = None
        self._pendientes: dict[tuple[str, str], Any] = {}
        self._lock_sync = threading.RLock()
        self._detener_sync = threading.Event()
        self._hilo: threading.Thread | None = None

    def iniciar(self) -> None:
        if not self._dsn or self._hilo is not None:
            return
        self._hilo = threading.Thread(
            target=self._bucle_sincronizacion, name="postgres", daemon=True
        )
        self._hilo.start()

    def detener(self) -> None:
        self._detener_sync.set()
        if self._hilo is not None:
            self._hilo.join(timeout=3)
        self._cerrar()

    def guardar_estado(self, estado: EstadoNota) -> None:
        super().guardar_estado(estado)
        with self._lock_sync:
            self._pendientes[("estado", estado.nota_id)] = estado

    def guardar_respuesta(self, respuesta: RespuestaOperador) -> None:
        super().guardar_respuesta(respuesta)
        with self._lock_sync:
            self._pendientes[("respuesta", respuesta.id)] = respuesta

    def pendientes_sincronizar(self) -> int:
        with self._lock_sync:
            return len(self._pendientes)

    def _bucle_sincronizacion(self) -> None:
        while not self._detener_sync.is_set():
            if self._conexion is None:
                try:
                    self._conectar()
                    log.info("Postgres conectado; sincronizando estado")
                except Exception as exc:
                    log.warning("Postgres no disponible: %s", exc)
                    self._detener_sync.wait(self._reintento_s)
                    continue
            try:
                self._sincronizar_pendientes()
            except Exception:
                log.exception("falló la sincronización con Postgres")
                self._cerrar()
            self._detener_sync.wait(0.5)

    def _conectar(self) -> None:
        import psycopg

        self._conexion = psycopg.connect(self._dsn, connect_timeout=2)
        self._conexion.autocommit = True
        with self._conexion.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS estado_nota (
                    nota_id TEXT PRIMARY KEY,
                    mensaje JSONB NOT NULL,
                    nota JSONB NOT NULL,
                    borrador JSONB NOT NULL,
                    items JSONB NOT NULL,
                    texto TEXT NOT NULL,
                    intento INTEGER NOT NULL,
                    estado TEXT NOT NULL,
                    pregunta JSONB,
                    actualizado_ts TIMESTAMPTZ NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS respuestas (
                    id TEXT PRIMARY KEY,
                    mensaje_id TEXT NOT NULL,
                    nota_id TEXT,
                    ts TIMESTAMPTZ NOT NULL,
                    payload JSONB NOT NULL
                )
                """
            )

    def _sincronizar_pendientes(self) -> None:
        if self._conexion is None:
            return
        with self._lock_sync:
            pendientes = list(self._pendientes.items())
        for clave, valor in pendientes:
            if isinstance(valor, EstadoNota):
                self._guardar_estado_pg(valor)
            else:
                self._guardar_respuesta_pg(valor)
            with self._lock_sync:
                if self._pendientes.get(clave) is valor:
                    self._pendientes.pop(clave, None)

    def _guardar_estado_pg(self, estado: EstadoNota) -> None:
        datos = _estado_json(estado)
        assert self._conexion is not None
        with self._conexion.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO estado_nota
                    (nota_id, mensaje, nota, borrador, items, texto, intento,
                     estado, pregunta, actualizado_ts)
                VALUES (%s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s,
                        %s, %s::jsonb, %s)
                ON CONFLICT (nota_id) DO UPDATE SET
                    mensaje = EXCLUDED.mensaje,
                    nota = EXCLUDED.nota,
                    borrador = EXCLUDED.borrador,
                    items = EXCLUDED.items,
                    texto = EXCLUDED.texto,
                    intento = EXCLUDED.intento,
                    estado = EXCLUDED.estado,
                    pregunta = EXCLUDED.pregunta,
                    actualizado_ts = EXCLUDED.actualizado_ts
                """,
                (
                    datos["nota_id"],
                    json.dumps(datos["mensaje"], ensure_ascii=False),
                    json.dumps(datos["nota"], ensure_ascii=False),
                    json.dumps(datos["borrador"], ensure_ascii=False),
                    json.dumps(datos["items"], ensure_ascii=False),
                    datos["texto"],
                    datos["intento"],
                    datos["estado"],
                    (
                        json.dumps(datos["pregunta"], ensure_ascii=False)
                        if datos["pregunta"]
                        else None
                    ),
                    datos["actualizado_ts"],
                ),
            )

    def _guardar_respuesta_pg(self, respuesta: RespuestaOperador) -> None:
        assert self._conexion is not None
        estado = super().obtener_por_mensaje(respuesta.mensaje_id)
        with self._conexion.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO respuestas (id, mensaje_id, nota_id, ts, payload)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    respuesta.id,
                    respuesta.mensaje_id,
                    estado.nota_id if estado else None,
                    respuesta.ts.isoformat(),
                    json.dumps(respuesta.model_dump(mode="json"), ensure_ascii=False),
                ),
            )

    def _cerrar(self) -> None:
        if self._conexion is not None:
            try:
                self._conexion.close()
            except Exception:
                pass
            self._conexion = None


def crear_repositorio(dsn: str) -> RepositorioMemoria:
    if not dsn:
        return RepositorioMemoria()
    return RepositorioSincronizado(dsn)
