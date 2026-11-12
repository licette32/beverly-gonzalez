import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class ItemParte:
    tag: str | None
    variable: str
    valor: float | None
    unidad: str | None = None
    observacion: str | None = None


UNIDAD_MANOMETRO = {"B-101": "kg/cm2", "B-102": "psi", "B-103": "bar"}

A_KG = {"kg/cm2": 1.0, "psi": 1 / 14.2233, "bar": 1.01972}

LIMITES = {
    ("B-101", "presion_descarga"): {"alarma_alta": 125.0, "alarma_baja": 95.0},
    ("B-102", "presion_descarga"): {"alarma_alta": 125.0, "alarma_baja": 95.0},
    ("B-103", "presion_descarga"): {"alarma_alta": 125.0, "alarma_baja": 95.0},
    ("F-201A", "presion_diferencial"): {"alarma_alta": 1.5, "alarma_baja": 0.15},
    ("F-201B", "presion_diferencial"): {"alarma_alta": 1.5, "alarma_baja": 0.15},
}

VARIABLES_CON_LIMITE = {
    "presion_descarga_local": "presion_descarga",
    "presion_diferencial": "presion_diferencial",
}

OBSERVACIONES_NORMALES = {"parada, en reserva", "parada por mantenimiento"}

EQUIPOS = [
    (r"\bla uno\b|\bla 1\b|\bla de la punta\b|\bla del porton\b|\bbomba uno\b", "B-101"),
    (r"\bla dos\b|\bla 2\b|\bla del medio\b|\bbomba dos\b", "B-102"),
    (r"\bla tres\b|\bla 3\b|\bla del fondo\b|\bla de reserva\b|\bbomba tres\b", "B-103"),
    (r"\bel filtro a\b|\bel primario\b|\bel de la izquierda\b|\bel grueso\b", "F-201A"),
    (r"\bel filtro b\b|\bel secundario\b|\bel de la derecha\b|\bel fino\b", "F-201B"),
    (r"\bel pulmon\b|\bel tanque\b", "TK-301"),
    (r"\bel caudalimetro\b|\bel colector\b", "FT-401"),
    (r"\bla bomba\b", None),
]

UNIDADES = {
    "cero": 0,
    "uno": 1,
    "un": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "dieciseis": 16,
    "diecisiete": 17,
    "dieciocho": 18,
    "diecinueve": 19,
    "veinte": 20,
    "veintiuno": 21,
    "veintiun": 21,
    "veintiuna": 21,
    "veintidos": 22,
    "veintitres": 23,
    "veinticuatro": 24,
    "veinticinco": 25,
    "veintiseis": 26,
    "veintisiete": 27,
    "veintiocho": 28,
    "veintinueve": 29,
}

DECENAS = {
    "treinta": 30,
    "cuarenta": 40,
    "cincuenta": 50,
    "sesenta": 60,
    "setenta": 70,
    "ochenta": 80,
    "noventa": 90,
}

CIENTOS = {
    "cien": 100,
    "ciento": 100,
    "doscientos": 200,
    "trescientos": 300,
    "cuatrocientos": 400,
    "quinientos": 500,
    "seiscientos": 600,
    "setecientos": 700,
    "ochocientos": 800,
    "novecientos": 900,
}

DIGITOS = {palabra: valor for palabra, valor in UNIDADES.items() if valor < 10}

SEPARADORES_DECIMALES = ("coma", "punto", "con")

PALABRAS_NUMERO = (
    set(UNIDADES)
    | set(DECENAS)
    | set(CIENTOS)
    | {"mil", "y", "medio", *SEPARADORES_DECIMALES}
)

TOKEN = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)?")


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = texto.replace("\ufffd", "")
    return re.sub(r"\bp\.?\s*c\.?(?![a-z])", "psi", texto)


def _oraciones(texto: str) -> list[str]:
    partes = re.split(r"[.!?;]+(?=\s|$)", texto)
    return [parte.strip() for parte in partes if parte.strip()]


