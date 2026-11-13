"""Evalúa hit@5 y recall@5 del RAG contra la suite del corpus del curso.

Uso:
    python evaluacion/retrieval_eval.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
AGENTE = RAIZ / "agente"
if str(AGENTE) not in sys.path:
    sys.path.insert(0, str(AGENTE))

from sistema import indexado, rag  # noqa: E402

BASE_BM25 = {"hit@5": 0.85, "recall@5": 0.66}


def cargar_suite(curso: Path) -> list[dict]:
    ruta = curso / "datos" / "documentos" / "evaluacion" / "retrieval.json"
    return json.loads(ruta.read_text(encoding="utf-8"))


def cargar_fragmentos(curso: Path, api: str) -> tuple[list, str]:
    try:
        fragmentos = indexado.cargar_desde_api(api)
        if fragmentos:
            return fragmentos, f"api {api}"
    except Exception as exc:
        print(f"API no disponible: {exc}")

    ruta_fragmentos = curso / "datos" / "documentos" / "fragmentos.jsonl"
    ruta_indice = curso / "datos" / "documentos" / "indice.json"
    print(f"Usando archivo local: {ruta_fragmentos}")
    fragmentos = indexado.cargar_desde_archivo(str(ruta_fragmentos), str(ruta_indice))
    return fragmentos, "archivo local"


def main() -> None:
    ap = argparse.ArgumentParser(description="Evalúa hit@5 y recall@5 del RAG")
    ap.add_argument("--api", default=os.getenv("PLANTA_API", "http://localhost:8100"))
    ap.add_argument(
        "--curso",
        type=Path,
        default=Path(
            os.getenv(
                "PLANTA_CURSO",
                RAIZ.parent / "novit-curso" / "academia2026-tp",
            )
        ),
    )
    a = ap.parse_args()
    curso = a.curso.resolve()

    if not (curso / "planta" / "corpus" / "evaluar.py").exists():
        raise SystemExit(f"No se encontró corpus/evaluar.py en {curso}")
    sys.path.insert(0, str(curso / "planta"))
    from corpus import evaluar as evaluar_corpus

    suite = cargar_suite(curso)
    fragmentos, fuente = cargar_fragmentos(curso, a.api)
    rag.cargar_desde_api = lambda: fragmentos
    rag._retriever = None

    resultado = evaluar_corpus.evaluar(rag.buscar, suite)
    total = resultado["total"]
    hit5 = total["hit@5"]
    recall5 = total["recall@5"]

    por_id = {q["id"]: q for q in suite}
    rev_c_antes_d = 0
    rev_c_antes_d_ambas = 0
    fallan = []
    for fila in resultado["preguntas"]:
        top = fila["top"]
        pos_c = next((i for i, c in enumerate(top) if c.startswith("TX350-C")), None)
        pos_d = next((i for i, c in enumerate(top) if c.startswith("TX350-D")), None)
        if pos_c is not None and (pos_d is None or pos_c < pos_d):
            rev_c_antes_d += 1
        if pos_c is not None and pos_d is not None and pos_c < pos_d:
            rev_c_antes_d_ambas += 1
        if fila["hit@5"] == 0:
            fallan.append(fila)

    salida = {
        "fragmentos": len(fragmentos),
        "fuente_fragmentos": fuente,
        "suite": len(suite),
        "hit@5": hit5,
        "recall@5": recall5,
        "rev_c_antes_de_d": rev_c_antes_d,
        "rev_c_antes_de_d_ambas": rev_c_antes_d_ambas,
        "base_bm25": BASE_BM25,
        "total": total,
        "por_tipo": resultado["por_tipo"],
        "preguntas": resultado["preguntas"],
    }
    destino = RAIZ / "evaluacion" / "resultados" / "retrieval.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Fragmentos: {len(fragmentos)} ({fuente})")
    print(f"Preguntas: {len(suite)}")
    print(f"hit@5:    {hit5:.3f}  (base BM25 0.850)")
    print(f"recall@5: {recall5:.3f}  (base BM25 0.660)")
    print(
        f"Rev. C antes que D: {rev_c_antes_d}/{len(suite)} "
        f"(estricto, ambas: {rev_c_antes_d_ambas})"
    )
    print(f"Resultado: {destino}")
    if fallan:
        print(f"\nPreguntas sin hit@5 ({len(fallan)}), máx. 10:")
        for fila in fallan[:10]:
            q = por_id[fila["id"]]
            print(f"- {fila['id']}: {q['pregunta']}")
            print(f"  esperado: {q['relevantes']}")
            print(f"  obtuvo:   {fila['top']}")


if __name__ == "__main__":
    main()
