"""Embeddings por hashing de tokens para el RAG.

No usa modelos externos ni servicios en la nube. Cada token se proyecta a
una posicion fija de un vector de dimension `EMBEDDING_DIM` usando
`zlib.crc32` (determinista entre procesos, a diferencia de `hash()`).
Sobre esas posiciones se acumulan pesos IDF calculados con los textos
recibidos y el resultado se normaliza en L2.
"""

from __future__ import annotations

import math
import re
import unicodedata
import zlib
from collections import Counter
from typing import Iterable

from .config import EMBEDDING_DIM


def _tokens(texto: str) -> list[str]:
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", texto)


def _bucket(token: str, dim: int) -> int:
    """Posicion estable del token en el vector de dimension fija."""
    return zlib.crc32(token.encode("utf-8")) % dim


class EmbeddingsHash:
    """Vectorizador por hashing de tokens con pesos IDF opcionales."""

    def __init__(self, textos: Iterable[str], dim: int | None = None) -> None:
        self.dim = dim or EMBEDDING_DIM
        documentos = [{_bucket(t, self.dim) for t in _tokens(texto)} for texto in textos]
        n = len(documentos)
        df: Counter[int] = Counter(b for d in documentos for b in d)
        self._idf = {
            b: math.log((1 + n) / (1 + c)) + 1.0 for b, c in df.items()
        }

    def embed(self, texto: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in _tokens(texto):
            b = _bucket(token, self.dim)
            peso = self._idf.get(b)
            if peso is not None:
                vector[b] += peso
        norma = math.sqrt(sum(x * x for x in vector))
        if norma == 0.0:
            return vector
        return [x / norma for x in vector]


def obtener_modelo(textos: Iterable[str]) -> EmbeddingsHash:
    return EmbeddingsHash(textos)
