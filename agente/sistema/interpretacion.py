from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Literal

from .ambiguedades import Ambiguedad, detectar
from .catalogo import CatalogoPlanta
from .parte import ItemParte, normalizar, numeros

A_KG = {"kg/cm2": 1.0, "psi": 1 / 14.2233, "bar": 1.01972}


def _observacion_numerica(
    variable: str, valor: float | None, unidad: str | None
) -> str | None:
    if valor is None:
        return None
    if variable == "presion_diferencial":
        return "diferencial alto" if valor * A_KG.get(unidad or "kg/cm2", 1.0) >= 1.5 else None
    if variable == "temperatura_rodamiento_ir":
        return "rodamiento caliente" if valor > 75 else None
    return None

UNIDADES = (
    ("gotas por minuto", "gotas/min"),
    ("kg/cm2", "kg/cm2"),
    ("kg/cm²", "kg/cm2"),
    ("kilogramos", "kg/cm2"),
    ("kilos", "kg/cm2"),
    ("libras", "psi"),
    ("libra", "psi"),
    ("bares", "bar"),
    ("grados", "degC"),
    ("metros", "m"),
    ("gotas", "gotas/min"),
    ("psi", "psi"),
    ("kg", "kg/cm2"),
    ("lb", "psi"),
    ("bar", "bar"),
    ("degc", "degC"),
    ("°c", "degC"),
    ("m", "m"),
)

CONFIRMA = re.compile(
    r"\b(si|correcto|confirmo|dale|esta bien|perfecto|asi es|de acuerdo|ok)\b"
)
NO_ENTIENDE = re.compile(r"\b(no te entendi|no te sigo|repetime|como)\b")


@dataclass
class Resultado:
    tipo: Literal["confirmacion", "correccion", "sin_entender"]
    items: list[ItemParte]
    descripcion: str = ""


def _unidad_en(texto: str) -> str | None:
    normalizado = normalizar(texto)
    for palabra, unidad in UNIDADES:
        if re.search(rf"(?<![a-z0-9]){re.escape(palabra)}(?![a-z0-9])", normalizado):
            return unidad
    return None


def _es_confirmacion(normalizado: str) -> bool:
    if NO_ENTIENDE.search(normalizado):
        return False
    if re.search(r"\bno\b", normalizado):
        return False
    return bool(CONFIRMA.search(normalizado))


def _cerca(a: float | None, b: float | None, ua: str | None, ub: str | None) -> bool:
    if a is None or b is None:
        return False
    if ua in A_KG and ub in A_KG:
        a_kg = a * A_KG[ua]
        b_kg = b * A_KG[ub]
        return abs(a_kg - b_kg) <= max(0.6, abs(b_kg) * 0.02)
    return abs(a - b) <= max(0.051, abs(b) * 0.015)


def _variable_en(texto: str, tag: str | None, unidad: str | None) -> str | None:
    if "diferencial" in texto:
        return "presion_diferencial"
    if "descarga" in texto:
        return "presion_descarga_local"
    if any(palabra in texto for palabra in ("grados", "rodamiento", "pistola", "temperatura")):
        return "temperatura_rodamiento_ir"
    if any(palabra in texto for palabra in ("gotea", "goteando", "empaquetadura")):
        return "goteo_empaquetadura"
    if any(palabra in texto for palabra in ("aceite", "visor")):
        return "nivel_aceite_visor"
    if "correa" in texto:
        return "estado_correas"
    if any(palabra in texto for palabra in ("metros", "nivel")):
        return "nivel"
    if any(palabra in texto for palabra in ("parada", "reserva", "disparada", "no arranca")):
        return "estado"
    if unidad == "degC":
        return "temperatura_rodamiento_ir"
    if unidad in A_KG and tag and tag.startswith("F-"):
        return "presion_diferencial"
    if unidad in A_KG and tag and tag.startswith("B-"):
        return "presion_descarga_local"
    if unidad == "m":
        return "nivel"
    if unidad == "gotas/min":
        return "goteo_empaquetadura"
    return None


