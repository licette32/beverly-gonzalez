"""Indice vectorial de fragmentos en PostgreSQL/pgvector.

Cada operacion abre y cierra su propia conexion usando `POSTGRES_DSN`; no
se mantiene un pool ni conexiones de larga vida. Los errores de busqueda se
registran y devuelven una lista vacia para que el RAG caiga al indice en
memoria sin afectar el latido ni el camino critico del agente.
"""

from __future__ import annotations

import logging

from . import config
from .indexado import Fragmento

log = logging.getLogger(__name__)

SQL_TABLA = f"""
CREATE TABLE IF NOT EXISTS fragmentos (
    id text PRIMARY KEY,
    doc text,
    numero text,
    titulo text,
    texto text,
    vigente boolean,
    pagina integer,
    tipo text,
    archivo text,
    embedding vector({config.EMBEDDING_DIM})
)
"""

SQL_INSERT = """
INSERT INTO fragmentos
    (id, doc, numero, titulo, texto, vigente, pagina, tipo, archivo, embedding)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
ON CONFLICT (id) DO UPDATE SET
    doc = EXCLUDED.doc,
    numero = EXCLUDED.numero,
    titulo = EXCLUDED.titulo,
    texto = EXCLUDED.texto,
    vigente = EXCLUDED.vigente,
    pagina = EXCLUDED.pagina,
    tipo = EXCLUDED.tipo,
    archivo = EXCLUDED.archivo,
    embedding = EXCLUDED.embedding
"""

SQL_BUSCAR = """
SELECT id, 1 - (embedding <=> %s::vector) AS score
FROM fragmentos
WHERE embedding IS NOT NULL
{extra}
ORDER BY embedding <=> %s::vector
LIMIT %s
"""


def _psycopg():
    import psycopg

    return psycopg


def _abrir_conexion():
    return _psycopg().connect(
        config.POSTGRES_DSN, connect_timeout=config.PG_TIMEOUT_S
    )


def _formato_vector(embedding: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"


def _es_cero(embedding: list[float]) -> bool:
    return all(abs(x) < 1e-12 for x in embedding)


def crear_tabla(conexion=None) -> None:
    """Habilita pgvector y crea la tabla `fragmentos` si no existe."""
    propia = conexion is None
    conn = conexion if conexion is not None else _abrir_conexion()
    cur = conn.cursor()
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute(SQL_TABLA)
        if propia:
            conn.commit()
    finally:
        cur.close()
        if propia:
            conn.close()


def indexar(fragmentos: list[Fragmento], modelo, conexion=None) -> int:
    """Inserta o actualiza fragmentos de forma idempotente (ON CONFLICT)."""
    propia = conexion is None
    conn = conexion if conexion is not None else _abrir_conexion()
    cur = conn.cursor()
    try:
        for f in fragmentos:
            vector = _formato_vector(modelo.embed(f.texto))
            cur.execute(
                SQL_INSERT,
                (
                    f.id,
                    f.doc,
                    f.numero,
                    f.titulo,
                    f.texto,
                    f.vigente,
                    f.pagina,
                    f.tipo,
                    f.archivo,
                    vector,
                ),
            )
        if propia:
            conn.commit()
        return len(fragmentos)
    finally:
        cur.close()
        if propia:
            conn.close()


def buscar(
    pregunta: str,
    k: int = 5,
    solo_vigentes: bool = True,
    modelo=None,
    conexion=None,
) -> list[tuple[float, str]]:
    """Devuelve `(score, id)` ordenados por distancia coseno en pgvector."""
    if modelo is None:
        log.warning("indice_pg.buscar sin modelo de embeddings")
        return []

    embedding = modelo.embed(pregunta)
    if _es_cero(embedding):
        return []
    vector = _formato_vector(embedding)

    propia = conexion is None
    try:
        conn = conexion if conexion is not None else _abrir_conexion()
        cur = conn.cursor()
        try:
            timeout_ms = int(config.PG_TIMEOUT_S * 1000)
            cur.execute(f"SET statement_timeout = {timeout_ms}")
            extra = "AND vigente = true" if solo_vigentes else ""
            cur.execute(SQL_BUSCAR.format(extra=extra), (vector, vector, k))
            filas = cur.fetchall()
        finally:
            cur.close()
            if propia:
                conn.close()
        return [(float(score), str(cid)) for cid, score in filas]
    except Exception as exc:
        log.warning("indice_pg.buscar fallo: %s", exc)
        return []
