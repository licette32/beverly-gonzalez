import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Deteccion:
    categoria: str
    evidencia: str


def normalizar(texto: str) -> str:
    # minúsculas, sin tildes, sin signos: "Presión!" -> "presion"
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"\bapresion\b", "a presion", texto)
    texto = re.sub(r"[.,;:!?¡¿]", " | ", texto)  # la puntuación corta la frase
    return re.sub(r"[^a-z0-9\s|]", " ", texto)


NEGADORES = {
    "no",
    "sin",
    "ni",
    "nadie",
    "ningun",
    "ninguna",
    "ninguno",
    "nunca",
    "tampoco",
    "nada",
}
CORTES = {"|", "y", "pero", "sino", "aunque"}
# frases donde el negador no niega: "no para de", "sin dejar de", etc.
EXCEPCIONES = (
    ("no", "para", "de"),
    ("no", "deja", "de"),
    ("no", "dejan", "de"),
    ("sin", "parar"),
    ("sin", "dejar", "de"),
)


def _es_excepcion(tokens: list[str], indice: int) -> bool:
    for exc in EXCEPCIONES:
        if tuple(tokens[indice:indice + len(exc)]) == exc:
            return True
    return False


def _negado_tokens(tokens: list[str], indice: int) -> bool:
    # miro hasta 6 palabras hacia atrás, cortando en | y en coordinantes
    for k in range(indice - 1, max(-1, indice - 7), -1):
        token = tokens[k]
        if token in CORTES:
            return False
        if token in NEGADORES:
            if _es_excepcion(tokens, k):
                continue
            return True
    return False


def negado_antes(texto_previo: str) -> bool:
    tokens = texto_previo.split()
    return _negado_tokens(tokens, len(tokens))


def buscar(texto: str, patrones: list[str]) -> str | None:
    for patron in patrones:
        for m in re.finditer(patron, texto):
            if not negado_antes(texto[:m.start()]):
                return m.group()
    return None


# ---------------------------------------------------------------- S1
AGUA = "agua"


def _es_proyeccion(tokens: list[str], indice: int) -> bool:
    token = tokens[indice]
    if token.startswith("presion"):
        siguiente = tokens[indice + 1] if indice + 1 < len(tokens) else ""
        return siguiente != "normal"
    if token in {"chorro", "chorros", "fuerza", "proyeccion"}:
        return True
    if token.startswith("roci"):
        return True
    if token == "lados" and indice >= 2:
        return tokens[indice - 1] == "todos" and tokens[indice - 2] == "para"
    return False


def detectar_s1(texto: str) -> str | None:
    # S1 = agua Y una señal de proyección a menos de 10 palabras
    tokens = texto.split()
    word_idx = [i for i, t in enumerate(tokens) if t != "|"]
    for r, i in enumerate(word_idx):
        if tokens[i] != AGUA or _negado_tokens(tokens, i):
            continue
        desde = max(0, r - 10)
        hasta = min(len(word_idx), r + 11)
        for rr in range(desde, hasta):
            j = word_idx[rr]
            if _es_proyeccion(tokens, j) and not _negado_tokens(tokens, j):
                inicio, fin = sorted((i, j))
                return " ".join(tokens[inicio:fin + 1])
    return None


# ---------------------------------------------------------------- S2
S2_PATRONES = [
    r"\b(?:fuga|escape|perdida)\b[^|]{0,20}?\bgas\b",
    r"\b(?:olor|huele|huelo|se siente)\b[^|]{0,15}?\bgas\b",
    r"\bhay\s+gas\b",
    r"\bgas\b",
]


def detectar_s2(texto: str) -> str | None:
    return buscar(texto, S2_PATRONES)


# ---------------------------------------------------------------- S3
S3_PATRONES = [
    r"\bhumo\b",
    r"\bhumit\w*",
    r"\bhumea\w*",
    r"\bincendi\w*",
    r"\bfuego\b",
    r"\bllamas\b",
    r"\bse prendio\b",
    r"\b(?:olor|huele) a quemado\b",
    r"\bse quemo (?:el|la) (?:motor|tablero|cable)\b",
]


def detectar_s3(texto: str) -> str | None:
    return buscar(texto, S3_PATRONES)


# ---------------------------------------------------------------- S4
PERSONAS = {
    "operario", "operaria", "tecnico", "tecnica", "persona", "companero",
    "companera", "trabajador", "trabajadora", "alguien",
}
PARTES = {
    "mano", "manos", "dedo", "dedos", "brazo", "brazos", "pierna", "piernas",
    "cabeza", "pie", "pies", "tobillo", "rodilla", "espalda", "hombro",
    "cara", "ojo", "ojos", "cintura", "cadera", "pecho", "cuello", "muneca",
}
VERBOS_LESION = {
    "golpeo", "golpearon", "golpee", "golpearse", "lastimo", "lastimaron",
    "lesiono", "lesionaron", "corto", "cortaron", "torcio", "torcieron",
    "cayo", "cayeron", "desmayo", "desmayaron", "electrocuto",
    "electrocutaron",
}
PURGA = {
    "linea", "lineas", "manometro", "manometros", "filtro", "filtros",
    "bomba", "bombas", "descarga", "tanque", "tanques",
}

S4_PATRONES = [
    r"\bse desmayo\b",
    r"\bdesmayad[oa]\b",
    r"\bse electrocut\w*",
    r"\belectrocutad[oa]\b",
    r"\bsangre\b",
    r"\b(?:lesionad[oa]|lastimad[oa]|herid[oa])\b",
    r"\b(?:persona|operari[oa]|tecnic[oa]|companer[oa]|trabajador[a]?)\b"
    r"[^|]{0,20}?\b(?:lesionad[oa]|lastimad[oa]|golpead[oa]|herid[oa])\b",
]


def _cerca(tokens: list[str], word_idx: list[int], indice: int, vocabulario: set[str], radio: int) -> bool:
    r = word_idx.index(indice)
    desde = max(0, r - radio)
    hasta = min(len(word_idx), r + radio + 1)
    return any(tokens[word_idx[rr]] in vocabulario for rr in range(desde, hasta))


def _es_purga(tokens: list[str], word_idx: list[int], indice: int) -> bool:
    r = word_idx.index(indice)
    for offset in (1, 2):
        if r + offset < len(word_idx):
            if tokens[word_idx[r + offset]] in PURGA:
                return True
    return False


def detectar_s4(texto: str) -> str | None:
    evidencia = buscar(texto, S4_PATRONES)
    if evidencia:
        return evidencia

    tokens = texto.split()
    word_idx = [i for i, t in enumerate(tokens) if t != "|"]
    for i in word_idx:
        token = tokens[i]
        if _negado_tokens(tokens, i):
            continue
        if token in VERBOS_LESION:
            if _cerca(tokens, word_idx, i, PERSONAS | PARTES, 5):
                return token
        if token == "sangrando":
            if _es_purga(tokens, word_idx, i):
                continue
            if _cerca(tokens, word_idx, i, PERSONAS | PARTES, 8):
                return token
    return None


# ---------------------------------------------------------------- global
def detectar(texto: str) -> list[Deteccion]:
    texto = normalizar(texto)
    encontradas = []

    for categoria, detector in (
        ("S1", detectar_s1),
        ("S2", detectar_s2),
        ("S3", detectar_s3),
        ("S4", detectar_s4),
    ):
        evidencia = detector(texto)
        if evidencia:
            encontradas.append(Deteccion(categoria, evidencia))
    return encontradas