def _unidad_para(
    texto: str,
    tag: str | None,
    variable: str | None,
    catalogo: CatalogoPlanta,
) -> str | None:
    unidad = _unidad_en(texto)
    if unidad is not None:
        return unidad
    if variable == "temperatura_rodamiento_ir":
        return "degC"
    if variable == "nivel":
        return "m"
    if variable == "goteo_empaquetadura":
        return "gotas/min"
    if variable == "presion_diferencial":
        return "kg/cm2"
    if variable == "presion_descarga_local":
        return catalogo.unidad_manometro(tag) or "kg/cm2"
    return None


def _indice_item(
    items: list[ItemParte],
    tag: str | None,
    valor: float | None = None,
    unidad: str | None = None,
    variable: str | None = None,
) -> int | None:
    candidatos = [
        indice
        for indice, item in enumerate(items)
        if (tag is None or item.tag == tag)
        and (variable is None or item.variable == variable)
    ]
    if valor is not None:
        exactos = [
            indice
            for indice in candidatos
            if _cerca(items[indice].valor, valor, items[indice].unidad, unidad)
        ]
        if exactos:
            return exactos[0]
    if candidatos:
        return candidatos[0]
    if valor is not None:
        for indice, item in enumerate(items):
            if _cerca(item.valor, valor, item.unidad, unidad):
                return indice
    return None


def _corregir_equipo(
    normalizado: str, items: list[ItemParte], catalogo: CatalogoPlanta
) -> tuple[list[ItemParte], bool]:
    normalizado = normalizado.replace("era del ", "era de el ")
    if "era de" not in normalizado:
        return items, False
    pos_era = normalizado.index("era de")
    resto = normalizado[pos_era + len("era de") :]
    pos_no = resto.find("no de")
    nuevo_texto = resto[:pos_no] if pos_no >= 0 else resto
    viejo_texto = resto[pos_no + len("no de") :] if pos_no >= 0 else ""
    tag_nuevo = catalogo.buscar_tag(nuevo_texto)
    if tag_nuevo is None:
        return items, False

    numeros_previos = numeros(normalizado[:pos_era])
    valor = numeros_previos[-1][2] if numeros_previos else None
    tag_viejo = catalogo.buscar_tag(viejo_texto) if viejo_texto else None

    indice = _indice_item(items, tag_viejo, valor)
    if indice is None and valor is not None:
        indice = _indice_item(items, None, valor)
    if indice is None:
        return items, False

    salida = list(items)
    item = salida[indice]
    variable = _variable_en(normalizado, tag_nuevo, item.unidad) or item.variable
    observacion = item.observacion
    if variable in {"presion_diferencial", "temperatura_rodamiento_ir"}:
        observacion = _observacion_numerica(variable, item.valor, item.unidad)
    salida[indice] = replace(
        item,
        tag=tag_nuevo,
        variable=variable,
        observacion=observacion,
    )
    return salida, salida != items


def _corregir_unidad(
    normalizado: str, items: list[ItemParte], catalogo: CatalogoPlanta
) -> tuple[list[ItemParte], bool]:
    if "no en" not in normalizado:
        return items, False
    pos_no = normalizado.index("no en")
    antes, despues = normalizado[:pos_no], normalizado[pos_no + len("no en") :]
    if not any(palabra in antes for palabra in ("es en", "esta en", "estaba en")):
        return items, False
    tag = catalogo.buscar_tag(antes)
    if tag is None:
        return items, False
    unidad_nueva = _unidad_en(antes)
    unidad_vieja = _unidad_en(despues)
    if unidad_nueva is None or unidad_vieja is None or unidad_nueva == unidad_vieja:
        return items, False

    indice = None
    for candidato, item in enumerate(items):
        if item.tag == tag and item.unidad == unidad_vieja:
            indice = candidato
            break
    if indice is None or items[indice].unidad == unidad_nueva:
        return items, False
    salida = list(items)
    salida[indice] = replace(salida[indice], unidad=unidad_nueva)
    return salida, True


