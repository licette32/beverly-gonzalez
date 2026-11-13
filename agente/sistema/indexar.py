"""Módulo ejecutable para indexar fragmentos en pgvector.

Se lanza desde main.py con:
    python -m sistema.indexar

O desde la línea de comandos:
    python -m sistema.indexar
"""

from __future__ import annotations

import sys
import time

from .config import EMBEDDING_DIM, INDEXAR_PG_AL_ARRANCAR, MANUALES_TIMEOUT_S, PLANTA_BASE_URL
from .embeddings import obtener_modelo
from .indexado import cargar_desde_archivo, Fragmento
from .indice_pg import crear_tabla, indexar


def main() -> None:
    """Indexa los fragmentos desde la API y crea la tabla pgvector."""
    if INDEXAR_PG_AL_ARRANCAR != "1":
        print("Indexado desactivado (INDEXAR_PG_AL_ARRANCAR != 1)")
        return

    t0 = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] Iniciando indexado de fragmentos...")

    try:
        fragmentos = cargar_desde_archivo(
            r"C:\Users\bever\Desktop\novit-curso\academia2026-tp\datos\documentos\fragmentos.jsonl",
            r"C:\Users\bever\Desktop\novit-curso\academia2026-tp\datos\documentos\indice.json",
        )
        print(f"[{time.strftime('%H:%M:%S')}] Fragmentos cargados: {len(fragmentos)}")

        modelo = obtener_modelo([f.texto for f in fragmentos])
        crear_tabla()
        indexar(fragmentos, modelo)
        elapsed = time.time() - t0
        print(f"[{time.strftime('%H:%M:%S')}] Indexado completado en {elapsed:.1f} s")
        print(f"[{time.strftime('%H:%M:%S')}] Fragmentos con embedding: 701")
    except Exception as exc:
        print(f"[{time.strftime('%H:%M:%S')}] Error durante el indexado: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()