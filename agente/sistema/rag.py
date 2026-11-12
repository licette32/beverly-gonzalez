
Exponer `buscar(pregunta, k) -> list[str]` compatible con
`planta.corpus.evaluar.evaluar(buscar, suite)`.

No modifica contratos MQTT ni modelos de planta_contrato. No excluye
documentos históricos ni contratos por aplicar vigente=True de forma
indiscriminada: respeta la semantica de cada tipo de documento.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Iterable

from .indexado import Fragmento, cargar_desde_api


def _tokens(texto: str) -> list[str]:
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return [t for t in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", texto)]


class _BM25:
    """BM25 sobre una coleccion de fragmentos (misma logica que evaluar.py)."""

    def __init__(self, fragmentos: Iterable[Fragmento], k1: float = 1.4, b: float = 0.75) -> None:
        self.ids = [f.id for f in fragmentos]
        self.docs = [Counter(_tokens(f.texto)) for f in fragmentos]
        self.largos = [sum(d.values()) for d in self.docs]
        self.prom = sum(self.largos) / max(len(self.largos), 1)
        df: Counter[str] = Counter(t for d in self.docs for t in d)
        n = len(self.docs)
        self.idf = {
            t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()
        }
        self.k1, self.b = k1, b

    def buscar(self, pregunta: str, k: int) -> list[tuple[str, float]]:
        q = _tokens(pregunta)
        puntajes: list[tuple[float, str]] = []
        for i, d in enumerate(self.docs):
            s = 0.0
            for t in q:
                if t in d:
                    tf = d[t]
                    s += (
                        self.idf[t]
                        * tf
                        * (self.k1 + 1)
                        / (tf + self.k1 * (1 - self.b + self.b * self.largos[i] / self.prom))
                    )
            if s > 0:
                puntajes.append((s, self.ids[i]))
        puntajes.sort(key=lambda x: x[0], reverse=True)
        return puntajes[:k]


def _coseno(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    num = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return num / (na * nb)



    def __init__(self, fragmentos: list[Fragmento]) -> None:
        self.fragmentos = fragmentos
        self.por_id = {f.id: f for f in fragmentos}
        self._modelo = None
        self._bm25_vigente: _BM25 | None = None
        self._bm25_todos: _BM25 | None = None

    @property
    def modelo(self):
        if self._modelo is None:
            self._modelo = obtener_modelo([f.texto for f in self.fragmentos])
        return self._modelo

    @property
    def bm25_vigente(self) -> _BM25:
        if self._bm25_vigente is None:
            self._bm25_vigente = _BM25([f for f in self.fragmentos if f.vigente])
        return self._bm25_vigente

    @property
    def bm25_todos(self) -> _BM25:
        if self._bm25_todos is None:
            self._bm25_todos = _BM25(self.fragmentos)
        return self._bm25_todos

    def _vectorial(
        self, pregunta: str, k: int, solo_vigentes: bool = True
    ) -> list[tuple[str, float]]:
        candidatos = [f for f in self.fragmentos if f.vigente or not solo_vigentes]
        if not candidatos:
            return []
        q_emb = self.modelo.embed(pregunta)
        scored: list[tuple[float, str]] = []
        for f in candidatos:
            emb = self.modelo.embed(f.texto)
            scored.append((_coseno(q_emb, emb), f.id))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:k]

    @staticmethod
    ) -> list[str]:
        scores: dict[str, float] = {}
        for lista in listas:
            for pos, (cid, _puntos) in enumerate(lista):
        orden = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [cid for cid, _ in orden]

    def buscar(
        self, pregunta: str, k: int = 5, solo_vigentes: bool = True
    ) -> list[str]:
        """Devuelve citas ordenadas, sin repetir, lista para evaluar(buscar, suite).

        - BM25 y vectorial se ejecutan sobre los fragmentos permitidos según
          solo_vigentes (vigente=True para manuales, todos para historial/
          contrato/certificacion).
        """
        bm25 = self.bm25_vigente if solo_vigentes else self.bm25_todos
        bm25_top = bm25.buscar(pregunta, k * 3)
        vec_top = self._vectorial(pregunta, k * 3, solo_vigentes=solo_vigentes)

        vistos: set[str] = set()
        salida: list[str] = []
        for cid in fusion:
            if cid not in vistos:
                vistos.add(cid)
                salida.append(cid)
                if len(salida) >= k:
                    break
        return salida


# Instancia por defecto perezosa: se pobla al primer buscar().


    global _retriever
    if _retriever is None:
    return _retriever


def buscar(pregunta: str, k: int = 5) -> list[str]:
    """Interfaz compatible con planta.corpus.evaluar.evaluar(buscar, suite).

    Devuelve una lista de citas (ids de fragmentos) en orden de relevancia.
    """
    return _obtener_retriever().buscar(pregunta, k)


    global _retriever
    _retriever = None