def _corregir_valor(
    normalizado: str, items: list[ItemParte], catalogo: CatalogoPlanta
) -> tuple[list[ItemParte], bool]:
    if "no en" in normalizado:
        pos_no = normalizado.index("no en")
        antes, despues = normalizado[:pos_no], normalizado[pos_no + len("no en") :]
        if not any(palabra in antes for palabra in ("estaba en", "esta en")):
            return items, False
        tag = catalogo.buscar_tag(antes)
        if tag is None:
            return items, False
        nuevos = numeros(antes)
        viejos = numeros(despues)
        if not nuevos:
            return items, False
        valor_nuevo = nuevos[-1][2]
        valor_viejo = viejos[0][2] if viejos else None
        unidad_nueva = _unidad_en(antes)
        unidad_vieja = _unidad_en(despues)
        variable = _variable_en(antes, tag, unidad_nueva)
        indice = _indice_item(items, tag, valor_viejo, unidad_vieja, variable)
        if indice is None:
            if variable is None:
                return items, False
            unidad = unidad_nueva or _unidad_para(antes, tag, variable, catalogo)
            nuevo = ItemParte(
                tag,
                variable,
                valor_nuevo,
                unidad,
                _observacion_numerica(variable, valor_nuevo, unidad),
            )
            if nuevo in items:
                return items, False
            return items + [nuevo], True
        salida = list(items)
        item = salida[indice]
        unidad = unidad_nueva or item.unidad
        observacion = item.observacion
        if item.variable in {"presion_diferencial", "temperatura_rodamiento_ir"}:
            observacion = _observacion_numerica(item.variable, valor_nuevo, unidad)
        salida[indice] = replace(
            item,
            valor=valor_nuevo,
            unidad=unidad,
            observacion=observacion,
        )
        return salida, True

    if "estaba en" not in normalizado and "esta en" not in normalizado:
        return items, False
    marca = "estaba en" if "estaba en" in normalizado else "esta en"
    pos = normalizado.index(marca)
    tag = catalogo.buscar_tag(normalizado[:pos]) or catalogo.buscar_tag(normalizado)
    if tag is None:
        return items, False
    encontrados = numeros(normalizado[pos:])
    if not encontrados:
        return items, False
    valor = encontrados[0][2]
    unidad = _unidad_en(normalizado[pos:])
    variable = _variable_en(normalizado[pos:], tag, unidad)
    indice = _indice_item(items, tag, None, None, variable)
    if indice is None:
        if variable is None:
            return items, False
        unidad = unidad or _unidad_para(normalizado[pos:], tag, variable, catalogo)
        nuevo = ItemParte(
            tag,
            variable,
            valor,
            unidad,
            _observacion_numerica(variable, valor, unidad),
        )
        if nuevo in items:
            return items, False
        return items + [nuevo], True
    salida = list(items)
    item = salida[indice]
    unidad = unidad or item.unidad
    observacion = item.observacion
    if item.variable in {"presion_diferencial", "temperatura_rodamiento_ir"}:
        observacion = _observacion_numerica(item.variable, valor, unidad)
    salida[indice] = replace(item, valor=valor, unidad=unidad, observacion=observacion)
    return salida, True


def _agregar_faltante(
    normalizado: str, items: list[ItemParte], catalogo: CatalogoPlanta
) -> tuple[list[ItemParte], bool]:
    coincidencia = re.search(r"\b(?:te\s+)?falto\s+([^.?!;]+)", normalizado)
    if coincidencia is None:
        return items, False
    texto = coincidencia.group(1)
    tag = catalogo.buscar_tag(texto)
    if tag is None:
        return items, False
    encontrados = numeros(texto)
    if not encontrados:
        return items, False
    valor = encontrados[-1][2]
    variable = _variable_en(texto, tag, _unidad_en(texto))
    if variable is None:
        return items, False
    unidad = _unidad_para(texto, tag, variable, catalogo)
    nuevo = ItemParte(
        tag,
        variable,
        valor,
        unidad,
        _observacion_numerica(variable, valor, unidad),
    )
    if nuevo in items:
        return items, False
    return items + [nuevo], True