def _es_numero(token: str) -> bool:
    if re.fullmatch(r"\d+(?:[.,]\d+)?", token):
        return True
    return token in PALABRAS_NUMERO


def _entero(tokens: list[str]) -> int:
    total = 0
    actual = 0
    for token in tokens:
        if token == "mil":
            actual = actual or 1
            total += actual * 1000
            actual = 0
        elif token in CIENTOS:
            actual += CIENTOS[token]
        elif token in DECENAS:
            actual += DECENAS[token]
        elif token in UNIDADES:
            actual += UNIDADES[token]
        elif token == "y":
            continue
        else:
            break
    return total + actual


def _digito(token: str) -> str:
    if token in DIGITOS:
        return str(DIGITOS[token])
    return str(_entero([token]))


def _decimal(token: str) -> float:
    if "," in token:
        entero, fraccion = token.split(",", 1)
        return float(f"{entero}.{fraccion}")
    if "." in token:
        entero, fraccion = token.split(".", 1)
        if len(fraccion) == 3 and len(entero) <= 3 and entero.isdigit():
            return float(entero + fraccion)
        return float(f"{entero}.{fraccion}")
    return float(token)


def _parsear(tokens: list[str]) -> float | None:
    if not tokens:
        return None
    while tokens and tokens[-1] in {"y", *SEPARADORES_DECIMALES}:
        tokens = tokens[:-1]
    if not tokens:
        return None
    # Whisper suele transcribir "me dio" como "medio" antes del número.
    if len(tokens) > 1 and tokens[0] == "medio":
        tokens = tokens[1:]
    if len(tokens) == 1 and re.fullmatch(r"\d+(?:[.,]\d+)?", tokens[0]):
        return _decimal(tokens[0])
    for separador in SEPARADORES_DECIMALES:
        if separador in tokens:
            indice = tokens.index(separador)
            entero = _entero(tokens[:indice]) if tokens[:indice] else 0
            decimales = tokens[indice + 1 :]
            if not decimales:
                return float(entero)
            cifras = "".join(_digito(token) for token in decimales)
            if not cifras:
                return float(entero)
            return entero + float(f"0.{cifras}")
    if len(tokens) >= 2 and tokens[-2:] == ["y", "medio"]:
        return float(_entero(tokens[:-2])) + 0.5
    if tokens == ["medio"]:
        return 0.5
    if len(tokens) == 2 and all(token in DIGITOS for token in tokens):
        return DIGITOS[tokens[0]] + DIGITOS[tokens[1]] / 10
    if len(tokens) == 2 and all(re.fullmatch(r"\d", token) for token in tokens):
        return float(tokens[0]) + float(tokens[1]) / 10
    return float(_entero(tokens))


def numeros(texto: str) -> list[tuple[int, int, float]]:
    tokens = [(m.group(), m.start(), m.end()) for m in TOKEN.finditer(texto)]
    salida: list[tuple[int, int, float]] = []
    i = 0
    while i < len(tokens):
        if not _es_numero(tokens[i][0]):
            i += 1
            continue
        j = i
        while j < len(tokens) and _es_numero(tokens[j][0]):
            j += 1
        valor = _parsear([token[0] for token in tokens[i:j]])
        if valor is not None:
            salida.append((tokens[i][1], tokens[j - 1][2], valor))
        i = j
    return salida


def numero(texto: str) -> float | None:
    hallados = numeros(normalizar(texto))
    return hallados[0][2] if len(hallados) == 1 else None


def _menciones(texto: str) -> list[tuple[int, int, str | None]]:
    salida: list[tuple[int, int, str | None]] = []
    for patron, tag in EQUIPOS:
        for coincidencia in re.finditer(patron, texto):
            salida.append((coincidencia.start(), coincidencia.end(), tag))
    salida.sort()
    return salida


