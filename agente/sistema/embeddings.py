"""Embeddings TF-IDF en memoria para el RAG de la Entrega 1.

No usa modelos externos ni servicios en la nube: construye un vocabulario y
pesos IDF a partir de los textos recibidos y devuelve vectores normalizados.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Iterable


def _tokens(texto: str) -> list[str]:
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", texto)


class EmbeddingsTFIDF:
    """Vectorizador TF-IDF ajustado a una coleccion de textos."""

    def __init__(self, textos: Iterable[str]) -> None:
        documentos = [Counter(_tokens(t)) for t in textos]
        self._vocabulario = sorted({t for d in documentos for t in d})
        self._indice = {t: i for i, t in enumerate(self._vocabulario)}
        n = len(documentos)
        df: Counter[str] = Counter(t for d in documentos for t in d)
        self._idf = {
            t: math.log((1 + n) / (1 + df[t])) + 1.0 for t in self._vocabulario
        }

    def embed(self, texto: str) -> list[float]:
        tf = Counter(_tokens(texto))
        vector = [0.0] * len(self._vocabulario)
        for token, frecuencia in tf.items():
            if token in self._indice:
                vector[self._indice[token]] = frecuencia * self._idf[token]
        norma = math.sqrt(sum(x * x for x in vector))
        if norma == 0.0:
            return vector
        return [x / norma for x in vector]


def obtener_modelo(textos: Iterable[str]) -> EmbeddingsTFIDF:
    return EmbeddingsTFIDF(textos)