def _quitar_sobrante(
    normalizado: str, items: list[ItemParte], catalogo: CatalogoPlanta
) -> tuple[list[ItemParte], bool]:
    if "no lo dije" not in normalizado:
        return items, False
    coincidencia = re.search(r"\blo de (.+?) no lo dije\b", normalizado)
    texto = coincidencia.group(1) if coincidencia else normalizado
    tag = catalogo.buscar_tag(texto)
    if tag is None:
        return items, False
    salida = [item for item in items if item.tag != tag]
    return salida, salida != items


def _resolver_pregunta(
    normalizado: str,
    estado,
    catalogo: CatalogoPlanta,
) -> Resultado:
    ambiguedades = detectar(estado.items, estado.texto, catalogo)
    if not ambiguedades:
        return Resultado("sin_entender", estado.items, "no hay ambigüedad pendiente")

    ambiguedad = ambiguedades[0]
    items = list(estado.items)
    if ambiguedad.tipo == "equipo":
        tag = catalogo.buscar_tag(normalizado)
        if tag is None:
            return Resultado("sin_entender", items, "no se entendió el equipo")
        for indice, item in enumerate(items):
            if item.tag is None:
                items[indice] = replace(item, tag=tag)
        return Resultado("correccion", items, f"equipo resuelto: {tag}")

    encontrados = numeros(normalizado)
    if not encontrados:
        return Resultado("sin_entender", items, "no se entendió el valor")
    valor = encontrados[-1][2]
    unidad = _unidad_en(normalizado) or items[ambiguedad.indice].unidad
    items[ambiguedad.indice] = replace(
        items[ambiguedad.indice], valor=valor, unidad=unidad
    )
    return Resultado("correccion", items, f"valor resuelto: {valor} {unidad or ''}".strip())


def interpretar(texto: str, estado, catalogo: CatalogoPlanta) -> Resultado:
    normalizado = normalizar(texto)
    if estado.estado == "PREGUNTA":
        return _resolver_pregunta(normalizado, estado, catalogo)

    if _es_confirmacion(normalizado):
        return Resultado("confirmacion", estado.items, "confirmado")

    items = list(estado.items)
    cambios = False
    for funcion in (_corregir_equipo, _corregir_unidad, _corregir_valor):
        items, cambio = funcion(normalizado, items, catalogo)
        cambios = cambios or cambio
    items, cambio = _agregar_faltante(normalizado, items, catalogo)
    cambios = cambios or cambio
    items, cambio = _quitar_sobrante(normalizado, items, catalogo)
    cambios = cambios or cambio

    if any(item.tag is None for item in items):
        tag = catalogo.buscar_tag(normalizado)
        if tag is not None:
            items = [replace(item, tag=tag) if item.tag is None else item for item in items]
            cambios = True

    if any(item.variable == "presion_diferencial" and item.valor is None for item in items):
        encontrados = numeros(normalizado)
        if len(encontrados) == 1 and not any(
            palabra in normalizado for palabra in ("no en", "falto", "era de", "no lo dije")
        ):
            indice = next(
                indice
                for indice, item in enumerate(items)
                if item.variable == "presion_diferencial" and item.valor is None
            )
            valor = encontrados[0][2]
            unidad = _unidad_en(normalizado) or items[indice].unidad
            items[indice] = replace(items[indice], valor=valor, unidad=unidad)
            cambios = True

    if cambios:
        return Resultado("correccion", items, "corrección aplicada")
    return Resultado("sin_entender", estado.items, "no se entendió la respuesta")