def _tag_en(
    posicion: int,
    menciones: list[tuple[int, int, str | None]],
    heredado: str | None,
) -> str | None:
    previas = [mencion for mencion in menciones if mencion[0] <= posicion]
    return previas[-1][2] if previas else heredado


def _ultimo_numero(
    lista: list[tuple[int, int, float]], posicion: int
) -> tuple[int, int, float] | None:
    previos = [numero_ for numero_ in lista if numero_[1] <= posicion]
    return previos[-1] if previos else None


def _unidad(texto: str, desde: int, hasta: int) -> str | None:
    trozo = texto[desde:hasta]
    if re.search(r"\b(kilos|kilogramos)\b", trozo):
        return "kg/cm2"
    if re.search(r"\b(psi|libras|libra)\b", trozo):
        return "psi"
    if re.search(r"\b(bares|bar)\b", trozo):
        return "bar"
    if re.search(r"\bmetros\b", trozo):
        return "m"
    if re.search(r"\bgotas\b", trozo):
        return "gotas/min"
    return None


def _items_oracion(
    oracion: str,
    menciones: list[tuple[int, int, str | None]],
    heredado: str | None,
    lista_numeros: list[tuple[int, int, float]],
    unidades_manometro: dict[str, str] | None = None,
) -> list[ItemParte]:
    items: list[ItemParte] = []
    unidades_manometro = unidades_manometro or UNIDAD_MANOMETRO

    for coincidencia in re.finditer(r"\bdescarga\b", oracion):
        numero_ = _ultimo_numero(lista_numeros, coincidencia.start())
        if numero_ is None:
            continue
        tag = _tag_en(numero_[0], menciones, heredado)
        unidad = _unidad(oracion, numero_[1], coincidencia.start())
        if unidad is None:
            unidad = unidades_manometro.get(tag or "", "kg/cm2")
        items.append(ItemParte(tag, "presion_descarga_local", numero_[2], unidad))

    for coincidencia in re.finditer(r"\bdiferencial\b", oracion):
        numero_ = _ultimo_numero(lista_numeros, coincidencia.start())
        if numero_ is None:
            continue
        tag = _tag_en(numero_[0], menciones, heredado)
        unidad = _unidad(oracion, numero_[1], coincidencia.start()) or "kg/cm2"
        observacion = "diferencial alto" if numero_[2] * A_KG.get(unidad, 1.0) >= 1.5 else None
        items.append(ItemParte(tag, "presion_diferencial", numero_[2], unidad, observacion))

    if "grados" in oracion and re.search(r"\b(rodamiento|pistola|temperatura)\b", oracion):
        for coincidencia in re.finditer(r"\bgrados\b", oracion):
            numero_ = _ultimo_numero(lista_numeros, coincidencia.start())
            if numero_ is None:
                continue
            tag = _tag_en(numero_[0], menciones, heredado)
            observacion = "rodamiento caliente" if numero_[2] > 75 else None
            items.append(
                ItemParte(tag, "temperatura_rodamiento_ir", numero_[2], "degC", observacion)
            )

    if "empaquetadura" in oracion and re.search(
        r"\b(gotea|goteando|pierde|perdida|chorrea)\b", oracion
    ):
        coincidencia = re.search(
            r"\b(gotea|goteando|pierde|perdida|chorrea)\b", oracion
        )
        tag = _tag_en(coincidencia.start(), menciones, heredado)
        fuerte = "chorrea" in oracion or "pierde bastante" in oracion
        observacion = (
            "perdida importante por empaquetadura"
            if fuerte
            else "goteo por empaquetadura"
        )
        gotas = re.search(r"\bgotas\b", oracion)
        numero_ = _ultimo_numero(lista_numeros, gotas.start()) if gotas else None
        valor = numero_[2] if numero_ else None
        items.append(ItemParte(tag, "goteo_empaquetadura", valor, "gotas/min", observacion))

    if "aceite" in oracion and ("visor" in oracion or "casi no tiene" in oracion):
        coincidencia = re.search(r"\b(aceite|visor)\b", oracion)
        tag = _tag_en(coincidencia.start(), menciones, heredado)
        items.append(
            ItemParte(tag, "nivel_aceite_visor", None, None, "nivel de aceite bajo")
        )

    if re.search(r"\bcorreas\b|\bcorrea\b", oracion):
        estado = None
        if "flojas" in oracion:
            estado = "flojas"
        elif "gastadas" in oracion:
            estado = "gastadas"
        if estado is not None:
            coincidencia = re.search(r"\bcorreas\b|\bcorrea\b", oracion)
            tag = _tag_en(coincidencia.start(), menciones, heredado)
            items.append(
                ItemParte(tag, "estado_correas", None, None, f"correas {estado}")
            )

    observacion_ruido = None
    posicion_ruido = 0
    if "golpeteo" in oracion:
        observacion_ruido = "golpeteo metalico"
        posicion_ruido = oracion.index("golpeteo")
    elif "piedras" in oracion:
        observacion_ruido = "cavitacion"
        posicion_ruido = oracion.index("piedras")
    elif "ruido" in oracion and "rodamiento" in oracion:
        observacion_ruido = "ruido de rodamiento"
        posicion_ruido = oracion.index("ruido")
    if observacion_ruido is not None:
        tag = _tag_en(posicion_ruido, menciones, heredado)
        items.append(ItemParte(tag, "ruido", None, None, observacion_ruido))

    observacion_estado = None
    posicion_estado = 0
    if "parada por mantenimiento" in oracion:
        observacion_estado = "parada por mantenimiento"
        posicion_estado = oracion.index("parada por mantenimiento")
    elif re.search(r"\bparada\b", oracion) and "en reserva" in oracion:
        observacion_estado = "parada, en reserva"
        posicion_estado = oracion.index("parada")
    elif "disparada" in oracion or "no arranca" in oracion:
        observacion_estado = "disparada, no arranca"
        posicion_estado = oracion.index("disparada") if "disparada" in oracion else oracion.index("no arranca")
    if observacion_estado is not None:
        tag = _tag_en(posicion_estado, menciones, heredado)
        items.append(ItemParte(tag, "estado", None, None, observacion_estado))

    if "metros" in oracion and any(tag == "TK-301" for _, _, tag in menciones):
        coincidencia = re.search(r"\bmetros\b", oracion)
        numero_ = _ultimo_numero(lista_numeros, coincidencia.start())
        if numero_ is not None:
            observacion = "rebalse a pileta" if "rebalsando" in oracion else None
            items.append(ItemParte("TK-301", "nivel", numero_[2], "m", observacion))

    vistos = set()
    unicos: list[ItemParte] = []
    for item in items:
        clave = (item.tag, item.variable, item.valor, item.unidad, item.observacion)
        if clave not in vistos:
            vistos.add(clave)
            unicos.append(item)
    return unicos


def extraer_items(
    texto: str, unidades_manometro: dict[str, str] | None = None
) -> list[ItemParte]:
    normalizado = normalizar(texto)
    items: list[ItemParte] = []
    heredado: str | None = None
    for oracion in _oraciones(normalizado):
        menciones = _menciones(oracion)
        lista_numeros = numeros(oracion)
        items.extend(
            _items_oracion(
                oracion,
                menciones,
                heredado,
                lista_numeros,
                unidades_manometro,
            )
        )
        if menciones:
            heredado = menciones[-1][2]
    return items


def fuera_de_limite(item: ItemParte) -> bool:
    if item.valor is None:
        return False
    sensor = VARIABLES_CON_LIMITE.get(item.variable)
    if sensor is None:
        return False
    limites = LIMITES.get((item.tag or "", sensor))
    if not limites:
        return False
    valor = item.valor * A_KG.get(item.unidad or "kg/cm2", 1.0)
    alta = limites.get("alarma_alta")
    baja = limites.get("alarma_baja")
    return (alta is not None and valor >= alta) or (baja is not None and valor <= baja)